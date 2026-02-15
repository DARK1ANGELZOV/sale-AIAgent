"""Helpers for cleaning text and normalizing tabular data."""

from __future__ import annotations

import re


def clean_text(value: str) -> str:
    """Normalize whitespace and trim noisy fragments."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    return normalized


def normalize_table_rows(rows: list[list[str | None]]) -> str:
    """Convert table rows into comparable, retrieval-friendly text."""
    if not rows:
        return ""

    header = [clean_text(cell or "") for cell in rows[0]]
    lines: list[str] = []
    for row in rows[1:]:
        cells = [clean_text(cell or "") for cell in row]
        pairs = []
        for index, cell in enumerate(cells):
            column = header[index] if index < len(header) and header[index] else f"column_{index}"
            pairs.append(f"{column}: {cell}")
        row_text = "; ".join(pairs).strip("; ").strip()
        if row_text:
            lines.append(row_text)

    return "\n".join(lines).strip()
