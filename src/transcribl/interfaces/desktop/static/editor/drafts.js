import { state, translationContent } from "./context.js";
import { asText } from "./dom.js";

// Contenteditable inserts DIV/P/BR elements for Enter. Preserve those line breaks
// while excluding the trusted footnote markers that are only display decoration.
export function editorPlainText(editor) {
  function readChildren(parent) {
    let text = "";
    for (const node of parent.childNodes) {
      if (node.nodeType === 3) {
        text += node.textContent || "";
        continue;
      }
      if (node.nodeType !== 1 || node.dataset.editorDisplayOnly === "true") continue;
      if (node.tagName === "BR") {
        const placeholder = parent.childNodes.length === 1 && /^(DIV|P)$/.test(parent.tagName);
        if (!placeholder) text += "\n";
        continue;
      }
      const isLine = /^(DIV|P|LI)$/.test(node.tagName);
      if (isLine && text && !text.endsWith("\n")) text += "\n";
      text += readChildren(node);
      if (isLine && node.nextSibling) text += "\n";
    }
    return text;
  }
  return readChildren(editor);
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

export function notifyDraftsChanged() {
  document.dispatchEvent(new CustomEvent("transcribl-drafts-changed"));
}

export function effectiveDraft(block) {
  const isFootnote = block.type === "footnote";
  return {
    text: asText(block.effective_text, block.machine_text),
    type: asText(block.type),
    footnoteOwner: isFootnote ? block.footnote_owner_block_id || null : null,
    footnoteAnchor: isFootnote ? block.footnote_anchor_offset ?? null : null,
  };
}

export function editorSnapshot(editor) {
  const blockId = asText(editor.dataset.blockId);
  const block = state.blockIndex.get(blockId)?.block;
  if (!block) return null;
  const container = editor.closest(".translation-block");
  const snapshot = effectiveDraft(block);
  snapshot.text = editorPlainText(editor);
  snapshot.type = container?.querySelector(".section-type-select")?.value || snapshot.type;
  const ownerControl = container?.querySelector(".footnote-owner-select");
  const anchorControl = container?.querySelector(".footnote-anchor-input");
  if (ownerControl) snapshot.footnoteOwner = ownerControl.value || null;
  if (anchorControl) snapshot.footnoteAnchor = anchorControl.value;
  if (snapshot.type !== "footnote" || !snapshot.footnoteOwner) {
    snapshot.footnoteOwner = null;
    snapshot.footnoteAnchor = null;
  }
  return snapshot;
}

export function draftsEqual(left, right) {
  return left?.text === right?.text && left?.type === right?.type &&
    left?.footnoteOwner === right?.footnoteOwner &&
    String(left?.footnoteAnchor ?? "") === String(right?.footnoteAnchor ?? "");
}

export function recordEditorDraft(editor, notify = true) {
  const blockElement = editor.closest(".translation-block");
  const blockId = asText(editor.dataset.blockId);
  const entry = state.blockIndex.get(blockId);
  const snapshot = editorSnapshot(editor);
  if (!blockElement || !entry || !snapshot) return;
  const dirty = !draftsEqual(snapshot, effectiveDraft(entry.block));
  editor.classList.toggle("is-dirty", dirty);
  editor.setAttribute("aria-invalid", "false");
  if (dirty) state.reviewDrafts.set(blockId, snapshot);
  else state.reviewDrafts.delete(blockId);
  blockElement.classList.toggle("is-dirty", Boolean(blockElement.querySelector(".translated-editor.is-dirty")));
  if (notify) notifyDraftsChanged();
}

export function recordBlockDraft(blockElement) {
  for (const editor of blockElement.querySelectorAll(".translated-editor")) {
    recordEditorDraft(editor, false);
  }
  notifyDraftsChanged();
}

export function captureDrafts() {
  for (const editor of translationContent.querySelectorAll(".translated-editor")) {
    recordEditorDraft(editor, false);
  }
  notifyDraftsChanged();
  return new Map(state.reviewDrafts);
}

// Capture AFTER the request. Clear only the exact submitted values; edits made
// during the request remain drafts against the new server revision.
export function draftsAfterSave(submitted) {
  const drafts = captureDrafts();
  for (const editor of translationContent.querySelectorAll(".translated-editor")) {
    const blockId = asText(editor.dataset.blockId);
    if (!submitted.has(blockId)) continue;
    const current = editorSnapshot(editor);
    if (draftsEqual(current, submitted.get(blockId))) drafts.delete(blockId);
    else if (current) drafts.set(blockId, current);
  }
  return drafts;
}

// Selection offsets stay in DOM UTF-16 units, independently of canonical
// code-point footnote offsets. Rerendering produces plain text and inline marks.
export function captureEditorSelection() {
  const selection = window.getSelection();
  const editor = document.activeElement?.closest(".translated-editor");
  if (!editor || !selection?.rangeCount || !editor.contains(selection.anchorNode) ||
      !editor.contains(selection.focusNode)) return null;
  function offsetTo(node, offset) {
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.setEnd(node, offset);
    const prefix = document.createElement("div");
    prefix.append(range.cloneContents());
    return editorPlainText(prefix).length;
  }
  return {
    blockId: asText(editor.dataset.blockId),
    anchorOffset: offsetTo(selection.anchorNode, selection.anchorOffset),
    focusOffset: offsetTo(selection.focusNode, selection.focusOffset),
  };
}

export function restoreEditorSelection(snapshot) {
  if (!snapshot) return false;
  const editor = [...translationContent.querySelectorAll(".translated-editor")]
    .find((candidate) => candidate.dataset.blockId === snapshot.blockId);
  const selection = window.getSelection();
  if (!editor || !selection) return false;
  function positionAt(offset) {
    let remaining = Math.max(0, offset);
    let last = null;
    function visit(parent) {
      for (const node of parent.childNodes) {
        if (node.nodeType === 3) {
          last = node;
          if (remaining <= node.textContent.length) return [node, remaining];
          remaining -= node.textContent.length;
        } else if (node.nodeType === 1 && node.dataset.editorDisplayOnly !== "true") {
          const position = visit(node);
          if (position) return position;
        }
      }
      return null;
    }
    return visit(editor) || (last ? [last, last.textContent.length] : [editor, 0]);
  }
  const [anchorNode, anchorOffset] = positionAt(snapshot.anchorOffset);
  const [focusNode, focusOffset] = positionAt(snapshot.focusOffset);
  editor.focus({ preventScroll: true });
  selection.setBaseAndExtent(anchorNode, anchorOffset, focusNode, focusOffset);
  return true;
}
