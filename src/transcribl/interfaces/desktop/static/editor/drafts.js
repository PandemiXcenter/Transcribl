import {
  state,
  translationContent
} from "./context.js";
import {
  asText
} from "./dom.js";

export function editorPlainText(editor) {
  const copy = editor.cloneNode(true);
  for (const marker of copy.querySelectorAll("[data-editor-display-only='true']")) {
    marker.remove();
  }
  return copy.textContent || "";
}

export function insertPlainTextAtSelection(editor, text) {
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

export function setBlockDirty(blockElement, editor, effectiveText) {
  const dirty = editorPlainText(editor) !== effectiveText;
  editor.classList.toggle("is-dirty", dirty);
  blockElement.classList.toggle(
    "is-dirty",
    Boolean(blockElement.querySelector(".translated-editor.is-dirty")),
  );
  editor.setAttribute("aria-invalid", "false");
  return dirty;
}

export function recordEditorDraft(editor) {
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

export function captureDrafts() {
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
