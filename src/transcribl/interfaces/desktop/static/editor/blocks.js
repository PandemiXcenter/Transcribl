import {
  EDITABLE_BLOCK_TYPES,
  state
} from "./context.js";
import {
  asText,
  createElement,
  humanize,
  reviewStatusClass
} from "./dom.js";
import { effectiveDraft, draftsEqual } from "./drafts.js";
import {
  renderHighlightedText,
  unresolvedUncertainties
} from "./highlights.js";

export function provenanceLabel(block) {
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

export function updateBlockStatus(blockElement, block) {
  const statusElement = blockElement.querySelector(".status");
  if (!statusElement) {
    return;
  }
  const status = asText(block.review_status, "unreviewed");
  statusElement.textContent = humanize(status);
  statusElement.className = `status ${reviewStatusClass(status)}`.trim();
}

export function makeTranslationBlock(block, page, draft) {
  const values = draft || effectiveDraft(block);
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
    option.selected = type === values.type;
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
      option.selected = option.value === asText(values.footnoteOwner);
      ownerSelect.append(option);
    }
  }
  ownerLabel.append(ownerSelect);
  ownerLabel.hidden = values.type !== "footnote";
  const selectedOwnerEntry = state.blockIndex.get(asText(values.footnoteOwner));
  const selectedOwnerLength = Array.from(asText(
    selectedOwnerEntry?.block?.effective_text,
    selectedOwnerEntry?.block?.machine_text,
  )).length;
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
  anchorInput.value = asText(values.footnoteAnchor, selectedOwnerLength);
  anchorInput.disabled = !values.footnoteOwner;
  anchorInput.dataset.testid = "footnote-anchor-input";
  anchorInput.dataset.action = "change-footnote-anchor";
  anchorLabel.append(anchorInput);
  anchorLabel.hidden = values.type !== "footnote";
  sectionControls.append(typeLabel, ownerLabel, anchorLabel);
  sectionControls.append(
    createElement(
      "p",
      "footnote-anchor-help",
      "Use 0 for a marker before the first character; the text length places it at the end.",
    ),
  );
  sectionControls.querySelector(".footnote-anchor-help").hidden =
    values.type !== "footnote";

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
  const displayedText = values.text;
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
  if (!draftsEqual(values, effectiveDraft(block))) {
    editor.classList.add("is-dirty");
    article.classList.add("is-dirty");
  }
  return article;
}
