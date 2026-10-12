import { state, translationContent } from "./context.js";
import { notifyDraftsChanged } from "./drafts.js";

const mutationButtons = "[data-action='save-block'], [data-action='save-paragraph']";

export function beginReviewMutation() {
  if (state.reviewMutationPending) return false;
  state.reviewMutationPending = true;
  for (const button of translationContent.querySelectorAll(mutationButtons)) button.disabled = true;
  notifyDraftsChanged();
  return true;
}

export function endReviewMutation() {
  state.reviewMutationPending = false;
  for (const button of translationContent.querySelectorAll(mutationButtons)) button.disabled = false;
  notifyDraftsChanged();
}
