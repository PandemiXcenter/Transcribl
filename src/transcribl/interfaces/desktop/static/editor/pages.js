import {
  apiRequest
} from "./api.js";
import {
  activePageLabel,
  fullSizePageLink,
  reviewZoomSelect,
  sourcePageImage,
  reviewEditor,
  sourcePageLabel,
  state,
  translationContent,
  translationScroll
} from "./context.js";
import {
  asText,
  createElement,
  elementPositionInScroller,
  pageDescription,
  renderedPageElement
} from "./dom.js";

import { resizeSourceImage, sourceImageLoading } from "./viewport.js";

export function pageImageUrl(pageNumber) {
  return `/backend/api/jobs/${encodeURIComponent(state.jobId)}/pages/${encodeURIComponent(
    pageNumber,
  )}/image`;
}

export function setReviewZoom(percent) {
  const allowedLevels = Array.isArray(state.config?.review?.zoom_levels)
    ? state.config.review.zoom_levels
    : [];
  const normalized = Number(percent);
  if (!Number.isInteger(normalized) || !allowedLevels.includes(normalized)) {
    return;
  }
  state.reviewZoomPercent = normalized;
  reviewZoomSelect.value = String(normalized);
  resizeSourceImage();
  document.getElementById("zoom-out").disabled = normalized === allowedLevels[0];
  document.getElementById("zoom-in").disabled = normalized === allowedLevels.at(-1);
}

export function showSourcePage(page) {
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
  sourceImageLoading();
  sourcePageImage.src = url;
  fullSizePageLink.href = url;
}

export function activateSourcePageNumber(pageNumber, { persist = true } = {}) {
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
  document.getElementById("review-page-number").value = label;
  document.getElementById("review-page-number").max = String(state.reviewPages.length);
  document.getElementById("review-page-count").textContent = `of ${state.reviewPages.length}`;
  document.getElementById("previous-review-page").disabled = Number(label) <= 1;
  document.getElementById("next-review-page").disabled = Number(label) >= state.reviewPages.length;
  if (persist) {
    persistReviewPosition(Number(pageEntry.original_page_number));
  }
}

export function persistReviewPosition(pageNumber) {
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

export function syncSourceToTranslation() {
  state.scrollFrame = null;
  if (reviewEditor.hidden || !translationScroll.clientHeight) return;
  const pageAnchors = [
    ...translationContent.querySelectorAll(".page-sync-anchor[data-page-number]"),
  ];
  if (!pageAnchors.length) {
    return;
  }
  const scrollTop = translationScroll.scrollTop;
  const scrollEnd = translationScroll.scrollHeight - translationScroll.clientHeight;
  if (scrollEnd > 0 && scrollTop >= scrollEnd - 1) {
    activateSourcePageNumber(state.reviewPages.at(-1).original_page_number);
    return;
  }
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

export function requestScrollSync() {
  if (state.scrollFrame === null) {
    state.scrollFrame = requestAnimationFrame(syncSourceToTranslation);
  }
}

export function reviewPageAnchor(pageNumber) {
  return translationContent.querySelector(`.page-sync-anchor[data-page-number="${Number(pageNumber)}"]`)
    || renderedPageElement(translationContent, pageNumber);
}

export function navigateReviewPage(pageNumber) {
  const number = Number(pageNumber);
  if (!Number.isInteger(number) || number < 1 || number > state.reviewPages.length) {
    document.getElementById("review-page-number").value = String(state.sourcePageNumber || 1);
    return;
  }
  // Prefer the inline physical-page anchor when a paragraph spans pages.
  const anchor = reviewPageAnchor(number);
  if (!anchor) return;
  translationScroll.scrollTop = elementPositionInScroller(anchor, translationScroll);
  activateSourcePageNumber(number);
  translationScroll.focus({ preventScroll: true });
}

export function initializePageNavigation() {
  document.getElementById("previous-review-page").addEventListener("click", () => navigateReviewPage(state.sourcePageNumber - 1));
  document.getElementById("next-review-page").addEventListener("click", () => navigateReviewPage(state.sourcePageNumber + 1));
  document.getElementById("review-page-form").addEventListener("submit", (event) => {
    event.preventDefault();
    navigateReviewPage(document.getElementById("review-page-number").value);
  });
  for (const [id, direction] of [["zoom-out", -1], ["zoom-in", 1]]) {
    document.getElementById(id).addEventListener("click", () => {
      const levels = state.config.review.zoom_levels;
      setReviewZoom(levels[levels.indexOf(state.reviewZoomPercent) + direction]);
    });
  }
  document.getElementById("zoom-fit").addEventListener("click", () => {
    setReviewZoom(100);
    resizeSourceImage({ reset: true });
  });
}
