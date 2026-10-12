import {
  makeTranslationBlock
} from "./blocks.js";
import {
  exportLatexLink,
  exportMarkdownLink,
  exportPdfLink,
  exportTextLink,
  reviewDocument,
  reviewEditor,
  reviewLibrary,
  reviewProgress,
  sourceScroll,
  state,
  translationContent,
  translationScroll,
  uncertaintyListButton
} from "./context.js";
import {
  asText,
  createElement,
  elementPositionInScroller,
  makePageLabel,
  renderedPageElement
} from "./dom.js";
import {
  configureExportLinks,
  costBreakdown
} from "./exports.js";
import {
  unresolvedUncertainties
} from "./highlights.js";
import {
  buildReviewIndexes
} from "./indexes.js";
import {
  reviewPageAnchor,
  syncSourceToTranslation
} from "./pages.js";
import {
  makeParagraphGroup
} from "./paragraphs.js";
import {
  renderUncertaintyGroupList
} from "./uncertainty_render.js";

import { resizeReviewWorkspace } from "./viewport.js";
import { notifyDraftsChanged, restoreEditorSelection } from "./drafts.js";

let renderObserver = null;

export function updateReviewSummary() {
  if (!state.review) {
    return;
  }
  const blocks = [...state.blockIndex.values()].map((entry) => entry.block);
  const accepted = blocks.filter((block) => block.review_status === "accepted").length;
  const uncertain = blocks.reduce(
    (count, block) => count + unresolvedUncertainties(block).length,
    0,
  );
  state.uncertaintyGroups = Array.isArray(state.review?.uncertainty_groups)
    ? [...state.review.uncertainty_groups]
    : [];
  uncertaintyListButton.disabled = state.uncertaintyGroups.length === 0;
  uncertaintyListButton.textContent = `Uncertain terms (${uncertain})`;
  renderUncertaintyGroupList(state.uncertaintyGroups);
  const classificationChecks = blocks.filter(
    (block) => block.classification_review_required === true,
  ).length;
  const validation =
    blocks.length > 0 ? `${accepted} of ${blocks.length} validated` : "No text blocks";
  const uncertaintySummary =
    uncertain > 0
      ? `${validation} · ${uncertain} ${uncertain === 1 ? "uncertainty" : "uncertainties"}`
      : `${validation} · no open uncertainties`;
  reviewProgress.textContent = classificationChecks
    ? `${uncertaintySummary} · ${classificationChecks} classification ${
        classificationChecks === 1 ? "check" : "checks"
      }`
    : uncertaintySummary;
}

export function renderAllReviewPages(options = {}) {
  const generation = ++state.renderGeneration;
  renderObserver?.disconnect();
  if (state.scrollFrame !== null) {
    cancelAnimationFrame(state.scrollFrame);
    state.scrollFrame = null;
  }
  translationContent.replaceChildren();
  translationContent.dataset.renderedPageCount = asText(state.reviewPages.length);

  if (!state.reviewPages.length) {
    translationContent.append(
      createElement("p", "lede", "No translated pages were returned."),
    );
  }

  for (const page of state.reviewPages) {
    const translatedPage = createElement("section", "review-page");
    const pageNumber = asText(page.original_page_number);
    translatedPage.dataset.pageNumber = pageNumber;
    translatedPage.append(makePageLabel(page));

    for (const block of Array.isArray(page.blocks) ? page.blocks : []) {
      const paragraphGroup = state.paragraphGroupByFragment.get(asText(block.block_id));
      if (paragraphGroup) {
        if (asText(block.block_id) === asText(paragraphGroup.paragraph_id)) {
          translatedPage.append(makeParagraphGroup(paragraphGroup));
        }
        continue;
      }
      translatedPage.append(
        makeTranslationBlock(
          block,
          page,
          state.reviewDrafts.get(asText(block.block_id)),
        ),
      );
    }
    translationContent.append(translatedPage);
  }

  if (options.resetScroll) {
    sourceScroll.scrollTop = 0;
    translationScroll.scrollTop = 0;
  }

  const finishRender = () => {
    if (generation !== state.renderGeneration) return;
    if (!translationScroll.clientHeight) {
      renderObserver = new ResizeObserver(() => {
        if (translationScroll.clientHeight) {
          renderObserver?.disconnect();
          requestAnimationFrame(finishRender);
        }
      });
      renderObserver.observe(translationScroll);
      return;
    }
    resizeReviewWorkspace();
    const requestedPageNumber = Number(
      options.anchorPageNumber ?? options.resumePageNumber,
    );
    if (Number.isInteger(requestedPageNumber)) {
      const anchorPage = Number.isFinite(options.anchorViewportOffset)
        ? renderedPageElement(translationContent, requestedPageNumber)
        : reviewPageAnchor(requestedPageNumber);
      if (anchorPage && Number.isFinite(options.anchorViewportOffset)) {
        const currentOffset =
          anchorPage.getBoundingClientRect().top -
          translationScroll.getBoundingClientRect().top;
        translationScroll.scrollTop += currentOffset - options.anchorViewportOffset;
      } else if (anchorPage) {
        translationScroll.scrollTop = elementPositionInScroller(
          anchorPage,
          translationScroll,
        );
      }
    }
    syncSourceToTranslation();
    if (options.focusBlockId) {
      const editor = [...translationContent.querySelectorAll(".translated-editor")].find(
        (element) => element.dataset.blockId === asText(options.focusBlockId),
      );
      editor?.focus({ preventScroll: true });
    }
    restoreEditorSelection(options.selection);
    requestAnimationFrame(() => {
      if (generation === state.renderGeneration) state.allowPositionPersistence = true;
    });
  };
  requestAnimationFrame(finishRender);
}
export function renderReview(drafts = new Map(), options = {}) {
  state.allowPositionPersistence = false;
  state.reviewDrafts = new Map(drafts);
  state.reviewPages = Array.isArray(state.review?.pages)
    ? [...state.review.pages].sort(
        (left, right) =>
          Number(left.original_page_number) - Number(right.original_page_number),
      )
    : [];
  buildReviewIndexes(state.reviewPages);

  const filename =
    asText(state.review?.filename) ||
    asText(state.review?.source_file_name) ||
    asText(state.job?.filename) ||
    "Translated PDF";
  const stableRunId = asText(state.review?.translation_run_id);
  if (/^[0-9a-f]{32}$/.test(stableRunId)) {
    state.jobId = stableRunId;
    window.history.replaceState({}, "", `/?job=${encodeURIComponent(stableRunId)}`);
  }
  reviewLibrary.hidden = true;
  reviewEditor.hidden = false;
  reviewDocument.textContent = filename;
  document.getElementById("review-cost").replaceChildren(...(state.review?.cost ? [costBreakdown(state.review.cost)] : []));
  document.title = `${filename} · Transcribl`;
  configureExportLinks(state.jobId, {
    pdf: exportPdfLink,
    tex: exportLatexLink,
    md: exportMarkdownLink,
    txt: exportTextLink,
  });
  updateReviewSummary();
  notifyDraftsChanged();
  resizeReviewWorkspace();
  const focusedPage = options.focusBlockId
    ? state.blockIndex.get(asText(options.focusBlockId))?.page.original_page_number
    : null;
  renderAllReviewPages({
    ...options,
    resumePageNumber:
      options.centerPageNumber ||
      focusedPage ||
      Number(state.review?.continue_page) ||
      state.reviewPages[0]?.original_page_number,
  });
}
