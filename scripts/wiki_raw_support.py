"""Helpers for distinguishing raw evidence from raw-folder support files."""

from __future__ import annotations

from pathlib import Path


AUXILIARY_RAW_MARKDOWN_STEMS = frozenset({"index", "索引"})
AUXILIARY_RAW_MARKDOWN_SUFFIXES = frozenset({".md", ".txt"})
AUXILIARY_RAW_FILENAMES = frozenset({"_translation_cache.json"})


def is_auxiliary_raw_source_path(path: str | Path) -> bool:
    """Return True for corpus support notes that should not become evidence."""
    candidate = Path(path)
    if candidate.name in AUXILIARY_RAW_FILENAMES:
        return True
    return (
        candidate.suffix.casefold() in AUXILIARY_RAW_MARKDOWN_SUFFIXES
        and candidate.stem.strip().casefold() in AUXILIARY_RAW_MARKDOWN_STEMS
    )
