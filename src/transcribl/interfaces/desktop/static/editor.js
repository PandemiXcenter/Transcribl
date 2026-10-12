(async () => {
const state = {
  config: null,
  selectedFile: null,
  jobId: null,
  job: null,
  review: null,
  pollTimer: null,
  pollFailures: 0,
  blockIndex: new Map(),
  uncertaintyIndex: new Map(),
  uncertaintyGroups: [],
  reviewPages: [],
  paragraphGroups: [],
  paragraphGroupByFragment: new Map(),
  reviewDrafts: new Map(),
  footnoteEntrypointsByOwner: new Map(),
  sourcePageNumber: null,
  reviewZoomPercent: null,
  allowPositionPersistence: false,
  lastPersistedPage: null,
  positionQueue: Promise.resolve(),
  activeUncertaintyId: null,
  scrollFrame: null,
};

const reviewDocument = document.querySelector("#review-document");
const reviewProgress = document.querySelector("#review-progress");
const exportPdfLink = document.querySelector("#export-pdf-link");
const exportLatexLink = document.querySelector("#export-latex-link");
const exportMarkdownLink = document.querySelector("#export-markdown-link");
const exportTextLink = document.querySelector("#export-text-link");
const activePageLabel = document.querySelector("#active-page-label");
const sourceScroll = document.querySelector("#source-scroll");
const translationScroll = document.querySelector("#translation-scroll");
const sourceContent = document.querySelector("#source-content");
const translationContent = document.querySelector("#translation-content");
const sourcePageLabel = document.querySelector("#source-page-label");
const sourcePageImage = document.querySelector("#source-page-image");
const fullSizePageLink = document.querySelector("#full-size-page-link");
const reviewZoomSelect = document.querySelector("#review-zoom-select");
const uncertaintyDialog = document.querySelector("#uncertainty-dialog");
const uncertaintyListButton = document.querySelector("#uncertainty-list-button");
const uncertaintyListDialog = document.querySelector("#uncertainty-list-dialog");
const uncertaintyGroupList = document.querySelector("#uncertainty-group-list");
const uncertaintyGroupEmpty = document.querySelector("#uncertainty-group-empty");
const uncertaintyForm = document.querySelector("#uncertainty-form");
const closeUncertaintyButton = document.querySelector("#close-uncertainty");
const cancelUncertaintyButton = document.querySelector("#cancel-uncertainty");
const translateOneButton = document.querySelector("#translate-one");
const translateAllButton = document.querySelector("#translate-all");
const replacementInput = document.querySelector("#replacement-input");
const replacementError = document.querySelector("#replacement-error");
const replacementField = document.querySelector("#replacement-field");
const fallbackInstruction = document.querySelector("#fallback-instruction");
const reviewPanel = document.querySelector("#review-panel");
const reviewLibrary = document.querySelector("#review-library");
const reviewEditor = document.querySelector("#review-editor");
const reviewList = document.querySelector("#review-list");
const reviewListEmpty = document.querySelector("#review-list-empty");
const refreshTranslationsButton = document.querySelector("#refresh-translations");
const backToTranslationsButton = document.querySelector("#back-to-translations");
const globalAlert = document.querySelector("#global-alert");
const globalAlertMessage = document.querySelector("#global-alert-message");
const dismissAlert = document.querySelector("#dismiss-alert");
const newTranslationButton = document.querySelector("#new-translation");
const EDITABLE_BLOCK_TYPES = [
  "title",
  "subtitle",
  "byline",
  "heading",
  "body",
  "list_item",
  "quote",
  "caption",
  "footnote",
  "page_number",
  "header",
  "footer",
  "equation",
  "other",
];

function createElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined && text !== null) {
    element.textContent = String(text);
  }
  return element;
}

function asText(value, fallback = "") {
  if (value === undefined || value === null) {
    return fallback;
  }
  return String(value);
}

function showGlobalError(message) {
  globalAlertMessage.textContent = message;
  globalAlert.hidden = false;
  globalAlert.focus();
}

function clearGlobalError() {
  globalAlert.hidden = true;
  globalAlertMessage.textContent = "";
}

