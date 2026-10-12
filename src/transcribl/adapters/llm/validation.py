from __future__ import annotations

from copy import deepcopy
from typing import cast

from pydantic import BaseModel


def repair_page_continuations(parsed: object) -> object:
    """Downgrade contradictory page-edge claims and require human review.

    Structured JSON schemas cannot express that only the first/last flow body may
    cross a physical page boundary. Valid output is returned untouched. An
    impossible edge claim cannot be linked safely, so retain any non-conflicting
    direction, otherwise use ``unknown``, and make the ambiguity visible during
    editorial review.
    """

    if isinstance(parsed, BaseModel):
        return parsed
    if not isinstance(parsed, dict) or not isinstance(parsed.get("blocks"), list):
        return parsed
    repaired = deepcopy(parsed)
    blocks = cast(list[object], repaired["blocks"])
    mappings = [block for block in blocks if isinstance(block, dict)]
    body_blocks = [block for block in mappings if block.get("type") == "body"]
    if not body_blocks:
        return repaired
    incoming_flow = [
        block for block in mappings if block.get("type") not in {"header", "footer", "page_number"}
    ]
    outgoing_flow = [block for block in incoming_flow if block.get("type") != "footnote"]
    allowed_incoming = (
        body_blocks[0] if incoming_flow and incoming_flow[0] is body_blocks[0] else None
    )
    allowed_outgoing = (
        body_blocks[-1] if outgoing_flow and outgoing_flow[-1] is body_blocks[-1] else None
    )
    incoming_values = {"from_previous_page", "from_previous_and_to_next_page"}
    outgoing_values = {"to_next_page", "from_previous_and_to_next_page"}
    for block in body_blocks:
        continuation = block.get("paragraph_continuation")
        has_incoming = continuation in incoming_values
        has_outgoing = continuation in outgoing_values
        invalid_incoming = has_incoming and block is not allowed_incoming
        invalid_outgoing = has_outgoing and block is not allowed_outgoing
        if not invalid_incoming and not invalid_outgoing:
            continue
        keep_incoming = has_incoming and not invalid_incoming
        keep_outgoing = has_outgoing and not invalid_outgoing
        if keep_incoming and keep_outgoing:
            repaired_value = "from_previous_and_to_next_page"
        elif keep_incoming:
            repaired_value = "from_previous_page"
        elif keep_outgoing:
            repaired_value = "to_next_page"
        else:
            repaired_value = "unknown"
        block["paragraph_continuation"] = repaired_value
        block["classification_review_required"] = True
    return repaired
