from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from transcribl.domain.editorial import (
    UncertaintyFallback,
    UncertaintyHighlight,
)
from transcribl.domain.errors import (
    EditorialError,
)
from transcribl.domain.models import (
    TranslatedBlock,
    UncertainTerm,
)


@dataclass(frozen=True, slots=True)
class UncertaintySpec:
    uncertainty_id: str
    term_group_id: str
    block_id: str
    source_term: str
    proposed_translation: str
    reason: str
    alternatives: tuple[str, ...]
    machine_start_offset: int
    machine_end_offset: int


@dataclass(frozen=True, slots=True)
class _FallbackSpec:
    uncertainty_id: str
    term_group_id: str
    source_term: str
    proposed_translation: str | None
    reason: str
    alternatives: tuple[str, ...]


def machine_uncertainty_specs(
    block: TranslatedBlock,
) -> tuple[list[UncertaintySpec], list[_FallbackSpec]]:
    if block.translated_text is None:
        return [], []
    specs: list[UncertaintySpec] = []
    unlocated: list[_FallbackSpec] = []
    seen_terms: set[tuple[str, str | None]] = set()
    for uncertainty_number, uncertainty in enumerate(block.uncertainties, start=1):
        term_key = (uncertainty.source_term, uncertainty.proposed_translation)
        if term_key in seen_terms:
            continue
        seen_terms.add(term_key)
        group_id = _term_group_id(uncertainty)
        proposed = uncertainty.proposed_translation
        if not proposed:
            unlocated.append(
                _FallbackSpec(
                    uncertainty_id=f"{block.block_id}-u{uncertainty_number:04d}-o0000",
                    term_group_id=group_id,
                    source_term=uncertainty.source_term,
                    proposed_translation=proposed,
                    reason=uncertainty.reason,
                    alternatives=tuple(uncertainty.alternatives),
                )
            )
            continue
        positions = _find_occurrences(block.translated_text, proposed)
        if not positions:
            unlocated.append(
                _FallbackSpec(
                    uncertainty_id=f"{block.block_id}-u{uncertainty_number:04d}-o0000",
                    term_group_id=group_id,
                    source_term=uncertainty.source_term,
                    proposed_translation=proposed,
                    reason=uncertainty.reason,
                    alternatives=tuple(uncertainty.alternatives),
                )
            )
            continue
        for occurrence_number, (start, end) in enumerate(positions, start=1):
            specs.append(
                UncertaintySpec(
                    uncertainty_id=(
                        f"{block.block_id}-u{uncertainty_number:04d}-o{occurrence_number:04d}"
                    ),
                    term_group_id=group_id,
                    block_id=block.block_id,
                    source_term=uncertainty.source_term,
                    proposed_translation=proposed,
                    reason=uncertainty.reason,
                    alternatives=tuple(uncertainty.alternatives),
                    machine_start_offset=start,
                    machine_end_offset=end,
                )
            )
    return specs, unlocated


def _term_group_id(uncertainty: UncertainTerm) -> str:
    serialized = json.dumps(
        [uncertainty.source_term, uncertainty.proposed_translation],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _find_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    positions: list[tuple[int, int]] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return positions
        end = index + len(needle)
        positions.append((index, end))
        start = end


def locate_unresolved_specs(
    machine_text: str,
    effective_text: str,
    specs: list[UncertaintySpec],
    resolved_ids: set[str],
) -> tuple[list[UncertaintyHighlight], list[_FallbackSpec]]:
    specs_by_group: dict[str, list[UncertaintySpec]] = defaultdict(list)
    for spec in specs:
        if spec.uncertainty_id not in resolved_ids:
            specs_by_group[spec.term_group_id].append(spec)

    highlights: list[UncertaintyHighlight] = []
    unlocated: list[_FallbackSpec] = []
    equal_spans = [
        (machine_start, machine_end, effective_start, effective_end)
        for tag, machine_start, machine_end, effective_start, effective_end in SequenceMatcher(
            None,
            machine_text,
            effective_text,
            autojunk=False,
        ).get_opcodes()
        if tag == "equal"
    ]
    for grouped_specs in specs_by_group.values():
        used_positions: set[tuple[int, int]] = set()
        pending_specs: list[UncertaintySpec] = []
        located: list[tuple[UncertaintySpec, int, int]] = []
        for spec in grouped_specs:
            mapped = _map_equal_machine_span(spec, equal_spans)
            if (
                mapped is not None
                and effective_text[mapped[0] : mapped[1]] == spec.proposed_translation
            ):
                used_positions.add(mapped)
                located.append((spec, mapped[0], mapped[1]))
            else:
                pending_specs.append(spec)
        available_positions = [
            position
            for position in _find_occurrences(
                effective_text,
                grouped_specs[0].proposed_translation,
            )
            if position not in used_positions
        ]
        for spec, (start, end) in zip(pending_specs, available_positions, strict=False):
            located.append((spec, start, end))
        unlocated.extend(
            _FallbackSpec(
                uncertainty_id=spec.uncertainty_id,
                term_group_id=spec.term_group_id,
                source_term=spec.source_term,
                proposed_translation=spec.proposed_translation,
                reason=spec.reason,
                alternatives=spec.alternatives,
            )
            for spec in pending_specs[len(available_positions) :]
        )
        for spec, start, end in located:
            highlights.append(
                UncertaintyHighlight(
                    uncertainty_id=spec.uncertainty_id,
                    term_group_id=spec.term_group_id,
                    source_term=spec.source_term,
                    proposed_translation=spec.proposed_translation,
                    reason=spec.reason,
                    alternatives=list(spec.alternatives),
                    start_offset=start,
                    end_offset=end,
                    matching_occurrence_count=1,
                    can_replace_all=False,
                )
            )
    return (
        sorted(highlights, key=lambda highlight: (highlight.start_offset, highlight.end_offset)),
        unlocated,
    )


def to_fallback(spec: _FallbackSpec) -> UncertaintyFallback:
    return UncertaintyFallback(
        uncertainty_id=spec.uncertainty_id,
        term_group_id=spec.term_group_id,
        source_term=spec.source_term,
        proposed_translation=spec.proposed_translation,
        reason=spec.reason,
        alternatives=list(spec.alternatives),
    )


def _map_equal_machine_span(
    spec: UncertaintySpec,
    equal_spans: list[tuple[int, int, int, int]],
) -> tuple[int, int] | None:
    for machine_start, machine_end, effective_start, _ in equal_spans:
        if machine_start <= spec.machine_start_offset and spec.machine_end_offset <= machine_end:
            start = effective_start + spec.machine_start_offset - machine_start
            return start, start + len(spec.proposed_translation)
    return None


def replace_highlight_offsets(
    text: str,
    highlights: list[UncertaintyHighlight],
    replacement: str,
) -> str:
    if not replacement.strip():
        raise EditorialError("Replacement must not be blank")
    result = text
    for highlight in sorted(highlights, key=lambda item: item.start_offset, reverse=True):
        observed = result[highlight.start_offset : highlight.end_offset]
        if observed != highlight.proposed_translation:
            raise EditorialError("Uncertainty offsets no longer match the effective text")
        result = result[: highlight.start_offset] + replacement + result[highlight.end_offset :]
    return result
