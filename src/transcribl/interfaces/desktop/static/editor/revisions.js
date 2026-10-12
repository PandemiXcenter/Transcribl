import {
  apiRequest
} from "./api.js";
import {
  updateBlockStatus
} from "./blocks.js";
import {
  state,
  translationContent,
  translationScroll
} from "./context.js";
import {
  asText,
  renderedPageElement,
  showGlobalError
} from "./dom.js";
import {
  captureDrafts,
  editorPlainText
} from "./drafts.js";
import {
  renderHighlightedText
} from "./highlights.js";
import {
  renderReview,
  updateReviewSummary
} from "./review.js";

export function currentReviewVersion(response, oldVersion) {
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

export async function saveBlock(block, blockElement, editor, status, buttons, message) {
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

export async function saveParagraphGroup(paragraph, blockElement, status, buttons, message) {
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
