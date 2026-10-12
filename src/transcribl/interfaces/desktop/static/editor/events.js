import {
  state,
  translationContent
} from "./context.js";
import {
  asText
} from "./dom.js";
import {
  insertPlainTextAtSelection,
  recordEditorDraft,
  recordBlockDraft
} from "./drafts.js";
import {
  activateSourcePageNumber,
  setReviewZoom
} from "./pages.js";
import {
  saveBlock,
  saveParagraphGroup
} from "./revisions.js";
import {
  openUncertainty
} from "./uncertainties.js";

export function activateUncertaintyFromEvent(event, uncertaintyId) {
  event.preventDefault();
  event.stopPropagation();
  openUncertainty(uncertaintyId);
}

export function handleReviewClick(event) {
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

export function handleReviewKeydown(event) {
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

export function handleReviewInput(event) {
  const target = event.target instanceof Element ? event.target : null;
  const editor = target?.closest(".translated-editor");
  if (editor && translationContent.contains(editor)) {
    recordEditorDraft(editor);
  } else if (target instanceof HTMLInputElement && translationContent.contains(target)) {
    const blockElement = target.closest(".translation-block");
    if (blockElement) recordBlockDraft(blockElement);
  }
}

export function handleReviewControlChange(event) {
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
      const ownerLength = Array.from(asText(
        ownerEntry?.block?.effective_text,
        ownerEntry?.block?.machine_text,
      )).length;
      anchorInput.max = asText(ownerLength);
      anchorInput.value = control.value ? asText(ownerLength) : "0";
      anchorInput.disabled = !control.value;
    }
  }
  recordBlockDraft(blockElement);
}

export function handleReviewPaste(event) {
  const target = event.target instanceof Element ? event.target : null;
  const editor = target?.closest(".translated-editor");
  if (!editor || !translationContent.contains(editor)) {
    return;
  }
  event.preventDefault();
  insertPlainTextAtSelection(editor, event.clipboardData?.getData("text/plain") || "");
  editor.dispatchEvent(new Event("input", { bubbles: true }));
}

export function handleReviewToolbarChange(event) {
  const target = event.target instanceof HTMLSelectElement ? event.target : null;
  if (target?.matches("#review-zoom-select")) {
    setReviewZoom(target.value);
  }
}