function setInlineError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function getCookie(name) {
  const prefix = `${name}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (!cookie) {
    return "";
  }
  try {
    return decodeURIComponent(cookie.slice(prefix.length));
  } catch {
    return cookie.slice(prefix.length);
  }
}

function errorMessageFromPayload(payload, status) {
  const detail = payload?.detail ?? payload?.error ?? payload?.message;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (typeof entry?.msg === "string" ? entry.msg : null))
      .filter(Boolean);
    if (messages.length) {
      return messages.join(" ");
    }
  }
  if (status === 409) {
    return "This document changed since it was loaded. Refresh the review and try again.";
  }
  if (status === 413) {
    return "This PDF is larger than the configured upload limit.";
  }
  return `The request could not be completed (HTTP ${status}).`;
}

async function apiRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", getCookie("at_csrf"));
  }

  let response;
  try {
    response = await fetch(`/backend${path}`, {
      ...options,
      method,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Transcribl could not reach the local server.");
  }

  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    throw new Error(errorMessageFromPayload(payload, response.status));
  }
  return payload;
}

function humanize(value) {
  const text = asText(value);
  if (!text) {
    return "Unknown";
  }
  return text
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function pageDescription(page) {
  const parts = [];
  if (page.pdf_page_label) {
    parts.push(`PDF label ${asText(page.pdf_page_label)}`);
  }
  if (page.detected_printed_page_label) {
    parts.push(`printed ${asText(page.detected_printed_page_label)}`);
  }
  return parts.join(" · ");
}

function makePageLabel(page) {
  const label = createElement(
    "p",
    "page-label",
    `Physical page ${Number(page.original_page_number) || 1}`,
  );
  const details = pageDescription(page);
  label.classList.add("page-sync-anchor");
  label.dataset.pageNumber = asText(page.original_page_number);
  if (details) {
    label.append(createElement("span", "", details));
  }
  return label;
}

function reviewStatusClass(status) {
  if (status === "accepted") {
    return "accepted";
  }
  if (status === "needs_work") {
    return "needs-work";
  }
  return "";
}

function unresolvedUncertainties(block) {
  return Array.isArray(block.uncertainties)
    ? block.uncertainties.filter((uncertainty) => !uncertainty.resolved)
    : [];
}

function uncertaintyNeedle(uncertainty) {
  return asText(
    uncertainty.highlight_text ||
      uncertainty.proposed_translation ||
      uncertainty.source_term,
  ).trim();
}

function findAvailableRange(text, needle, occupied) {
  if (!needle) {
    return null;
  }
  let index = text.indexOf(needle);
  while (index !== -1) {
    const start = Array.from(text.slice(0, index)).length;
    const end = start + Array.from(needle).length;
    const overlaps = occupied.some((range) => start < range.end && end > range.start);
    if (!overlaps) {
      return { start, end };
    }
    index = text.indexOf(needle, index + Math.max(needle.length, 1));
  }

  const lowerText = text.toLocaleLowerCase();
  const lowerNeedle = needle.toLocaleLowerCase();
  if (lowerNeedle.length !== needle.length) {
    return null;
  }
  index = lowerText.indexOf(lowerNeedle);
  while (index !== -1) {
    const start = Array.from(text.slice(0, index)).length;
    const end = start + Array.from(text.slice(index, index + needle.length)).length;
    const overlaps = occupied.some((range) => start < range.end && end > range.start);
    if (!overlaps) {
      return { start, end };
    }
    index = lowerText.indexOf(lowerNeedle, index + Math.max(needle.length, 1));
  }
  return null;
}

function activateUncertaintyFromEvent(event, uncertaintyId) {
  event.preventDefault();
  event.stopPropagation();
  openUncertainty(uncertaintyId);
}

function makeUncertaintyMark(text, entry) {
  const mark = createElement("mark", "uncertainty-mark", text);
  mark.dataset.testid = "uncertainty-highlight";
  mark.dataset.action = "review-uncertainty";
  mark.dataset.uncertaintyId = asText(entry.uncertainty.uncertainty_id);
  mark.tabIndex = 0;
  mark.setAttribute("role", "button");
  mark.setAttribute("contenteditable", "false");
  mark.setAttribute(
    "aria-label",
    `Uncertain translation: ${text}. Open reviewer options.`,
  );
  return mark;
}

function footnoteEntrypointsForBlock(block) {
  return state.footnoteEntrypointsByOwner.get(asText(block.block_id)) || [];
}

function makeFootnoteEntrypointMarker(entrypoint) {
  const marker = createElement("sup", "footnote-entrypoint-marker", entrypoint.text);
  marker.dataset.editorDisplayOnly = "true";
  marker.dataset.footnoteId = entrypoint.identity;
  marker.setAttribute("contenteditable", "false");
  marker.setAttribute("role", "note");
  marker.setAttribute("aria-label", `Footnote entrypoint ${entrypoint.identity}`);
  marker.title = `Footnote entrypoint ${entrypoint.identity}`;
  return marker;
}

function appendTextWithFootnoteEntrypoints(
  container,
  codePoints,
  start,
  end,
  entrypoints,
) {
  let cursor = start;
  for (const entrypoint of entrypoints) {
    const offset = Math.min(Math.max(entrypoint.offset, start), end);
    if (offset < cursor) {
      continue;
    }
    if (offset > cursor) {
      container.append(document.createTextNode(codePoints.slice(cursor, offset).join("")));
    }
    container.append(makeFootnoteEntrypointMarker(entrypoint));
    cursor = offset;
  }
  if (cursor < end) {
    container.append(document.createTextNode(codePoints.slice(cursor, end).join("")));
  }
}

function renderHighlightedText(container, text, block) {
  const codePoints = Array.from(text);
  const entrypoints = footnoteEntrypointsForBlock(block).map((entrypoint) => ({
    ...entrypoint,
    offset: Math.min(entrypoint.offset, codePoints.length),
  }));
  const ranges = [];
  const handled = new Set();
  for (const uncertainty of unresolvedUncertainties(block)) {
    const entry = state.uncertaintyIndex.get(asText(uncertainty.uncertainty_id));
    if (!entry) {
      continue;
    }
    let range = null;
    const startOffset = Number(uncertainty.start_offset);
    const endOffset = Number(uncertainty.end_offset);
    const offsetText =
      Number.isInteger(startOffset) &&
      Number.isInteger(endOffset) &&
      startOffset >= 0 &&
      endOffset > startOffset &&
      endOffset <= codePoints.length
        ? codePoints.slice(startOffset, endOffset).join("")
        : "";
    if (
      uncertainty.highlight_mode === "range" &&
      offsetText === uncertaintyNeedle(uncertainty)
    ) {
      const overlaps = ranges.some(
        (existing) => startOffset < existing.end && endOffset > existing.start,
      );
      range = overlaps ? null : { start: startOffset, end: endOffset };
    } else if (uncertainty.highlight_mode !== "block") {
      range = findAvailableRange(text, uncertaintyNeedle(uncertainty), ranges);
    }
    if (range) {
      ranges.push({ ...range, entry });
      handled.add(asText(uncertainty.uncertainty_id));
    }
  }

  ranges.sort((left, right) => left.start - right.start);
  let cursor = 0;
  for (const range of ranges) {
    if (range.start > cursor) {
      appendTextWithFootnoteEntrypoints(
        container,
        codePoints,
        cursor,
        range.start,
        entrypoints.filter(
          (entrypoint) => entrypoint.offset >= cursor && entrypoint.offset < range.start,
        ),
      );
    }
    const uncertaintyMark = makeUncertaintyMark(
      codePoints.slice(range.start, range.end).join(""),
      range.entry,
    );
    uncertaintyMark.replaceChildren();
    appendTextWithFootnoteEntrypoints(
      uncertaintyMark,
      codePoints,
      range.start,
      range.end,
      entrypoints.filter(
        (entrypoint) =>
          entrypoint.offset >= range.start && entrypoint.offset < range.end,
      ),
    );
    container.append(uncertaintyMark);
    cursor = range.end;
  }
  appendTextWithFootnoteEntrypoints(
    container,
    codePoints,
    cursor,
    codePoints.length,
    entrypoints.filter((entrypoint) => entrypoint.offset >= cursor),
  );
  return handled;
}

function editorPlainText(editor) {
  const copy = editor.cloneNode(true);
  for (const marker of copy.querySelectorAll("[data-editor-display-only='true']")) {
    marker.remove();
  }
  return copy.textContent || "";
}

function insertPlainTextAtSelection(editor, text) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    editor.append(document.createTextNode(text));
    return;
  }
  const range = selection.getRangeAt(0);
  if (!editor.contains(range.commonAncestorContainer)) {
    editor.append(document.createTextNode(text));
    return;
  }
  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  range.setStartAfter(node);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function setBlockDirty(blockElement, editor, effectiveText) {
  const dirty = editorPlainText(editor) !== effectiveText;
  editor.classList.toggle("is-dirty", dirty);
  blockElement.classList.toggle(
    "is-dirty",
    Boolean(blockElement.querySelector(".translated-editor.is-dirty")),
  );
  editor.setAttribute("aria-invalid", "false");
  return dirty;
}

function recordEditorDraft(editor) {
  const blockElement = editor.closest(".translation-block");
  const blockId = asText(editor.dataset.blockId, blockElement?.dataset.blockId);
  const entry = state.blockIndex.get(blockId);
  if (!blockElement || !entry) {
    return;
  }
  const editorialText = editorPlainText(editor);
  const effectiveText = asText(entry.block.effective_text, entry.block.machine_text);
  if (setBlockDirty(blockElement, editor, effectiveText)) {
    state.reviewDrafts.set(blockId, editorialText);
  } else {
    state.reviewDrafts.delete(blockId);
  }
}

function handleReviewClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  const actionTarget = target?.closest("[data-action]");
  if (!actionTarget || !translationContent.contains(actionTarget)) {
    return;
  }
  const action = actionTarget.dataset.action;
  if (action === "show-paragraph-page") {
    event.preventDefault();
    activateSourcePageNumber(Number(actionTarget.dataset.pageNumber));
    return;
  }
  if (action === "review-uncertainty") {
    activateUncertaintyFromEvent(event, actionTarget.dataset.uncertaintyId);
    return;
  }
  if (action === "save-paragraph") {
    const blockElement = actionTarget.closest(".paragraph-group");
    const paragraphId = asText(blockElement?.dataset.paragraphId);
    const paragraph = state.paragraphGroups.find(
      (candidate) => asText(candidate.paragraph_id) === paragraphId,
    );
    const message = blockElement?.querySelector(".block-message");
    if (!blockElement || !paragraph || !message) {
      return;
    }
    const buttons = [...blockElement.querySelectorAll("[data-action='save-paragraph']")];
    const status =
      actionTarget.dataset.reviewStatus === "accepted" ? "accepted" : "in_review";
    void saveParagraphGroup(paragraph, blockElement, status, buttons, message);
    return;
  }
  if (action !== "save-block") {
    return;
  }
  const blockElement = actionTarget.closest(".translation-block");
  const blockId = asText(blockElement?.dataset.blockId);
  const entry = state.blockIndex.get(blockId);
  const editor = blockElement?.querySelector(".translated-editor");
  const message = blockElement?.querySelector(".block-message");
  if (!blockElement || !entry || !editor || !message) {
    return;
  }
  const status = actionTarget.dataset.reviewStatus === "accepted" ? "accepted" : "in_review";
  const buttons = [...blockElement.querySelectorAll("[data-action='save-block']")];
  void saveBlock(entry.block, blockElement, editor, status, buttons, message);
}

function handleReviewKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const target = event.target instanceof Element ? event.target : null;
  const uncertainty = target?.closest("[data-action='review-uncertainty']");
  if (!uncertainty || !translationContent.contains(uncertainty)) {
    return;
  }
  if (uncertainty instanceof HTMLButtonElement) {
    return;
  }
  activateUncertaintyFromEvent(event, uncertainty.dataset.uncertaintyId);
}

function handleReviewInput(event) {
  const target = event.target instanceof Element ? event.target : null;
  const editor = target?.closest(".translated-editor");
  if (editor && translationContent.contains(editor)) {
    recordEditorDraft(editor);
  }
}

function handleReviewControlChange(event) {
  const control =
    event.target instanceof HTMLSelectElement || event.target instanceof HTMLInputElement
      ? event.target
      : null;
  if (!control || !translationContent.contains(control)) {
    return;
  }
  const blockElement = control.closest(".translation-block");
  if (!blockElement) {
    return;
  }
  if (control.dataset.action === "change-section-type") {
    const ownerField = blockElement.querySelector(".footnote-owner-field");
    const anchorField = blockElement.querySelector(".footnote-anchor-field");
    const anchorHelp = blockElement.querySelector(".footnote-anchor-help");
    if (ownerField) {
      ownerField.hidden = control.value !== "footnote";
    }
    if (anchorField) {
      anchorField.hidden = control.value !== "footnote";
    }
    if (anchorHelp) {
      anchorHelp.hidden = control.value !== "footnote";
    }
  }
  if (control.dataset.action === "change-footnote-owner") {
    const anchorInput = blockElement.querySelector(".footnote-anchor-input");
    const ownerEntry = state.blockIndex.get(control.value);
    if (anchorInput instanceof HTMLInputElement) {
      const ownerLength = asText(
        ownerEntry?.block?.effective_text,
        ownerEntry?.block?.machine_text,
      ).length;
      anchorInput.max = asText(ownerLength);
      anchorInput.value = control.value ? asText(ownerLength) : "0";
      anchorInput.disabled = !control.value;
    }
  }
  blockElement.classList.add("is-dirty");
}

function handleReviewPaste(event) {
  const target = event.target instanceof Element ? event.target : null;
  const editor = target?.closest(".translated-editor");
  if (!editor || !translationContent.contains(editor)) {
    return;
  }
  event.preventDefault();
  insertPlainTextAtSelection(editor, event.clipboardData?.getData("text/plain") || "");
  editor.dispatchEvent(new Event("input", { bubbles: true }));
}

function pageImageUrl(pageNumber) {
  return `/backend/api/jobs/${encodeURIComponent(state.jobId)}/pages/${encodeURIComponent(
    pageNumber,
  )}/image`;
}

function setReviewZoom(percent) {
  const allowedLevels = Array.isArray(state.config?.review?.zoom_levels)
    ? state.config.review.zoom_levels
    : [];
  const normalized = Number(percent);
  if (!Number.isInteger(normalized) || !allowedLevels.includes(normalized)) {
    return;
  }
  state.reviewZoomPercent = normalized;
  reviewZoomSelect.value = String(normalized);
  sourcePageImage.style.setProperty("--review-page-zoom", String(normalized / 100));
}

function handleReviewToolbarChange(event) {
  const target = event.target instanceof HTMLSelectElement ? event.target : null;
  if (target?.matches("#review-zoom-select")) {
    setReviewZoom(target.value);
  }
}

function showSourcePage(page) {
  const pageNumber = Number(page?.original_page_number) || 1;
  if (state.sourcePageNumber === pageNumber && sourcePageImage.getAttribute("src")) {
    return;
  }
  state.sourcePageNumber = pageNumber;
  const details = pageDescription(page || {});
  sourcePageLabel.replaceChildren(
    document.createTextNode(`Physical page ${pageNumber}`),
  );
  if (details) {
    sourcePageLabel.append(createElement("span", "", details));
  }
  const url = pageImageUrl(pageNumber);
  sourcePageImage.alt = `Original physical page ${pageNumber}`;
  sourcePageImage.src = url;
  fullSizePageLink.href = url;
}

function activateSourcePageNumber(pageNumber, { persist = true } = {}) {
  const pageEntry = state.reviewPages.find(
    (page) => Number(page.original_page_number) === Number(pageNumber),
  );
  if (!pageEntry) {
    return;
  }
  const label = asText(pageEntry.original_page_number);
  activePageLabel.textContent = pageEntry.pdf_page_label
    ? `Physical page ${label} · ${pageEntry.pdf_page_label}`
    : `Physical page ${label}`;
  showSourcePage(pageEntry);
  if (persist) {
    persistReviewPosition(Number(pageEntry.original_page_number));
  }
}

function provenanceLabel(block) {
  const revision = Math.max(0, Number(block.base_revision) || 0);
  const reconstructedTable = block.segment_handling === "table_reconstruction";
  if (block.segment_handling === "manual_insertion" && revision === 0) {
    return "Manual insertion required";
  }
  if (reconstructedTable && revision === 0) {
    return "Machine-reconstructed table";
  }
  if (revision === 0) {
    return "Machine translation";
  }
  const changed = asText(block.effective_text) !== asText(block.machine_text);
  if (reconstructedTable) {
    return changed
      ? `Machine-reconstructed table · manually edited · revision ${revision}`
      : `Machine-reconstructed table · reviewed unchanged · revision ${revision}`;
  }
  return changed ? `Manually edited · revision ${revision}` : `Reviewed unchanged · revision ${revision}`;
}

function updateBlockStatus(blockElement, block) {
  const statusElement = blockElement.querySelector(".status");
  if (!statusElement) {
    return;
  }
  const status = asText(block.review_status, "unreviewed");
  statusElement.textContent = humanize(status);
  statusElement.className = `status ${reviewStatusClass(status)}`.trim();
}

function makeTranslationBlock(block, page, draftText) {
  const article = createElement("article", "translation-block");
  article.classList.add("page-sync-anchor");
  article.dataset.blockId = asText(block.block_id);
  article.dataset.pageNumber = asText(page.original_page_number);
  article.dataset.baseRevision = asText(block.base_revision, "0");
  const manualInsertion = block.segment_handling === "manual_insertion";
  article.classList.toggle("manual-insertion-block", manualInsertion);
  article.classList.toggle(
    "continued-paragraph-block",
    Boolean(block.continues_from_block_id),
  );

  const meta = createElement("div", "block-meta");
  meta.append(createElement("span", "", humanize(block.type || "text")));
  const provenance = createElement(
    "span",
    Number(block.base_revision) > 0 ? "provenance edited" : "provenance machine",
    provenanceLabel(block),
  );
  meta.append(provenance);
  if (block.continuation) {
    meta.append(createElement("span", "continuation", humanize(block.continuation)));
  }
  if (block.paragraph_continuation) {
    const paragraphLabel = block.continues_from_block_id
      ? `Linked paragraph · ${humanize(block.paragraph_continuation)}`
      : humanize(block.paragraph_continuation);
    meta.append(createElement("span", "paragraph-continuation", paragraphLabel));
  }
  if (block.classification_review_required === true) {
    meta.append(createElement("span", "classification-warning", "Check classification"));
  }
  if (block.footnote_owner_review_required === true) {
    meta.append(createElement("span", "classification-warning", "Choose footnote owner"));
  }
  if (block.footnote_id?.id) {
    const printedReference = block.footnote_id.text
      ? ` · printed reference ${block.footnote_id.text}`
      : " · no visible printed reference";
    meta.append(
      createElement("span", "footnote-identity", `Footnote ${block.footnote_id.id}${printedReference}`),
    );
  }
  if (block.footnote_continues_from_block_id) {
    meta.append(
      createElement(
        "span",
        "footnote-continuation",
        `Continues ${block.footnote_continues_from_block_id}`,
      ),
    );
  }
  const ownedFootnotes = state.reviewPages
    .flatMap((candidatePage) => candidatePage.blocks || [])
    .filter((candidate) => candidate.footnote_owner_block_id === block.block_id);
  if (ownedFootnotes.length) {
    const ownedFootnoteCount = new Set(
      ownedFootnotes.map((candidate) => candidate.footnote_id?.id || candidate.block_id),
    ).size;
    meta.append(
      createElement(
        "span",
        "footnote-owner-badge",
        `Owns ${ownedFootnoteCount} ${ownedFootnoteCount === 1 ? "footnote" : "footnotes"}`,
      ),
    );
  }
  const status = createElement(
    "span",
    `status ${reviewStatusClass(asText(block.review_status))}`.trim(),
    humanize(block.review_status || "unreviewed"),
  );
  meta.append(status);

  const sectionControls = createElement("div", "section-controls");
  const typeLabel = createElement("label", "field-label compact-field", "Section type");
  const typeSelect = createElement("select", "section-type-select");
  typeSelect.dataset.testid = "section-type-select";
  typeSelect.dataset.action = "change-section-type";
  const availableTypes = block.segment_handling === "translate"
    ? EDITABLE_BLOCK_TYPES
    : [asText(block.type)];
  for (const type of availableTypes) {
    const option = createElement("option", "", humanize(type));
    option.value = type;
    option.selected = type === asText(block.type);
    typeSelect.append(option);
  }
  typeSelect.disabled = block.segment_handling !== "translate";
  typeLabel.append(typeSelect);

  const ownerLabel = createElement("label", "field-label compact-field footnote-owner-field", "Footnote owner");
  const ownerSelect = createElement("select", "footnote-owner-select");
  ownerSelect.dataset.testid = "footnote-owner-select";
  ownerSelect.dataset.action = "change-footnote-owner";
  const unknownOwner = createElement("option", "", "Unknown — requires review");
  unknownOwner.value = "";
  ownerSelect.append(unknownOwner);
  for (const candidatePage of state.reviewPages) {
    for (const candidate of Array.isArray(candidatePage.blocks) ? candidatePage.blocks : []) {
      if (
        candidate.block_id === block.block_id ||
        candidate.type === "footnote" ||
        candidate.segment_handling !== "translate"
      ) {
        continue;
      }
      const preview = asText(candidate.effective_text, candidate.machine_text)
        .replace(/\s+/g, " ")
        .slice(0, 58);
      const option = createElement(
        "option",
        "",
        `Page ${candidatePage.original_page_number} · ${humanize(candidate.type)} · ${preview}`,
      );
      option.value = asText(candidate.block_id);
      option.selected = option.value === asText(block.footnote_owner_block_id);
      ownerSelect.append(option);
    }
  }
  ownerLabel.append(ownerSelect);
  ownerLabel.hidden = asText(block.type) !== "footnote";
  const selectedOwnerEntry = state.blockIndex.get(asText(block.footnote_owner_block_id));
  const selectedOwnerLength = asText(
    selectedOwnerEntry?.block?.effective_text,
    selectedOwnerEntry?.block?.machine_text,
  ).length;
  const anchorLabel = createElement(
    "label",
    "field-label compact-field footnote-anchor-field",
    "Marker after character",
  );
  const anchorInput = createElement("input", "footnote-anchor-input");
  anchorInput.type = "number";
  anchorInput.min = "0";
  anchorInput.max = asText(selectedOwnerLength);
  anchorInput.step = "1";
  anchorInput.value = asText(block.footnote_anchor_offset, selectedOwnerLength);
  anchorInput.disabled = !block.footnote_owner_block_id;
  anchorInput.dataset.testid = "footnote-anchor-input";
  anchorInput.dataset.action = "change-footnote-anchor";
  anchorLabel.append(anchorInput);
  anchorLabel.hidden = asText(block.type) !== "footnote";
  sectionControls.append(typeLabel, ownerLabel, anchorLabel);
  sectionControls.append(
    createElement(
      "p",
      "footnote-anchor-help",
      "Use 0 for a marker before the first character; the text length places it at the end.",
    ),
  );
  sectionControls.querySelector(".footnote-anchor-help").hidden =
    asText(block.type) !== "footnote";

  if (block.footnote_description) {
    const description = createElement("details", "footnote-description");
    description.append(createElement("summary", "", "Model footnote assessment"));
    description.append(
      createElement("p", "", `Appearance: ${asText(block.footnote_description.appearance)}`),
      createElement("p", "", `Handling: ${asText(block.footnote_description.handling)}`),
    );
    sectionControls.append(description);
  }

  const editor = createElement("div", "translated-editor");
  editor.dataset.blockId = asText(block.block_id);
  editor.dataset.pageNumber = asText(page.original_page_number);
  editor.dataset.testid = "translated-block";
  editor.contentEditable = "true";
  editor.spellcheck = true;
  editor.setAttribute("role", "textbox");
  editor.setAttribute("aria-multiline", "true");
  editor.setAttribute(
    "aria-label",
    manualInsertion
      ? `Manual insertion for physical page ${asText(page.original_page_number)}, ${humanize(
          block.type || "material",
        )}`
      : `Translation for physical page ${asText(page.original_page_number)}, ${humanize(
          block.type || "text",
        )}`,
  );
  if (manualInsertion) {
    editor.classList.add("manual-insertion-editor");
    editor.dataset.placeholder = `Insert the ${humanize(
      block.manual_insertion_reason || block.type || "material",
    ).toLocaleLowerCase()} manually from the page image.`;
  }
  const effectiveText = asText(block.effective_text, asText(block.machine_text));
  const displayedText = draftText === undefined ? effectiveText : draftText;
  const handled = renderHighlightedText(editor, displayedText, block);

  const fallbackContainer = createElement("div", "uncertainty-fallbacks");
  for (const uncertainty of unresolvedUncertainties(block)) {
    const uncertaintyId = asText(uncertainty.uncertainty_id);
    if (handled.has(uncertaintyId)) {
      continue;
    }
    const fallback = createElement(
      "button",
      "uncertainty-fallback",
      `Review: ${asText(uncertainty.source_term, "uncertain passage")}`,
    );
    fallback.type = "button";
    fallback.dataset.testid = "uncertainty-highlight";
    fallback.dataset.action = "review-uncertainty";
    fallback.dataset.uncertaintyId = uncertaintyId;
    fallbackContainer.append(fallback);
  }

  const actions = createElement("div", "block-actions");
  const save = createElement(
    "button",
    "block-action save-action",
    manualInsertion ? "Save insertion" : "Save",
  );
  save.type = "button";
  save.dataset.testid = "save-block";
  save.dataset.action = "save-block";
  save.dataset.reviewStatus = "in_review";
  const validate = createElement("button", "block-action validate-action", "Validate");
  validate.type = "button";
  validate.dataset.testid = "validate-block";
  validate.dataset.action = "save-block";
  validate.dataset.reviewStatus = "accepted";
  const message = createElement("span", "block-message");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  actions.append(save, validate, message);

  article.append(meta, sectionControls, editor);
  if (
    Number(block.base_revision) > 0 &&
    asText(block.machine_text) &&
    asText(block.effective_text) !== asText(block.machine_text)
  ) {
    const machineDetails = createElement("details", "machine-text-details");
    machineDetails.append(
      createElement(
        "summary",
        "",
        block.segment_handling === "table_reconstruction"
          ? "Show original machine reconstruction"
          : "Show original machine translation",
      ),
      createElement("p", "", asText(block.machine_text)),
    );
    article.append(machineDetails);
  }
  if (fallbackContainer.childElementCount) {
    article.append(fallbackContainer);
  }
  article.append(actions);
  if (displayedText !== effectiveText) {
    article.classList.add("is-dirty");
  }
  return article;
}

function paragraphGroupEntries(group) {
  return group.fragment_block_ids
    .map((blockId) => state.blockIndex.get(asText(blockId)))
    .filter(Boolean);
}

function paragraphReviewStatus(entries) {
  const statuses = entries.map(({ block }) => asText(block.review_status, "unreviewed"));
  if (statuses.every((status) => status === "accepted")) {
    return "accepted";
  }
  if (statuses.some((status) => status === "needs_work")) {
    return "needs_work";
  }
  return statuses.some((status) => status !== "unreviewed") ? "in_review" : "unreviewed";
}

function makeParagraphGroup(group) {
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
    const draftText = state.reviewDrafts.get(asText(block.block_id));
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

function captureDrafts() {
  for (const editor of translationContent.querySelectorAll(".translated-editor")) {
    const blockId = asText(editor.dataset.blockId);
    const entry = state.blockIndex.get(blockId);
    if (!entry) {
      continue;
    }
    const editorialText = editorPlainText(editor);
    if (editorialText !== asText(entry.block.effective_text, entry.block.machine_text)) {
      state.reviewDrafts.set(blockId, editorialText);
    } else {
      state.reviewDrafts.delete(blockId);
    }
  }
  return new Map(state.reviewDrafts);
}

function buildReviewIndexes(pages) {
  state.blockIndex = new Map();
  state.uncertaintyIndex = new Map();
  state.uncertaintyGroups = [];
  state.footnoteEntrypointsByOwner = new Map();
  state.paragraphGroups = [];
  state.paragraphGroupByFragment = new Map();
  for (const page of pages) {
    for (const block of Array.isArray(page.blocks) ? page.blocks : []) {
      block.base_revision = Math.max(0, Number(block.base_revision) || 0);
      block.effective_text = asText(block.effective_text, asText(block.machine_text));
      block.review_status = asText(block.review_status, "unreviewed");
      block.uncertainties = Array.isArray(block.uncertainties) ? block.uncertainties : [];
      const entry = { block, page };
      state.blockIndex.set(asText(block.block_id), entry);
      block.uncertainties.forEach((uncertainty, index) => {
        const id = asText(uncertainty.uncertainty_id, `${block.block_id}-u${index + 1}`);
        uncertainty.uncertainty_id = id;
        state.uncertaintyIndex.set(id, { ...entry, uncertainty });
      });
    }
  }
  const identitiesByOwner = new Map();
  for (const { block } of state.blockIndex.values()) {
    const ownerId = asText(block.footnote_owner_block_id);
    if (block.type !== "footnote" || !ownerId) {
      continue;
    }
    const identity = asText(block.footnote_id?.id, block.block_id);
    const seen = identitiesByOwner.get(ownerId) || new Set();
    if (seen.has(identity)) {
      continue;
    }
    const offset = Number(block.footnote_anchor_offset);
    if (!Number.isInteger(offset) || offset < 0) {
      continue;
    }
    seen.add(identity);
    identitiesByOwner.set(ownerId, seen);
    const entrypoints = state.footnoteEntrypointsByOwner.get(ownerId) || [];
    entrypoints.push({
      identity,
      offset,
      text: asText(block.footnote_id?.text, "†"),
    });
    state.footnoteEntrypointsByOwner.set(ownerId, entrypoints);
  }
  for (const entrypoints of state.footnoteEntrypointsByOwner.values()) {
    entrypoints.sort((left, right) => left.offset - right.offset);
  }
  const paragraphGroups = Array.isArray(state.review?.paragraph_groups)
    ? state.review.paragraph_groups
    : [];
  for (const group of paragraphGroups) {
    const fragmentIds = Array.isArray(group.fragment_block_ids)
      ? group.fragment_block_ids.map((value) => asText(value))
      : [];
    if (
      fragmentIds.length < 2 ||
      fragmentIds[0] !== asText(group.paragraph_id) ||
      fragmentIds.some((blockId) => !state.blockIndex.has(blockId))
    ) {
      continue;
    }
    const normalized = {
      paragraph_id: asText(group.paragraph_id),
      fragment_block_ids: fragmentIds,
      original_page_numbers: Array.isArray(group.original_page_numbers)
        ? group.original_page_numbers.map(Number)
        : [],
    };
    state.paragraphGroups.push(normalized);
    for (const blockId of fragmentIds) {
      state.paragraphGroupByFragment.set(blockId, normalized);
    }
  }
}

function renderUncertaintyGroupList(groups) {
  uncertaintyGroupList.replaceChildren();
  uncertaintyGroupEmpty.hidden = groups.length > 0;
  for (const group of groups) {
    const item = createElement("article", "uncertainty-group-item");
    item.setAttribute("role", "listitem");
    const heading = createElement("div", "uncertainty-group-heading");
    heading.append(
      createElement("h3", "", asText(group.source_term, "Uncertain passage")),
      createElement(
        "span",
        "uncertainty-count",
        `${Number(group.occurrence_count) || 1} ${
          Number(group.occurrence_count) === 1 ? "occurrence" : "occurrences"
        }`,
      ),
    );
    const details = [];
    if (group.proposed_translation) {
      details.push(`Model: ${asText(group.proposed_translation)}`);
    }
    const pages = Array.isArray(group.page_numbers)
      ? group.page_numbers.map(Number).filter(Number.isInteger)
      : [];
    if (pages.length) {
      details.push(`Physical ${pages.length === 1 ? "page" : "pages"} ${pages.join(", ")}`);
    }
    const open = createElement(
      "button",
      "text-button uncertainty-group-open",
      "Review first occurrence",
    );
    open.type = "button";
    open.dataset.action = "open-uncertainty-group";
    open.dataset.uncertaintyId = asText(group.first_uncertainty_id);
    item.append(heading);
    if (details.length) {
      item.append(createElement("p", "uncertainty-group-details", details.join(" · ")));
    }
    item.append(createElement("p", "uncertainty-group-reason", asText(group.reason)), open);
    uncertaintyGroupList.append(item);
  }
}

function openUncertaintyList() {
  if (!state.uncertaintyGroups.length) {
    return;
  }
  uncertaintyListDialog.showModal();
  requestAnimationFrame(() => {
    uncertaintyGroupList.querySelector("[data-action='open-uncertainty-group']")?.focus();
  });
}

function handleUncertaintyGroupClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest("[data-action='open-uncertainty-group']");
  if (!button || !uncertaintyGroupList.contains(button)) {
    return;
  }
  const uncertaintyId = asText(button.dataset.uncertaintyId);
  const entry = state.uncertaintyIndex.get(uncertaintyId);
  if (!entry) {
    showGlobalError("This uncertainty is no longer available. Refresh the review.");
    return;
  }
  uncertaintyListDialog.close();
  const matchingEditor = [...translationContent.querySelectorAll(".translated-editor")].find(
    (element) => element.dataset.blockId === asText(entry.block.block_id),
  );
  const blockElement = matchingEditor?.closest(".translation-block");
  if (blockElement) {
    translationScroll.scrollTop = Math.max(
      0,
      elementPositionInScroller(blockElement, translationScroll) - 72,
    );
    syncSourceToTranslation();
    activateSourcePageNumber(Number(entry.page.original_page_number));
  }
  requestAnimationFrame(() => openUncertainty(uncertaintyId));
}

function updateReviewSummary() {
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

function renderedPageElement(container, pageNumber) {
  return [...container.querySelectorAll(".review-page")].find(
    (page) => Number(page.dataset.pageNumber) === Number(pageNumber),
  );
}

function renderAllReviewPages(options = {}) {
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

function renderReview(drafts = new Map(), options = {}) {
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
    asText(state.selectedFile?.name, "Translated PDF");
  const stableRunId = asText(state.review?.translation_run_id);
  if (/^[0-9a-f]{32}$/.test(stableRunId)) {
    state.jobId = stableRunId;
    window.history.replaceState({}, "", `/?job=${encodeURIComponent(stableRunId)}`);
  }
  reviewLibrary.hidden = true;
  reviewEditor.hidden = false;
  reviewDocument.textContent = filename;
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

function currentReviewVersion(response, oldVersion) {
  const candidates = [
    response?.current_revision,
    response?.revision,
    response?.version,
    response?.base_revision,
  ];
  for (const candidate of candidates) {
    const value = Number(candidate);
    if (Number.isInteger(value) && value > oldVersion) {
      return value;
    }
  }
  return oldVersion + 1;
}

async function saveBlock(block, blockElement, editor, status, buttons, message) {
  const editorialText = editorPlainText(editor).trim();
  if (!editorialText) {
    editor.setAttribute("aria-invalid", "true");
    message.textContent = "Translation cannot be blank.";
    editor.focus();
    return;
  }

  for (const button of buttons) {
    button.disabled = true;
  }
  blockElement.classList.add("is-saving");
  message.textContent = status === "accepted" ? "Validating…" : "Saving…";
  const oldVersion = Number(block.base_revision) || 0;
  const drafts = captureDrafts();
  drafts.delete(asText(block.block_id));
  state.reviewDrafts.delete(asText(block.block_id));
  const pageNumber = Number(blockElement.dataset.pageNumber);
  const anchorPage = renderedPageElement(translationContent, pageNumber);
  const anchorViewportOffset = anchorPage
    ? anchorPage.getBoundingClientRect().top -
      translationScroll.getBoundingClientRect().top
    : null;
  try {
    const selectedType = asText(
      blockElement.querySelector(".section-type-select")?.value,
      block.type,
    );
    const selectedOwner = blockElement.querySelector(".footnote-owner-select")?.value || null;
    const anchorControl = blockElement.querySelector(".footnote-anchor-input");
    const selectedAnchor = anchorControl instanceof HTMLInputElement
      ? Number(anchorControl.value)
      : null;
    const response = await apiRequest(
      `/api/jobs/${encodeURIComponent(state.jobId)}/revisions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_id: block.block_id,
          editorial_text: editorialText,
          type: selectedType,
          footnote_owner_block_id: selectedType === "footnote" ? selectedOwner : null,
          footnote_anchor_offset:
            selectedType === "footnote" && selectedOwner && Number.isInteger(selectedAnchor)
              ? selectedAnchor
              : null,
          expected_base_revision: oldVersion,
          status,
        }),
      },
    );
    if (Array.isArray(response?.pages)) {
      state.review = response;
      renderReview(drafts, {
        centerPageNumber: pageNumber,
        anchorPageNumber: pageNumber,
        anchorViewportOffset,
        focusBlockId: block.block_id,
      });
      requestAnimationFrame(() => {
        const refreshedBlock = [
          ...translationContent.querySelectorAll(".translation-block"),
        ].find((element) => element.dataset.blockId === asText(block.block_id));
        const refreshedMessage = refreshedBlock?.querySelector(".block-message");
        if (refreshedMessage) {
          refreshedMessage.textContent = status === "accepted" ? "Validated" : "Saved";
        }
      });
      return;
    }
    block.effective_text = asText(response?.effective_text, editorialText);
    block.review_status = asText(response?.review_status || response?.status, status);
    block.base_revision = currentReviewVersion(response, oldVersion);
    if (Array.isArray(response?.uncertainties)) {
      block.uncertainties = response.uncertainties;
    }
    blockElement.dataset.baseRevision = asText(block.base_revision);
    editor.replaceChildren();
    renderHighlightedText(editor, block.effective_text, block);
    blockElement.classList.remove("is-dirty");
    editor.setAttribute("aria-invalid", "false");
    updateBlockStatus(blockElement, block);
    updateReviewSummary();
    message.textContent = status === "accepted" ? "Validated" : "Saved";
    window.setTimeout(() => {
      if (message.textContent === "Validated" || message.textContent === "Saved") {
        message.textContent = "";
      }
    }, 2400);
  } catch (error) {
    message.textContent = error.message;
    showGlobalError(error.message);
  } finally {
    for (const button of buttons) {
      button.disabled = false;
    }
    blockElement.classList.remove("is-saving");
  }
}

