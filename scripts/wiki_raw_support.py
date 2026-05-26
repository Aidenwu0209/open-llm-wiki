"""Helpers for distinguishing raw evidence from raw-folder support files."""

from __future__ import annotations

from pathlib import Path


AUXILIARY_RAW_MARKDOWN_STEMS = frozenset({"index", "索引"})
AUXILIARY_RAW_MARKDOWN_SUFFIXES = frozenset({".md", ".txt"})


def is_auxiliary_raw_source_path(path: str | Path) -> bool:
    """Return True for corpus support notes that should not become evidence."""
    candidate = Path(path)
    return (
        candidate.suffix.casefold() in AUXILIARY_RAW_MARKDOWN_SUFFIXES
        and candidate.stem.strip().casefold() in AUXILIARY_RAW_MARKDOWN_STEMS
    )
