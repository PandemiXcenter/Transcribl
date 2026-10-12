import {
  state,
  translationContent,
  translationScroll,
  uncertaintyGroupList,
  uncertaintyListDialog
} from "./context.js";
import {
  asText,
  elementPositionInScroller,
  showGlobalError
} from "./dom.js";
import {
  activateSourcePageNumber,
  syncSourceToTranslation
} from "./pages.js";
import {
  openUncertainty
} from "./uncertainties.js";

export function openUncertaintyList() {
  if (!state.uncertaintyGroups.length) {
    return;
  }
  uncertaintyListDialog.showModal();
  requestAnimationFrame(() => {
    uncertaintyGroupList.querySelector("[data-action='open-uncertainty-group']")?.focus();
  });
}

export function handleUncertaintyGroupClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest("[data-action='open-uncertainty-group']");
  if (!button || !uncertaintyGroupList.contains(button)) {
    return;
  }
  const uncertaintyId = asText(button.dataset.uncertaintyId);
  const entry = state.uncertaintyIndex.get(uncertaintyId);
  if (!entry) {
    showGlobalError("This uncertainty is no longer available. Refresh the review.");
    return;
  }
  uncertaintyListDialog.close();
  const matchingEditor = [...translationContent.querySelectorAll(".translated-editor")].find(
    (element) => element.dataset.blockId === asText(entry.block.block_id),
  );
  const blockElement = matchingEditor?.closest(".translation-block");
  if (blockElement) {
    translationScroll.scrollTop = Math.max(
      0,
      elementPositionInScroller(blockElement, translationScroll) - 72,
    );
    syncSourceToTranslation();
    activateSourcePageNumber(Number(entry.page.original_page_number));
  }
  requestAnimationFrame(() => openUncertainty(uncertaintyId));
}
