import {
  state
} from "./context.js";
import {
  asText,
  createElement
} from "./dom.js";

export function unresolvedUncertainties(block) {
  return Array.isArray(block.uncertainties)
    ? block.uncertainties.filter((uncertainty) => !uncertainty.resolved)
    : [];
}

export function uncertaintyNeedle(uncertainty) {
  return asText(
    uncertainty.highlight_text ||
      uncertainty.proposed_translation ||
      uncertainty.source_term,
  ).trim();
}

export function findAvailableRange(text, needle, occupied) {
  if (!needle) {
    return null;
  }
  let index = text.indexOf(needle);
  while (index !== -1) {
    const start = Array.from(text.slice(0, index)).length;
    const end = start + Array.from(needle).length;
    const overlaps = occupied.some((range) => start < range.end && end > range.start);
    if (!overlaps) {
      return { start, end };
    }
    index = text.indexOf(needle, index + Math.max(needle.length, 1));
  }

  const lowerText = text.toLocaleLowerCase();
  const lowerNeedle = needle.toLocaleLowerCase();
  if (lowerNeedle.length !== needle.length) {
    return null;
  }
  index = lowerText.indexOf(lowerNeedle);
  while (index !== -1) {
    const start = Array.from(text.slice(0, index)).length;
    const end = start + Array.from(text.slice(index, index + needle.length)).length;
    const overlaps = occupied.some((range) => start < range.end && end > range.start);
    if (!overlaps) {
      return { start, end };
    }
    index = lowerText.indexOf(lowerNeedle, index + Math.max(needle.length, 1));
  }
  return null;
}

export function makeUncertaintyMark(text, entry) {
  const mark = createElement("mark", "uncertainty-mark", text);
  mark.dataset.testid = "uncertainty-highlight";
  mark.dataset.action = "review-uncertainty";
  mark.dataset.uncertaintyId = asText(entry.uncertainty.uncertainty_id);
  mark.tabIndex = 0;
  mark.setAttribute("role", "button");
  mark.setAttribute("contenteditable", "false");
  mark.setAttribute(
    "aria-label",
    `Uncertain translation: ${text}. Open reviewer options.`,
  );
  return mark;
}

export function footnoteEntrypointsForBlock(block) {
  return state.footnoteEntrypointsByOwner.get(asText(block.block_id)) || [];
}

export function makeFootnoteEntrypointMarker(entrypoint) {
  const marker = createElement("sup", "footnote-entrypoint-marker", entrypoint.text);
  marker.dataset.editorDisplayOnly = "true";
  marker.dataset.footnoteId = entrypoint.identity;
  marker.setAttribute("contenteditable", "false");
  marker.setAttribute("role", "note");
  marker.setAttribute("aria-label", `Footnote entrypoint ${entrypoint.identity}`);
  marker.title = `Footnote entrypoint ${entrypoint.identity}`;
  return marker;
}

export function appendTextWithFootnoteEntrypoints(
  container,
  codePoints,
  start,
  end,
  entrypoints,
) {
  let cursor = start;
  for (const entrypoint of entrypoints) {
    const offset = Math.min(Math.max(entrypoint.offset, start), end);
    if (offset < cursor) {
      continue;
    }
    if (offset > cursor) {
      container.append(document.createTextNode(codePoints.slice(cursor, offset).join("")));
    }
    container.append(makeFootnoteEntrypointMarker(entrypoint));
    cursor = offset;
  }
  if (cursor < end) {
    container.append(document.createTextNode(codePoints.slice(cursor, end).join("")));
  }
}

export function renderHighlightedText(container, text, block) {
  const codePoints = Array.from(text);
  const entrypoints = footnoteEntrypointsForBlock(block).map((entrypoint) => ({
    ...entrypoint,
    offset: Math.min(entrypoint.offset, codePoints.length),
  }));
  const ranges = [];
  const handled = new Set();
  for (const uncertainty of unresolvedUncertainties(block)) {
    const entry = state.uncertaintyIndex.get(asText(uncertainty.uncertainty_id));
    if (!entry) {
      continue;
    }
    let range = null;
    const startOffset = Number(uncertainty.start_offset);
    const endOffset = Number(uncertainty.end_offset);
    const offsetText =
      Number.isInteger(startOffset) &&
      Number.isInteger(endOffset) &&
      startOffset >= 0 &&
      endOffset > startOffset &&
      endOffset <= codePoints.length
        ? codePoints.slice(startOffset, endOffset).join("")
        : "";
    if (
      uncertainty.highlight_mode === "range" &&
      offsetText === uncertaintyNeedle(uncertainty)
    ) {
      const overlaps = ranges.some(
        (existing) => startOffset < existing.end && endOffset > existing.start,
      );
      range = overlaps ? null : { start: startOffset, end: endOffset };
    } else if (uncertainty.highlight_mode !== "block") {
      range = findAvailableRange(text, uncertaintyNeedle(uncertainty), ranges);
    }
    if (range) {
      ranges.push({ ...range, entry });
      handled.add(asText(uncertainty.uncertainty_id));
    }
  }

  ranges.sort((left, right) => left.start - right.start);
  let cursor = 0;
  for (const range of ranges) {
    if (range.start > cursor) {
      appendTextWithFootnoteEntrypoints(
        container,
        codePoints,
        cursor,
        range.start,
        entrypoints.filter(
          (entrypoint) => entrypoint.offset >= cursor && entrypoint.offset < range.start,
        ),
      );
    }
    const uncertaintyMark = makeUncertaintyMark(
      codePoints.slice(range.start, range.end).join(""),
      range.entry,
    );
    uncertaintyMark.replaceChildren();
    appendTextWithFootnoteEntrypoints(
      uncertaintyMark,
      codePoints,
      range.start,
      range.end,
      entrypoints.filter(
        (entrypoint) =>
          entrypoint.offset >= range.start && entrypoint.offset < range.end,
      ),
    );
    container.append(uncertaintyMark);
    cursor = range.end;
  }
  appendTextWithFootnoteEntrypoints(
    container,
    codePoints,
    cursor,
    codePoints.length,
    entrypoints.filter((entrypoint) => entrypoint.offset >= cursor),
  );
  return handled;
}
