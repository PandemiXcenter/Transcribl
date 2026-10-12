import { apiRequest } from "./api.js";
import { state, translationContent, translationScroll } from "./context.js";
import { asText, renderedPageElement, showGlobalError } from "./dom.js";
import { captureDrafts, captureEditorSelection, draftsAfterSave, editorSnapshot } from "./drafts.js";
import { beginReviewMutation, endReviewMutation } from "./mutations.js";
import { renderReview } from "./review.js";

function reviewAnchor(blockElement) {
  const pageNumber = Number(blockElement.dataset.pageNumber);
  const anchorPage = renderedPageElement(translationContent, pageNumber);
  return {
    centerPageNumber: pageNumber,
    anchorPageNumber: pageNumber,
    anchorViewportOffset: anchorPage
      ? anchorPage.getBoundingClientRect().top - translationScroll.getBoundingClientRect().top
      : null,
  };
}

function applySavedReview(response, submitted, blockElement, focusBlockId, successMessage) {
  if (!Array.isArray(response?.pages)) {
    throw new Error("The server did not return the updated review. Your edits are retained.");
  }
  const selection = captureEditorSelection();
  const drafts = draftsAfterSave(submitted);
  const activeEditor = document.activeElement?.closest(".translated-editor");
  const focus = activeEditor?.dataset.blockId || focusBlockId;
  const anchor = reviewAnchor(blockElement);
  // Mutation responses contain the effective projection; retain the display-only
  // cost and resume metadata supplied by the initial review request.
  state.review = { ...state.review, ...response };
  renderReview(drafts, { ...anchor, focusBlockId: focus, selection });
  requestAnimationFrame(() => {
    const refreshed = [...translationContent.querySelectorAll(".translation-block")]
      .find((element) => element.dataset.blockId === asText(focusBlockId));
    const message = refreshed?.querySelector(".block-message");
    if (message) message.textContent = drafts.has(asText(focusBlockId))
      ? `${successMessage}. Newer edits are unsaved.` : successMessage;
  });
}

export async function saveBlock(block, blockElement, editor, status, buttons, message) {
  const snapshot = editorSnapshot(editor);
  if (!snapshot || !snapshot.text.trim()) {
    editor.setAttribute("aria-invalid", "true");
    message.textContent = "Translation cannot be blank.";
    editor.focus();
    return;
  }
  if (!beginReviewMutation()) return;
  const jobId = state.jobId;
  captureDrafts();
  const submitted = new Map([[asText(block.block_id), snapshot]]);
  blockElement.classList.add("is-saving");
  message.textContent = status === "accepted" ? "Validating…" : "Saving…";
  try {
    const offset = snapshot.footnoteAnchor === null ? null : Number(snapshot.footnoteAnchor);
    const response = await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}/revisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        block_id: block.block_id,
        editorial_text: snapshot.text,
        type: snapshot.type,
        footnote_owner_block_id: snapshot.footnoteOwner,
        footnote_anchor_offset: Number.isInteger(offset) ? offset : null,
        expected_base_revision: Number(block.base_revision) || 0,
        status,
      }),
    });
    if (state.jobId !== jobId) return;
    applySavedReview(response, submitted, blockElement, block.block_id,
      status === "accepted" ? "Validated" : "Saved");
  } catch (error) {
    captureDrafts();
    message.textContent = error.message;
    showGlobalError(error.message);
  } finally {
    blockElement.classList.remove("is-saving");
    endReviewMutation();
  }
}

export async function saveParagraphGroup(paragraph, blockElement, status, buttons, message) {
  const editorsByBlockId = new Map(
    [...blockElement.querySelectorAll(".paragraph-fragment-editor")].map((editor) => [
      asText(editor.dataset.blockId), editor,
    ]),
  );
  const fragments = [];
  const submitted = new Map();
  for (const blockId of paragraph.fragment_block_ids) {
    const entry = state.blockIndex.get(asText(blockId));
    const editor = editorsByBlockId.get(asText(blockId));
    const snapshot = editor && editorSnapshot(editor);
    if (!entry || !editor || !snapshot) {
      showGlobalError("The combined paragraph no longer matches the review data. Refresh it.");
      return;
    }
    if (!snapshot.text.trim()) {
      editor.setAttribute("aria-invalid", "true");
      message.textContent = "Paragraph fragments cannot be blank.";
      editor.focus();
      return;
    }
    submitted.set(asText(blockId), snapshot);
    fragments.push({
      block_id: blockId,
      editorial_text: snapshot.text,
      expected_base_revision: Number(entry.block.base_revision) || 0,
    });
  }
  if (!beginReviewMutation()) return;
  const jobId = state.jobId;
  captureDrafts();
  blockElement.classList.add("is-saving");
  message.textContent = status === "accepted" ? "Validating paragraph…" : "Saving paragraph…";
  try {
    const response = await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}/paragraph-revisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paragraph_id: paragraph.paragraph_id, fragments, status }),
    });
    if (state.jobId !== jobId) return;
    applySavedReview(response, submitted, blockElement, paragraph.paragraph_id,
      status === "accepted" ? "Paragraph validated" : "Paragraph saved");
  } catch (error) {
    captureDrafts();
    message.textContent = error.message;
    showGlobalError(error.message);
  } finally {
    blockElement.classList.remove("is-saving");
    endReviewMutation();
  }
}
