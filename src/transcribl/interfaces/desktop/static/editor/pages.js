import {
  apiRequest
} from "./api.js";
import {
  activePageLabel,
  fullSizePageLink,
  reviewZoomSelect,
  sourcePageImage,
  sourcePageLabel,
  state,
  translationContent,
  translationScroll
} from "./context.js";
import {
  asText,
  createElement,
  elementPositionInScroller,
  pageDescription
} from "./dom.js";

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
  sourcePageImage.style.setProperty("--review-page-zoom", String(normalized / 100));
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
  const pageAnchors = [
    ...translationContent.querySelectorAll(".page-sync-anchor[data-page-number]"),
  ];
  if (!pageAnchors.length) {
    return;
  }
  const scrollTop = translationScroll.scrollTop;
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
