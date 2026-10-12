import {
  globalAlert,
  globalAlertMessage
} from "./context.js";

export function createElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (text !== undefined && text !== null) {
    element.textContent = String(text);
  }
  return element;
}

export function asText(value, fallback = "") {
  if (value === undefined || value === null) {
    return fallback;
  }
  return String(value);
}

export function setInlineError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

export function humanize(value) {
  const text = asText(value);
  if (!text) {
    return "Unknown";
  }
  return text
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function pageDescription(page) {
  const parts = [];
  if (page.pdf_page_label) {
    parts.push(`PDF label ${asText(page.pdf_page_label)}`);
  }
  if (page.detected_printed_page_label) {
    parts.push(`printed ${asText(page.detected_printed_page_label)}`);
  }
  return parts.join(" · ");
}

export function makePageLabel(page) {
  const label = createElement(
    "p",
    "page-label",
    `Physical page ${Number(page.original_page_number) || 1}`,
  );
  const details = pageDescription(page);
  label.classList.add("page-sync-anchor");
  label.dataset.pageNumber = asText(page.original_page_number);
  if (details) {
    label.append(createElement("span", "", details));
  }
  return label;
}

export function reviewStatusClass(status) {
  if (status === "accepted") {
    return "accepted";
  }
  if (status === "needs_work") {
    return "needs-work";
  }
  return "";
}

export function renderedPageElement(container, pageNumber) {
  return [...container.querySelectorAll(".review-page")].find(
    (page) => Number(page.dataset.pageNumber) === Number(pageNumber),
  );
}

export function elementPositionInScroller(element, scroller) {
  const elementRect = element.getBoundingClientRect();
  const scrollerRect = scroller.getBoundingClientRect();
  return elementRect.top - scrollerRect.top + scroller.scrollTop;
}


export function activateTab(name) {
  emitEvent('transcribl-tab', name === 'review' ? 'Articles' : 'Translate');
}


export function showGlobalError(message) {
  globalAlertMessage.textContent = message;
  globalAlert.hidden = false;
  globalAlert.focus();
}

export function clearGlobalError() {
  globalAlert.hidden = true;
  globalAlertMessage.textContent = "";
}
