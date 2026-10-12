import {
  apiRequest
} from "./api.js";
import {
  reviewDocument,
  reviewEditor,
  reviewLibrary,
  reviewList,
  reviewListEmpty,
  state
} from "./context.js";
import {
  activateTab,
  asText,
  clearGlobalError,
  createElement,
  showGlobalError
} from "./dom.js";
import {
  costBreakdown,
  makeExportMenu
} from "./exports.js";
import {
  loadReview
} from "./review.js";

export function formatReviewDate(value) {
  const date = new Date(asText(value));
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function renderTranslationLibrary(payload) {
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
    if (review.cost) {
      summary.append(costBreakdown(review.cost));
    }
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

export async function loadTranslationLibrary({ activate = false } = {}) {
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

export async function openLibraryReview(jobId, button) {
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

export function handleReviewListClick(event) {
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

export async function deleteLibraryReview(button) {
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
