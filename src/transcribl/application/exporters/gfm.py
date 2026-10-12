from __future__ import annotations

import re


def parse_gfm_table(value: str) -> tuple[list[str], list[list[str]], int] | None:
    lines = [line.strip() for line in value.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    header = _split_gfm_row(lines[0])
    separators = _split_gfm_row(lines[1])
    if not header or len(header) != len(separators):
        return None
    if any(re.fullmatch(r":?-{3,}:?", separator.strip()) is None for separator in separators):
        return None
    alignments = [
        "right" if separator.strip().endswith(":") else "left" for separator in separators
    ]
    rows = [header]
    for line in lines[2:]:
        row = _split_gfm_row(line)
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        rows.append(row[: len(header)])
    return alignments, rows, len(header)


def _split_gfm_row(line: str) -> list[str]:
    content = line.strip().removeprefix("|").removesuffix("|")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in content:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells
