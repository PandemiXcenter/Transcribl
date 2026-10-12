import {
  state
} from "./context.js";
import {
  asText
} from "./dom.js";

export function buildReviewIndexes(pages) {
  state.blockIndex = new Map();
  state.uncertaintyIndex = new Map();
  state.uncertaintyGroups = [];
  state.footnoteEntrypointsByOwner = new Map();
  state.paragraphGroups = [];
  state.paragraphGroupByFragment = new Map();
  for (const page of pages) {
    for (const block of Array.isArray(page.blocks) ? page.blocks : []) {
      block.base_revision = Math.max(0, Number(block.base_revision) || 0);
      block.effective_text = asText(block.effective_text, asText(block.machine_text));
      block.review_status = asText(block.review_status, "unreviewed");
      block.uncertainties = Array.isArray(block.uncertainties) ? block.uncertainties : [];
      const entry = { block, page };
      state.blockIndex.set(asText(block.block_id), entry);
      block.uncertainties.forEach((uncertainty, index) => {
        const id = asText(uncertainty.uncertainty_id, `${block.block_id}-u${index + 1}`);
        uncertainty.uncertainty_id = id;
        state.uncertaintyIndex.set(id, { ...entry, uncertainty });
      });
    }
  }
  const identitiesByOwner = new Map();
  for (const { block } of state.blockIndex.values()) {
    const ownerId = asText(block.footnote_owner_block_id);
    if (block.type !== "footnote" || !ownerId) {
      continue;
    }
    const identity = asText(block.footnote_id?.id, block.block_id);
    const seen = identitiesByOwner.get(ownerId) || new Set();
    if (seen.has(identity)) {
      continue;
    }
    const offset = Number(block.footnote_anchor_offset);
    if (!Number.isInteger(offset) || offset < 0) {
      continue;
    }
    seen.add(identity);
    identitiesByOwner.set(ownerId, seen);
    const entrypoints = state.footnoteEntrypointsByOwner.get(ownerId) || [];
    entrypoints.push({
      identity,
      offset,
      text: asText(block.footnote_id?.text, "†"),
    });
    state.footnoteEntrypointsByOwner.set(ownerId, entrypoints);
  }
  for (const entrypoints of state.footnoteEntrypointsByOwner.values()) {
    entrypoints.sort((left, right) => left.offset - right.offset);
  }
  const paragraphGroups = Array.isArray(state.review?.paragraph_groups)
    ? state.review.paragraph_groups
    : [];
  for (const group of paragraphGroups) {
    const fragmentIds = Array.isArray(group.fragment_block_ids)
      ? group.fragment_block_ids.map((value) => asText(value))
      : [];
    if (
      fragmentIds.length < 2 ||
      fragmentIds[0] !== asText(group.paragraph_id) ||
      fragmentIds.some((blockId) => !state.blockIndex.has(blockId))
    ) {
      continue;
    }
    const normalized = {
      paragraph_id: asText(group.paragraph_id),
      fragment_block_ids: fragmentIds,
      original_page_numbers: Array.isArray(group.original_page_numbers)
        ? group.original_page_numbers.map(Number)
        : [],
    };
    state.paragraphGroups.push(normalized);
    for (const blockId of fragmentIds) {
      state.paragraphGroupByFragment.set(blockId, normalized);
    }
  }
}
