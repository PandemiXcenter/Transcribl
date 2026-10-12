import {
  apiRequest
} from "./api.js";
import {
  closeUncertaintyButton,
  fallbackInstruction,
  replacementError,
  replacementField,
  replacementInput,
  state,
  translateAllButton,
  translateOneButton,
  translationContent,
  translationScroll,
  uncertaintyDialog
} from "./context.js";
import {
  asText,
  clearGlobalError,
  renderedPageElement,
  setInlineError,
  showGlobalError
} from "./dom.js";
import {
  captureDrafts
} from "./drafts.js";
import {
  uncertaintyNeedle
} from "./highlights.js";
import {
  loadReview
} from "./review.js";

export function relatedUncertainties(entry) {
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

export function expectedVersionsFor(entries) {
  const versions = {};
  for (const entry of entries) {
    versions[asText(entry.block.block_id)] = Number(entry.block.base_revision) || 0;
  }
  return versions;
}

export function openUncertainty(uncertaintyId) {
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

export function closeUncertainty() {
  state.activeUncertaintyId = null;
  if (uncertaintyDialog.open) {
    uncertaintyDialog.close();
  }
}

export async function replaceUncertainty(scope) {
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
