import {
  apiRequest
} from "./api.js";
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
  activateTab,
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
  syncSourceToTranslation
} from "./pages.js";
import {
  makeParagraphGroup
} from "./paragraphs.js";
import {
  renderUncertaintyGroupList
} from "./uncertainty_render.js";

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

  requestAnimationFrame(() => {
    const requestedPageNumber = Number(
      options.anchorPageNumber ?? options.resumePageNumber,
    );
    if (Number.isInteger(requestedPageNumber)) {
      const anchorPage = renderedPageElement(translationContent, requestedPageNumber);
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
    requestAnimationFrame(() => {
      state.allowPositionPersistence = true;
    });
  });
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
  if (state.review?.cost) {
    document.getElementById("review-cost").replaceChildren(costBreakdown(state.review.cost));
  }
  document.title = `${filename} · Transcribl`;
  configureExportLinks(state.jobId, {
    pdf: exportPdfLink,
    tex: exportLatexLink,
    md: exportMarkdownLink,
    txt: exportTextLink,
  });
  updateReviewSummary();
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

export async function loadReview(options = {}) {
  const review = await apiRequest(
    `/api/jobs/${encodeURIComponent(state.jobId)}/review`,
  );
  state.review = review || { pages: [] };
  state.sourcePageNumber = null;
  state.lastPersistedPage = Number(state.review.continue_page) || null;
  const hasAnchor = options.anchorPageNumber !== undefined;
  renderReview(options.drafts instanceof Map ? options.drafts : new Map(), {
    centerPageNumber: options.centerPageNumber,
    anchorPageNumber: options.anchorPageNumber,
    anchorViewportOffset: options.anchorViewportOffset,
    focusBlockId: options.focusBlockId,
    resetScroll: !hasAnchor,
  });
  activateTab("review");
}
