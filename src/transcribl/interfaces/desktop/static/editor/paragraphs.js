import {
  state
} from "./context.js";
import {
  asText,
  createElement,
  humanize,
  reviewStatusClass
} from "./dom.js";
import {
  renderHighlightedText,
  unresolvedUncertainties
} from "./highlights.js";

export function paragraphGroupEntries(group) {
  return group.fragment_block_ids
    .map((blockId) => state.blockIndex.get(asText(blockId)))
    .filter(Boolean);
}

export function paragraphReviewStatus(entries) {
  const statuses = entries.map(({ block }) => asText(block.review_status, "unreviewed"));
  if (statuses.every((status) => status === "accepted")) {
    return "accepted";
  }
  if (statuses.some((status) => status === "needs_work")) {
    return "needs_work";
  }
  return statuses.some((status) => status !== "unreviewed") ? "in_review" : "unreviewed";
}

export function makeParagraphGroup(group) {
  const entries = paragraphGroupEntries(group);
  const firstEntry = entries[0];
  const article = createElement(
    "article",
    "translation-block paragraph-group page-sync-anchor",
  );
  article.dataset.blockId = asText(group.paragraph_id);
  article.dataset.paragraphId = asText(group.paragraph_id);
  article.dataset.pageNumber = asText(firstEntry?.page.original_page_number, "1");

  const meta = createElement("div", "block-meta");
  meta.append(
    createElement("span", "", "Body"),
    createElement(
      "span",
      "paragraph-continuation",
      `Combined paragraph · physical pages ${entries
        .map(({ page }) => page.original_page_number)
        .join("–")}`,
    ),
  );
  const revisedCount = entries.filter(({ block }) => Number(block.base_revision) > 0).length;
  meta.append(
    createElement(
      "span",
      revisedCount ? "provenance edited" : "provenance machine",
      revisedCount
        ? `${revisedCount} ${revisedCount === 1 ? "fragment" : "fragments"} manually reviewed`
        : "Machine translation",
    ),
  );
  if (entries.some(({ block }) => block.classification_review_required === true)) {
    meta.append(createElement("span", "classification-warning", "Check continuation seam"));
  }
  const groupStatus = paragraphReviewStatus(entries);
  meta.append(
    createElement(
      "span",
      `status ${reviewStatusClass(groupStatus)}`.trim(),
      humanize(groupStatus),
    ),
  );

  const flow = createElement("div", "merged-paragraph-editor");
  flow.dataset.testid = "merged-paragraph-editor";
  flow.setAttribute("role", "group");
  flow.setAttribute(
    "aria-label",
    `Combined paragraph across ${entries.length} physical pages`,
  );
  const fallbackContainer = createElement("div", "uncertainty-fallbacks");
  for (const [index, entry] of entries.entries()) {
    const { block, page } = entry;
    if (index > 0) {
      flow.append(document.createTextNode(" "));
      const boundary = createElement(
        "button",
        "paragraph-page-boundary page-sync-anchor",
        `Physical page ${page.original_page_number}`,
      );
      boundary.type = "button";
      boundary.contentEditable = "false";
      boundary.dataset.action = "show-paragraph-page";
      boundary.dataset.pageNumber = asText(page.original_page_number);
      boundary.setAttribute(
        "aria-label",
        `Paragraph continues on physical page ${page.original_page_number}; show that page image`,
      );
      flow.append(boundary, document.createTextNode(" "));
    }

    const editor = createElement("span", "translated-editor paragraph-fragment-editor");
    editor.dataset.testid = "translated-block";
    editor.dataset.blockId = asText(block.block_id);
    editor.dataset.pageNumber = asText(page.original_page_number);
    editor.dataset.baseRevision = asText(block.base_revision, "0");
    editor.contentEditable = "true";
    editor.tabIndex = 0;
    editor.spellcheck = true;
    editor.setAttribute("role", "textbox");
    editor.setAttribute(
      "aria-label",
      `Paragraph fragment from physical page ${page.original_page_number}`,
    );
    const effectiveText = asText(block.effective_text, asText(block.machine_text));
    const draftText = state.reviewDrafts.get(asText(block.block_id))?.text;
    const displayedText = draftText === undefined ? effectiveText : draftText;
    const handled = renderHighlightedText(editor, displayedText, block);
    if (displayedText !== effectiveText) {
      editor.classList.add("is-dirty");
      article.classList.add("is-dirty");
    }
    flow.append(editor);

    for (const uncertainty of unresolvedUncertainties(block)) {
      const uncertaintyId = asText(uncertainty.uncertainty_id);
      if (handled.has(uncertaintyId)) {
        continue;
      }
      const fallback = createElement(
        "button",
        "uncertainty-fallback",
        `Review page ${page.original_page_number}: ${asText(
          uncertainty.source_term,
          "uncertain passage",
        )}`,
      );
      fallback.type = "button";
      fallback.dataset.testid = "uncertainty-highlight";
      fallback.dataset.action = "review-uncertainty";
      fallback.dataset.uncertaintyId = uncertaintyId;
      fallbackContainer.append(fallback);
    }
  }

  const help = createElement(
    "p",
    "paragraph-group-help",
    "Edit each page fragment at the fixed page marker; Save or Validate applies to the whole paragraph.",
  );
  const actions = createElement("div", "block-actions");
  const save = createElement("button", "block-action save-action", "Save paragraph");
  save.type = "button";
  save.dataset.testid = "save-paragraph";
  save.dataset.action = "save-paragraph";
  save.dataset.reviewStatus = "in_review";
  const validate = createElement(
    "button",
    "block-action validate-action",
    "Validate paragraph",
  );
  validate.type = "button";
  validate.dataset.testid = "validate-paragraph";
  validate.dataset.action = "save-paragraph";
  validate.dataset.reviewStatus = "accepted";
  const message = createElement("span", "block-message");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  actions.append(save, validate, message);

  article.append(meta, flow, help);
  if (fallbackContainer.childElementCount) {
    article.append(fallbackContainer);
  }
  article.append(actions);
  return article;
}
