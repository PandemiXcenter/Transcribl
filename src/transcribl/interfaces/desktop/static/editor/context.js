
// One browser window's effective review state and mounted DOM references.
export const state = {
  config: null,
  reviewMutationPending: false,
  reviewLoadGeneration: 0,
  pendingOpenId: null,
  renderGeneration: 0,
  jobId: null,
  job: null,
  review: null,
  blockIndex: new Map(),
  uncertaintyIndex: new Map(),
  uncertaintyGroups: [],
  reviewPages: [],
  paragraphGroups: [],
  paragraphGroupByFragment: new Map(),
  reviewDrafts: new Map(),
  footnoteEntrypointsByOwner: new Map(),
  sourcePageNumber: null,
  reviewZoomPercent: null,
  allowPositionPersistence: false,
  lastPersistedPage: null,
  positionQueue: Promise.resolve(),
  activeUncertaintyId: null,
  scrollFrame: null,
};

export const reviewDocument = document.querySelector("#review-document");
export const reviewProgress = document.querySelector("#review-progress");
export const exportPdfLink = document.querySelector("#export-pdf-link");
export const exportLatexLink = document.querySelector("#export-latex-link");
export const exportMarkdownLink = document.querySelector("#export-markdown-link");
export const exportTextLink = document.querySelector("#export-text-link");
export const activePageLabel = document.querySelector("#active-page-label");
export const sourceScroll = document.querySelector("#source-scroll");
export const translationScroll = document.querySelector("#translation-scroll");
export const translationContent = document.querySelector("#translation-content");
export const sourcePageLabel = document.querySelector("#source-page-label");
export const sourcePageImage = document.querySelector("#source-page-image");
export const fullSizePageLink = document.querySelector("#full-size-page-link");
export const reviewZoomSelect = document.querySelector("#review-zoom-select");
export const uncertaintyDialog = document.querySelector("#uncertainty-dialog");
export const uncertaintyListButton = document.querySelector("#uncertainty-list-button");
export const uncertaintyListDialog = document.querySelector("#uncertainty-list-dialog");
export const uncertaintyGroupList = document.querySelector("#uncertainty-group-list");
export const uncertaintyGroupEmpty = document.querySelector("#uncertainty-group-empty");
export const uncertaintyForm = document.querySelector("#uncertainty-form");
export const closeUncertaintyButton = document.querySelector("#close-uncertainty");
export const cancelUncertaintyButton = document.querySelector("#cancel-uncertainty");
export const translateOneButton = document.querySelector("#translate-one");
export const translateAllButton = document.querySelector("#translate-all");
export const replacementInput = document.querySelector("#replacement-input");
export const replacementError = document.querySelector("#replacement-error");
export const replacementField = document.querySelector("#replacement-field");
export const fallbackInstruction = document.querySelector("#fallback-instruction");
export const reviewPanel = document.querySelector("#review-panel");
export const reviewLibrary = document.querySelector("#review-library");
export const reviewEditor = document.querySelector("#review-editor");
export const reviewList = document.querySelector("#review-list");
export const reviewListEmpty = document.querySelector("#review-list-empty");
export const refreshTranslationsButton = document.querySelector("#refresh-translations");
export const backToTranslationsButton = document.querySelector("#back-to-translations");
export const globalAlert = document.querySelector("#global-alert");
export const globalAlertMessage = document.querySelector("#global-alert-message");
export const dismissAlert = document.querySelector("#dismiss-alert");
export const EDITABLE_BLOCK_TYPES = [
  "title",
  "subtitle",
  "byline",
  "heading",
  "body",
  "list_item",
  "quote",
  "caption",
  "footnote",
  "page_number",
  "header",
  "footer",
  "equation",
  "other",
];

