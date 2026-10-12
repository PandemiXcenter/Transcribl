import { costBreakdown } from "./exports.js";
import {
  apiRequest
} from "./api.js";
import {
  backToTranslationsButton,
  cancelUncertaintyButton,
  closeUncertaintyButton,
  dismissAlert,
  newTranslationButton,
  refreshTranslationsButton,
  reviewEditor,
  reviewList,
  reviewPanel,
  reviewZoomSelect,
  state,
  translateAllButton,
  translateOneButton,
  translationContent,
  translationScroll,
  uncertaintyDialog,
  uncertaintyForm,
  uncertaintyGroupList,
  uncertaintyListButton
} from "./context.js";
import {
  activateTab,
  clearGlobalError,
  showGlobalError
} from "./dom.js";
import {
  handleReviewClick,
  handleReviewControlChange,
  handleReviewInput,
  handleReviewKeydown,
  handleReviewPaste,
  handleReviewToolbarChange
} from "./events.js";
import {
  handleReviewListClick,
  loadTranslationLibrary,
  openLibraryReview
} from "./library.js";
import {
  requestScrollSync,
  setReviewZoom
} from "./pages.js";
import {
  closeUncertainty,
  replaceUncertainty
} from "./uncertainties.js";
import {
  handleUncertaintyGroupClick,
  openUncertaintyList
} from "./uncertainty_list.js";

export async function initializeEditor() {
  translationContent.addEventListener('click', handleReviewClick);
  translationContent.addEventListener('keydown', handleReviewKeydown);
  translationContent.addEventListener('input', handleReviewInput);
  translationContent.addEventListener('change', handleReviewControlChange);
  translationContent.addEventListener('paste', handleReviewPaste);
  translationScroll.addEventListener('scroll', requestScrollSync, {passive: true});
  reviewPanel.addEventListener('change', handleReviewToolbarChange);
  window.addEventListener('resize', requestScrollSync);
  dismissAlert.addEventListener('click', clearGlobalError);
  reviewList.addEventListener('click', handleReviewListClick);
  refreshTranslationsButton.addEventListener('click', () => loadTranslationLibrary({activate: true}));
  backToTranslationsButton.addEventListener('click', () => {
    if (state.reviewDrafts.size && !window.confirm('Discard unsaved block edits?')) return;
    state.reviewDrafts = new Map();
    window.history.replaceState({}, '', '/');
    loadTranslationLibrary({activate: true});
  });
  newTranslationButton.addEventListener('click', () => activateTab('translate'));
  closeUncertaintyButton.addEventListener('click', closeUncertainty);
  cancelUncertaintyButton.addEventListener('click', closeUncertainty);
  uncertaintyListButton.addEventListener('click', openUncertaintyList);
  uncertaintyGroupList.addEventListener('click', handleUncertaintyGroupClick);
  translateOneButton.addEventListener('click', () => replaceUncertainty('one'));
  translateAllButton.addEventListener('click', () => replaceUncertainty('all'));
  uncertaintyForm.addEventListener('submit', (event) => {event.preventDefault(); replaceUncertainty('one');});
  uncertaintyDialog.addEventListener('cancel', () => {state.activeUncertaintyId = null;});
  window.addEventListener('beforeunload', (event) => {
    if (state.reviewDrafts.size || window.transcriblGlossaryDirty) {event.preventDefault(); event.returnValue = '';}
  });
  window.transcriblEditor = {
    open: openLibraryReview,
    refresh: loadTranslationLibrary,
    async refreshCosts() {
      await loadTranslationLibrary();
      if (state.review && state.jobId && !reviewEditor.hidden) {
        try {
          const job = await apiRequest(`/api/jobs/${encodeURIComponent(state.jobId)}`);
          state.review.cost = job.cost;
          document.getElementById("review-cost").replaceChildren(...(job.cost ? [costBreakdown(job.cost)] : []));
        } catch (error) {
          showGlobalError(error.message);
        }
      }
    },
    async initialize() {
      await fetch('/backend/session', {credentials: 'same-origin'});
      state.config = await apiRequest('/api/config');
      for (const level of state.config.review.zoom_levels) reviewZoomSelect.append(new Option(`${level}%`, String(level)));
      setReviewZoom(state.config.review.zoom_default_percent);
      await loadTranslationLibrary();
    },
  };
  await window.transcriblEditor.initialize();


}
