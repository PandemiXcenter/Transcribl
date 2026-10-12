// A scrollable view of one physical page; document navigation stays in pages.js.
import {
  reviewEditor,
  sourcePageImage,
  sourceScroll,
  state
} from "./context.js";

export function resizeReviewWorkspace() {
  if (reviewEditor.hidden || !reviewEditor.getClientRects().length) return;
  const top = reviewEditor.getBoundingClientRect().top + window.scrollY;
  const body = reviewEditor.closest(".workbench-body");
  const bottom = Math.max(16, body ? parseFloat(getComputedStyle(body).paddingBottom) : 0);
  reviewEditor.style.height = `${Math.max(360, window.innerHeight - top - bottom)}px`;
}

export function resizeSourceImage({ reset = false } = {}) {
  if (!sourcePageImage.naturalWidth || !sourceScroll.clientWidth || sourcePageImage.hidden) return;
  const content = document.getElementById("source-content");
  const padding = getComputedStyle(content);
  const horizontalPadding = parseFloat(padding.paddingLeft) + parseFloat(padding.paddingRight);
  const verticalPadding = parseFloat(padding.paddingTop) + parseFloat(padding.paddingBottom);
  const previous = sourcePageImage.getBoundingClientRect();
  const viewport = sourceScroll.getBoundingClientRect();
  const centerX = previous.width ? (viewport.left + sourceScroll.clientWidth / 2 - previous.left) / previous.width : 0.5;
  const centerY = previous.height ? (viewport.top + sourceScroll.clientHeight / 2 - previous.top) / previous.height : 0.5;
  // offsetWidth/Height include scrollbar space, keeping fit scale stable as bars appear.
  const fit = Math.min(
    Math.max(1, sourceScroll.offsetWidth - horizontalPadding - 2) / sourcePageImage.naturalWidth,
    Math.max(1, sourceScroll.offsetHeight - verticalPadding - 2) / sourcePageImage.naturalHeight,
  );
  const scale = fit * (state.reviewZoomPercent || 100) / 100;
  sourcePageImage.style.width = `${Math.floor(sourcePageImage.naturalWidth * scale)}px`;
  sourcePageImage.style.height = `${Math.floor(sourcePageImage.naturalHeight * scale)}px`;
  if (reset) {
    sourceScroll.scrollLeft = (sourceScroll.scrollWidth - sourceScroll.clientWidth) / 2;
    sourceScroll.scrollTop = 0;
  } else {
    const updated = sourcePageImage.getBoundingClientRect();
    sourceScroll.scrollLeft += updated.left + centerX * updated.width - viewport.left - sourceScroll.clientWidth / 2;
    sourceScroll.scrollTop += updated.top + centerY * updated.height - viewport.top - sourceScroll.clientHeight / 2;
  }
}

export function sourceImageLoading() {
  sourcePageImage.hidden = true;
  document.getElementById("source-image-status").hidden = false;
  document.getElementById("source-image-message").textContent = "Loading original page…";
  document.getElementById("retry-source-image").hidden = true;
  sourceScroll.setAttribute("aria-busy", "true");
}

export function initializeSourceViewport() {
  sourcePageImage.addEventListener("load", () => {
    sourcePageImage.hidden = false;
    document.getElementById("source-image-status").hidden = true;
    sourceScroll.setAttribute("aria-busy", "false");
    resizeSourceImage({ reset: true });
  });
  sourcePageImage.addEventListener("error", () => {
    sourcePageImage.hidden = true;
    document.getElementById("source-image-status").hidden = false;
    document.getElementById("source-image-message").textContent = "Original page could not be loaded.";
    document.getElementById("retry-source-image").hidden = false;
    sourceScroll.setAttribute("aria-busy", "false");
  });
  document.getElementById("retry-source-image").addEventListener("click", () => {
    // Assigning the identical failed URL does not trigger another load in WebKit.
    const url = new URL(sourcePageImage.src);
    url.searchParams.set("retry", String(Date.now()));
    sourceImageLoading();
    sourcePageImage.src = url.href;
  });
  new ResizeObserver(() => resizeSourceImage()).observe(sourceScroll);
  window.addEventListener("resize", resizeReviewWorkspace);
}