async function saveParagraphGroup(paragraph, blockElement, status, buttons, message) {
  const editorsByBlockId = new Map(
    [...blockElement.querySelectorAll(".paragraph-fragment-editor")].map((editor) => [
      asText(editor.dataset.blockId),
      editor,
    ]),
  );
  const fragments = [];
  for (const blockId of paragraph.fragment_block_ids) {
    const entry = state.blockIndex.get(asText(blockId));
    const editor = editorsByBlockId.get(asText(blockId));
    if (!entry || !editor) {
      showGlobalError("The combined paragraph no longer matches the review data. Refresh it.");
      return;
    }
    const editorialText = editorPlainText(editor).trim();
    if (!editorialText) {
      editor.setAttribute("aria-invalid", "true");
      message.textContent = "Paragraph fragments cannot be blank.";
      editor.focus();
      return;
    }
    fragments.push({
      block_id: blockId,
      editorial_text: editorialText,
      expected_base_revision: Number(entry.block.base_revision) || 0,
    });
  }

  for (const button of buttons) {
    button.disabled = true;
  }
  blockElement.classList.add("is-saving");
  message.textContent = status === "accepted" ? "Validating paragraph…" : "Saving paragraph…";
  const drafts = new Map(captureDrafts());
  for (const blockId of paragraph.fragment_block_ids) {
    drafts.delete(asText(blockId));
  }
  const pageNumber = Number(blockElement.dataset.pageNumber);
  const anchorPage = renderedPageElement(translationContent, pageNumber);
  const anchorViewportOffset = anchorPage
    ? anchorPage.getBoundingClientRect().top -
      translationScroll.getBoundingClientRect().top
    : null;
  try {
    const response = await apiRequest(
      `/api/jobs/${encodeURIComponent(state.jobId)}/paragraph-revisions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paragraph_id: paragraph.paragraph_id,
          fragments,
          status,
        }),
      },
    );
    if (!Array.isArray(response?.pages)) {
      throw new Error("The server did not return the updated paragraph review.");
    }
    state.review = response;
    renderReview(drafts, {
      centerPageNumber: pageNumber,
      anchorPageNumber: pageNumber,
      anchorViewportOffset,
      focusBlockId: paragraph.paragraph_id,
    });
    requestAnimationFrame(() => {
      const refreshed = translationContent.querySelector(
        `.paragraph-group[data-paragraph-id="${CSS.escape(asText(paragraph.paragraph_id))}"]`,
      );
      const refreshedMessage = refreshed?.querySelector(".block-message");
      if (refreshedMessage) {
        refreshedMessage.textContent = status === "accepted" ? "Paragraph validated" : "Paragraph saved";
      }
    });
  } catch (error) {
    message.textContent = error.message;
    showGlobalError(error.message);
  } finally {
    for (const button of buttons) {
      button.disabled = false;
    }
    blockElement.classList.remove("is-saving");
  }
}

function relatedUncertainties(entry) {
  const termGroupId = asText(entry.uncertainty.term_group_id);
  if (!termGroupId) {
    return [entry];
  }
  return [...state.uncertaintyIndex.values()].filter(
    (candidate) =>
      !candidate.uncertainty.resolved &&
      asText(candidate.uncertainty.term_group_id) === termGroupId,
  );
}

function expectedVersionsFor(entries) {
  const versions = {};
  for (const entry of entries) {
    versions[asText(entry.block.block_id)] = Number(entry.block.base_revision) || 0;
  }
  return versions;
}

function openUncertainty(uncertaintyId) {
  const entry = state.uncertaintyIndex.get(asText(uncertaintyId));
  if (!entry) {
    showGlobalError("This uncertainty is no longer available. Refresh the review.");
    return;
  }
  clearGlobalError();
  state.activeUncertaintyId = asText(uncertaintyId);
  const uncertainty = entry.uncertainty;
  document.querySelector("#uncertainty-source").textContent = asText(
    uncertainty.source_term,
    "Not supplied",
  );
  document.querySelector("#uncertainty-proposed").textContent = asText(
    uncertainty.proposed_translation,
    "No single suggestion",
  );
  document.querySelector("#uncertainty-reason").textContent = asText(
    uncertainty.reason,
    "The model marked this passage for human review.",
  );
  const alternatives = Array.isArray(uncertainty.alternatives)
    ? uncertainty.alternatives.map(asText).filter(Boolean)
    : [];
  document.querySelector("#alternatives-row").hidden = alternatives.length === 0;
  document.querySelector("#uncertainty-alternatives").textContent = alternatives.join(" · ");
  replacementInput.value = asText(
    uncertainty.proposed_translation,
    uncertaintyNeedle(uncertainty),
  );
  setInlineError(replacementError, "");

  const isFallback = uncertainty.highlight_mode === "block";
  replacementField.hidden = isFallback;
  fallbackInstruction.hidden = !isFallback;
  translateOneButton.hidden = isFallback;
  const related = relatedUncertainties(entry);
  const occurrenceCount = Math.max(
    related.length,
    Number(uncertainty.matching_occurrence_count) || 0,
  );
  const canReplaceAll =
    uncertainty.can_replace_all === true && occurrenceCount > 1;
  translateAllButton.hidden = isFallback || !canReplaceAll;
  translateAllButton.textContent = `Translate All (${occurrenceCount})`;
  translateOneButton.disabled = false;
  translateAllButton.disabled = false;
  uncertaintyDialog.showModal();
  requestAnimationFrame(() => {
    if (isFallback) {
      closeUncertaintyButton.focus();
    } else {
      replacementInput.focus();
      replacementInput.select();
    }
  });
}

function closeUncertainty() {
  state.activeUncertaintyId = null;
  if (uncertaintyDialog.open) {
    uncertaintyDialog.close();
  }
}

async function replaceUncertainty(scope) {
  const entry = state.uncertaintyIndex.get(asText(state.activeUncertaintyId));
  if (!entry) {
    setInlineError(replacementError, "This uncertainty is no longer available.");
    return;
  }
  if (entry.uncertainty.highlight_mode === "block") {
    setInlineError(
      replacementError,
      "Edit this block manually because an exact replacement range is unavailable.",
    );
    return;
  }
  const replacement = replacementInput.value.trim();
  if (!replacement) {
    replacementInput.setAttribute("aria-invalid", "true");
    setInlineError(replacementError, "Enter the translation that should replace this term.");
    replacementInput.focus();
    return;
  }

  replacementInput.removeAttribute("aria-invalid");
  setInlineError(replacementError, "");
  const affectedEntries = scope === "all" ? relatedUncertainties(entry) : [entry];
  const drafts = captureDrafts();
  for (const affected of affectedEntries) {
    drafts.delete(asText(affected.block.block_id));
  }
  const pageNumber = Number(entry.page.original_page_number);
  const anchorPage = renderedPageElement(translationContent, pageNumber);
  const anchorViewportOffset = anchorPage
    ? anchorPage.getBoundingClientRect().top -
      translationScroll.getBoundingClientRect().top
    : null;
  translateOneButton.disabled = true;
  translateAllButton.disabled = true;
  try {
    await apiRequest(
      `/api/jobs/${encodeURIComponent(state.jobId)}/uncertainties/${encodeURIComponent(
        entry.uncertainty.uncertainty_id,
      )}/replace`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          replacement,
          scope,
          expected_versions: expectedVersionsFor(affectedEntries),
        }),
      },
    );
    closeUncertainty();
    await loadReview({
      drafts,
      centerPageNumber: pageNumber,
      anchorPageNumber: pageNumber,
      anchorViewportOffset,
      focusBlockId: entry.block.block_id,
    });
  } catch (error) {
    setInlineError(replacementError, error.message);
    showGlobalError(error.message);
  } finally {
    translateOneButton.disabled = false;
    translateAllButton.disabled = false;
  }
}

async function loadReview(options = {}) {
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

function formatReviewDate(value) {
  const date = new Date(asText(value));
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function exportUrl(jobId, format) {
  return `/backend/api/jobs/${encodeURIComponent(jobId)}/export.${format}`;
}

function configureExportLinks(jobId, links) {
  for (const [format, link] of Object.entries(links)) {
    if (link) {
      link.href = jobId ? exportUrl(jobId, format) : "#";
    }
  }
}

function makeExportMenu(jobId) {
  const menu = createElement("details", "export-menu article-export-menu");
  const summary = createElement("summary", "secondary-button compact-control", "Export");
  const options = createElement("div", "export-menu-options");
  options.setAttribute("aria-label", "Export article");
  const formats = [
    ["pdf", "LaTeX PDF (.pdf)"],
    ["tex", "LaTeX source (.tex)"],
    ["md", "Markdown (.md)"],
    ["txt", "Plain text (.txt)"],
  ];
  for (const [format, label] of formats) {
    const link = createElement("a", "", label);
    link.href = exportUrl(jobId, format);
    link.download = "";
    options.append(link);
  }
  menu.append(summary, options);
  return menu;
}

function renderTranslationLibrary(payload) {
  const reviews = Array.isArray(payload) ? payload : payload?.jobs || payload?.translations || [];
  reviewList.replaceChildren();
  reviewListEmpty.hidden = reviews.length > 0;
  for (const review of reviews) {
    const jobId = asText(review.job_id || review.translation_run_id);
    if (!jobId) {
      continue;
    }
    const pageCount = Math.max(1, Number(review.page_count) || 1);
    const continuePage = Math.min(
      pageCount,
      Math.max(1, Number(review.continue_page) || 1),
    );
    const acceptedBlocks = Math.max(0, Number(review.accepted_blocks) || 0);
    const totalBlocks = Math.max(0, Number(review.total_blocks) || 0);
    const reviewComplete = review.review_complete === true;
    const card = createElement("article", "review-list-card");
    card.setAttribute("role", "listitem");
    const summary = createElement("div");
    summary.append(createElement("h2", "", asText(review.filename, "Translated PDF")));
    const details = [`${pageCount} ${pageCount === 1 ? "page" : "pages"}`];
    const updated = formatReviewDate(review.updated_at);
    if (updated) {
      details.push(`Updated ${updated}`);
    }
    details.push(
      reviewComplete
        ? "Review complete"
        : totalBlocks > 0
          ? `${acceptedBlocks} of ${totalBlocks} blocks reviewed`
          : "Review not started",
    );
    summary.append(createElement("p", "", details.join(" · ")));
    const open = createElement(
      "button",
      "primary-button compact-control",
      reviewComplete
        ? "Read"
        : continuePage > 1
          ? `Continue review · page ${continuePage}`
          : "Review",
    );
    open.type = "button";
    open.dataset.action = "open-review";
    open.dataset.jobId = jobId;
    const actions = createElement("div", "review-list-actions");
    const remove = createElement("button", "text-button danger-button", "Delete");
    remove.type = "button";
    remove.dataset.action = "delete-review";
    remove.dataset.jobId = jobId;
    remove.dataset.filename = asText(review.filename, "this article");
    actions.append(open, makeExportMenu(jobId), remove);
    card.append(summary, actions);
    reviewList.append(card);
  }
}

async function loadTranslationLibrary({ activate = false } = {}) {
  try {
    renderTranslationLibrary(await apiRequest("/api/jobs"));
  } catch (error) {
    renderTranslationLibrary([]);
    showGlobalError(error.message);
  }
  if (activate) {
    reviewEditor.hidden = true;
    reviewLibrary.hidden = false;
    reviewDocument.textContent = "";
    activateTab("review");
  }
}

async function openLibraryReview(jobId, button) {
  clearGlobalError();
  if (button) {
    button.disabled = true;
  }
  try {
    state.jobId = jobId;
    state.job = await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`);
    state.lastPersistedPage = null;
    window.history.replaceState({}, "", `/?job=${encodeURIComponent(jobId)}`);
    await loadReview();
  } catch (error) {
    showGlobalError(error.message);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

function handleReviewListClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest("[data-action]");
  if (!button || !reviewList.contains(button)) {
    return;
  }
  if (button.dataset.action === "open-review") {
    void openLibraryReview(asText(button.dataset.jobId), button);
    return;
  }
  if (button.dataset.action === "delete-review") {
    void deleteLibraryReview(button);
  }
}

async function deleteLibraryReview(button) {
  const jobId = asText(button.dataset.jobId);
  const filename = asText(button.dataset.filename, "this article");
  if (!jobId || !window.confirm(`Delete ${filename} and all of its review edits?`)) {
    return;
  }
  clearGlobalError();
  button.disabled = true;
  try {
    await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    await loadTranslationLibrary();
  } catch (error) {
    button.disabled = false;
    showGlobalError(error.message);
  }
}

function elementPositionInScroller(element, scroller) {
  const elementRect = element.getBoundingClientRect();
  const scrollerRect = scroller.getBoundingClientRect();
  return elementRect.top - scrollerRect.top + scroller.scrollTop;
}

function persistReviewPosition(pageNumber) {
  if (
    !state.allowPositionPersistence ||
    !Number.isInteger(pageNumber) ||
    state.lastPersistedPage === pageNumber ||
    !state.jobId
  ) {
    return;
  }
  const jobId = state.jobId;
  state.lastPersistedPage = pageNumber;
  state.positionQueue = state.positionQueue
    .catch(() => undefined)
    .then(() =>
      apiRequest(`/api/jobs/${encodeURIComponent(jobId)}/review-position`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ original_page_number: pageNumber }),
      }),
    )
    .catch(() => {
      if (state.jobId === jobId && state.lastPersistedPage === pageNumber) {
        state.lastPersistedPage = null;
      }
    });
}

