from __future__ import annotations

import json
from pathlib import Path

from transcribl.adapters.storage.atomic import read


def read_core_payload(path: Path) -> object:
    """Read current core JSON or migrate supported legacy payloads in memory."""

    payload: object = json.loads(read(path))
    if not isinstance(payload, dict):
        return payload
    if payload.get("schema_version") == "2.0":
        return migrate_v5_payload(
            migrate_v4_payload(migrate_v3_payload(migrate_v2_payload(payload)))
        )
    if payload.get("schema_version") == "3.0":
        return migrate_v5_payload(migrate_v4_payload(migrate_v3_payload(payload)))
    if payload.get("schema_version") == "4.0":
        return migrate_v5_payload(migrate_v4_payload(payload))
    if payload.get("schema_version") == "5.0":
        return migrate_v5_payload(payload)
    return payload


def migrate_v5_payload(payload: dict[str, object]) -> dict[str, object]:
    """Expose schema-v5 artifacts through v6 without rewriting immutable files."""

    migrated = dict(payload)
    migrated["schema_version"] = "6.0"

    if "blocks" in migrated:
        migrated["blocks"] = migrate_v5_blocks(migrated["blocks"])

    pages = migrated.get("pages")
    if isinstance(pages, list) and any(
        isinstance(page, dict) and "schema_version" in page for page in pages
    ):
        migrated["pages"] = [
            migrate_v5_payload(page) if isinstance(page, dict) else page for page in pages
        ]
    return migrated


def migrate_v5_blocks(blocks: object) -> object:
    if not isinstance(blocks, list):
        return blocks
    migrated_blocks: list[object] = []
    for block in blocks:
        if not isinstance(block, dict):
            migrated_blocks.append(block)
            continue
        migrated_block = dict(block)
        legacy_marker = migrated_block.pop("footnote_marker", None)
        migrated_block.setdefault("footnote_id", None)
        migrated_block.setdefault("footnote_description", None)
        migrated_block.setdefault("footnote_continues_from_block_id", None)
        if migrated_block.get("type") == "footnote":
            page_number = migrated_block.get("original_page_number")
            order = migrated_block.get("order")
            if isinstance(page_number, int) and isinstance(order, int):
                migrated_block["footnote_id"] = {
                    "id": f"fn-p{page_number}-n{order}",
                    "text": legacy_marker,
                }
            migrated_block["footnote_description"] = {
                "appearance": "Not recorded by the legacy schema.",
                "handling": (
                    "Migrated as an independent review item; legacy artifacts did not "
                    "retain a cross-page footnote identity."
                ),
            }
            continuation = migrated_block.get("continuation")
            if continuation == "from_previous_page":
                migrated_block["continuation"] = "unknown"
                migrated_block["classification_review_required"] = True
            elif continuation == "from_previous_and_to_next_page":
                migrated_block["continuation"] = "to_next_page"
                migrated_block["classification_review_required"] = True
        migrated_blocks.append(migrated_block)
    return migrated_blocks


def migrate_v2_payload(payload: dict[str, object]) -> dict[str, object]:
    migrated = dict(payload)
    migrated["schema_version"] = "3.0"

    if "blocks" in migrated:
        migrated["blocks"] = migrate_v2_blocks(migrated["blocks"])

    pages = migrated.get("pages")
    if isinstance(pages, list) and any(
        isinstance(page, dict) and "schema_version" in page for page in pages
    ):
        migrated["pages"] = [
            migrate_v2_payload(page) if isinstance(page, dict) else page for page in pages
        ]
    return migrated


def migrate_v3_payload(payload: dict[str, object]) -> dict[str, object]:
    migrated = dict(payload)
    migrated["schema_version"] = "4.0"

    if "blocks" in migrated:
        migrated["blocks"] = migrate_v3_blocks(migrated["blocks"])

    pages = migrated.get("pages")
    if isinstance(pages, list) and any(
        isinstance(page, dict) and "schema_version" in page for page in pages
    ):
        migrated["pages"] = [
            migrate_v3_payload(page) if isinstance(page, dict) else page for page in pages
        ]
    return migrated


def migrate_v4_payload(payload: dict[str, object]) -> dict[str, object]:
    migrated = dict(payload)
    migrated["schema_version"] = "5.0"

    if "blocks" in migrated:
        migrated["blocks"] = migrate_v4_blocks(migrated["blocks"])

    pages = migrated.get("pages")
    if isinstance(pages, list) and any(
        isinstance(page, dict) and "schema_version" in page for page in pages
    ):
        migrated["pages"] = [
            migrate_v4_payload(page) if isinstance(page, dict) else page for page in pages
        ]
    return migrated


def migrate_v4_blocks(blocks: object) -> object:
    if not isinstance(blocks, list):
        return blocks
    migrated_blocks: list[object] = []
    for block in blocks:
        if not isinstance(block, dict):
            migrated_blocks.append(block)
            continue
        migrated_block = dict(block)
        migrated_block.setdefault("footnote_owner_block_id", None)
        migrated_block.setdefault("footnote_anchor_offset", None)
        migrated_block.setdefault(
            "footnote_owner_review_required",
            migrated_block.get("type") == "footnote",
        )
        migrated_blocks.append(migrated_block)
    return migrated_blocks


def migrate_v3_blocks(blocks: object) -> object:
    if not isinstance(blocks, list):
        return blocks
    migrated_blocks: list[object] = []
    for block in blocks:
        if not isinstance(block, dict):
            migrated_blocks.append(block)
            continue
        migrated_block = dict(block)
        migrated_block.setdefault("legacy_translated_table", False)
        migrated_block["legacy_manual_table"] = (
            migrated_block.get("type") == "table"
            and migrated_block.get("segment_handling") == "manual_insertion"
        )
        migrated_blocks.append(migrated_block)
    return migrated_blocks


def migrate_v2_blocks(blocks: object) -> object:
    if not isinstance(blocks, list):
        return blocks
    migrated_blocks: list[object] = []
    for block in blocks:
        if not isinstance(block, dict):
            migrated_blocks.append(block)
            continue
        migrated_block = dict(block)
        migrated_block.setdefault("segment_handling", "translate")
        migrated_block.setdefault("manual_insertion_reason", None)
        migrated_block.setdefault("footnote_marker", None)
        migrated_block.setdefault("continuation", None)
        migrated_block.setdefault("classification_review_required", False)
        migrated_block["legacy_translated_table"] = (
            migrated_block.get("type") == "table"
            and migrated_block.get("segment_handling") == "translate"
        )
        migrated_block.setdefault("legacy_manual_table", False)
        migrated_blocks.append(migrated_block)
    return migrated_blocks