function syncSourceToTranslation() {
  state.scrollFrame = null;
  const pageAnchors = [
    ...translationContent.querySelectorAll(".page-sync-anchor[data-page-number]"),
  ];
  if (!pageAnchors.length) {
    return;
  }
  const scrollTop = translationScroll.scrollTop;
  const anchor = scrollTop + 76;
  let activePageAnchor = pageAnchors[0];
  for (const pageAnchor of pageAnchors) {
    if (elementPositionInScroller(pageAnchor, translationScroll) <= anchor) {
      activePageAnchor = pageAnchor;
    } else {
      break;
    }
  }
  activateSourcePageNumber(Number(activePageAnchor.dataset.pageNumber));
}

function requestScrollSync() {
  if (state.scrollFrame === null) {
    state.scrollFrame = requestAnimationFrame(syncSourceToTranslation);
  }
}


function activateTab(name) {
  emitEvent('transcribl-tab', name === 'review' ? 'Articles' : 'Translate');
}
translationContent.addEventListener('click', handleReviewClick);
translationContent.addEventListener('keydown', handleReviewKeydown);
translationContent.addEventListener('input', handleReviewInput);
translationContent.addEventListener('change', handleReviewControlChange);
translationContent.addEventListener('paste', handleReviewPaste);
translationScroll.addEventListener('scroll', requestScrollSync, {passive: true});
reviewPanel.addEventListener('change', handleReviewToolbarChange);
window.addEventListener('resize', requestScrollSync);
dismissAlert.addEventListener('click', clearGlobalError);
reviewList.addEventListener('click', handleReviewListClick);
refreshTranslationsButton.addEventListener('click', () => loadTranslationLibrary({activate: true}));
backToTranslationsButton.addEventListener('click', () => {
  if (state.reviewDrafts.size && !window.confirm('Discard unsaved block edits?')) return;
  state.reviewDrafts = new Map();
  window.history.replaceState({}, '', '/');
  loadTranslationLibrary({activate: true});
});
newTranslationButton.addEventListener('click', () => activateTab('translate'));
closeUncertaintyButton.addEventListener('click', closeUncertainty);
cancelUncertaintyButton.addEventListener('click', closeUncertainty);
uncertaintyListButton.addEventListener('click', openUncertaintyList);
uncertaintyGroupList.addEventListener('click', handleUncertaintyGroupClick);
translateOneButton.addEventListener('click', () => replaceUncertainty('one'));
translateAllButton.addEventListener('click', () => replaceUncertainty('all'));
uncertaintyForm.addEventListener('submit', (event) => {event.preventDefault(); replaceUncertainty('one');});
uncertaintyDialog.addEventListener('cancel', () => {state.activeUncertaintyId = null;});
window.addEventListener('beforeunload', (event) => {
  if (state.reviewDrafts.size || window.transcriblGlossaryDirty) {event.preventDefault(); event.returnValue = '';}
});
window.transcriblEditor = {
  open: openLibraryReview,
  refresh: loadTranslationLibrary,
  async initialize() {
    await fetch('/backend/session', {credentials: 'same-origin'});
    state.config = await apiRequest('/api/config');
    for (const level of state.config.review.zoom_levels) reviewZoomSelect.append(new Option(`${level}%`, String(level)));
    setReviewZoom(state.config.review.zoom_default_percent);
    await loadTranslationLibrary();
  },
};
await window.transcriblEditor.initialize();

})();
