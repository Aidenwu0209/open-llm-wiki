#!/usr/bin/env python3
"""Source registry module: single source of truth for ingest identity and status."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, read_text, write_text

VALID_STATUSES = frozenset({
    "candidate", "queued", "parsed", "chunked", "drafted",
    "qa_passed", "published", "stale", "failed", "archived",
})

REQUIRED_FIELDS = frozenset({
    "source_uuid", "raw_hash", "status", "source_id", "raw_path",
})

OPTIONAL_FIELDS = frozenset({
    "duplicate_of", "last_error", "title", "arxiv", "doi",
    "sha256", "title_key", "kind", "path", "updated", "created",
    "tags", "concepts",
})

SOURCE_ID_RE = re.compile(r"^LLM-\d{4}$")


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def save_registry(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    write_text(path, text)


def raw_hash(raw_path: Path) -> str:
    digest = hashlib.sha256()
    with raw_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_id_counter(state_dir: Path) -> int:
    counter_path = state_dir / "id-counter.md"
    if not counter_path.exists():
        return 1
    text = read_text(counter_path)
    for line in text.splitlines():
        if line.strip().startswith("next:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                return 1
    return 1


def write_id_counter(state_dir: Path, next_id: int) -> None:
    write_text(
        ensure_within(state_dir / "id-counter.md", state_dir, "id-counter must stay under _state/"),
        f"# ID Counter\nnext: {next_id}\n",
    )


def allocate_source_id(state_dir: Path) -> str:
    next_id = read_id_counter(state_dir)
    source_id = f"LLM-{next_id:04d}"
    write_id_counter(state_dir, next_id + 1)
    return source_id


def find_by_raw_hash(rows: list[dict[str, Any]], h: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("raw_hash") == h:
            return row
    return None


def find_by_source_id(rows: list[dict[str, Any]], source_id: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("source_id") == source_id:
            return row
    return None


def find_by_source_uuid(rows: list[dict[str, Any]], source_uuid: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("source_uuid") == source_uuid:
            return row
    return None


def find_by_raw_path(rows: list[dict[str, Any]], raw_path: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("raw_path") == raw_path:
            return row
    return None


def register_raw(
    registry_path: Path,
    state_dir: Path,
    raw_path: str,
    raw_file: Path,
    title: str = "",
    arxiv: str = "",
    doi: str = "",
    kind: str = "raw",
) -> dict[str, Any]:
    rows = load_registry(registry_path)
    h = raw_hash(raw_file)

    existing = find_by_raw_hash(rows, h)
    if existing is not None:
        return existing

    existing_by_path = find_by_raw_path(rows, raw_path)
    if existing_by_path is not None:
        existing_by_path["raw_hash"] = h
        save_registry(registry_path, rows)
        return existing_by_path

    source_uuid = str(uuid.uuid4())
    source_id = allocate_source_id(state_dir)
    now = datetime.now().strftime("%Y-%m-%d")

    row: dict[str, Any] = {
        "source_uuid": source_uuid,
        "source_id": source_id,
        "raw_hash": h,
        "raw_path": raw_path,
        "status": "candidate",
        "title": title,
        "arxiv": arxiv,
        "doi": doi,
        "kind": kind,
        "created": now,
        "updated": now,
    }
    rows.append(row)
    save_registry(registry_path, rows)
    return row


def update_status(
    registry_path: Path,
    source_uuid: str,
    status: str,
    last_error: str = "",
    **extra: Any,
) -> dict[str, Any] | None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {sorted(VALID_STATUSES)}")
    rows = load_registry(registry_path)
    row = find_by_source_uuid(rows, source_uuid)
    if row is None:
        return None
    row["status"] = status
    row["updated"] = datetime.now().strftime("%Y-%m-%d")
    if last_error:
        row["last_error"] = last_error
    elif "last_error" in row and status != "failed":
        del row["last_error"]
    for key, value in extra.items():
        row[key] = value
    save_registry(registry_path, rows)
    return row


def mark_duplicate(
    registry_path: Path,
    duplicate_uuid: str,
    original_uuid: str,
) -> dict[str, Any] | None:
    rows = load_registry(registry_path)
    dup_row = find_by_source_uuid(rows, duplicate_uuid)
    if dup_row is None:
        return None
    orig_row = find_by_source_uuid(rows, original_uuid)
    if orig_row is None:
        return None
    dup_row["duplicate_of"] = orig_row["source_id"]
    dup_row["status"] = "archived"
    dup_row["updated"] = datetime.now().strftime("%Y-%m-%d")
    save_registry(registry_path, rows)
    return dup_row


def candidates_for_ingest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("duplicate_of"):
            continue
        if row.get("status") in ("candidate", "queued", "failed"):
            result.append(row)
    return result


def validate_registry(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    source_ids: dict[str, int] = {}
    source_uuids: dict[str, int] = {}

    for i, row in enumerate(rows):
        prefix = f"row {i + 1}"

        missing = REQUIRED_FIELDS - set(row.keys())
        if missing:
            issues.append((prefix, f"missing required fields: {sorted(missing)}"))

        status = row.get("status", "")
        if status and status not in VALID_STATUSES:
            issues.append((prefix, f"invalid status {status!r}"))

        source_id = row.get("source_id", "")
        if source_id:
            if not SOURCE_ID_RE.match(source_id):
                issues.append((prefix, f"invalid source_id format: {source_id!r}"))
            source_ids[source_id] = source_ids.get(source_id, 0) + 1

        source_uuid = row.get("source_uuid", "")
        if source_uuid:
            source_uuids[source_uuid] = source_uuids.get(source_uuid, 0) + 1

        dup_of = row.get("duplicate_of", "")
        if dup_of:
            found = any(r.get("source_id") == dup_of for r in rows)
            if not found:
                issues.append((prefix, f"duplicate_of points to non-existent source_id: {dup_of!r}"))

    for sid, count in source_ids.items():
        if count > 1:
            issues.append(("registry", f"duplicate source_id: {sid} (appears {count} times)"))

    for suid, count in source_uuids.items():
        if count > 1:
            issues.append(("registry", f"duplicate source_uuid: {suid} (appears {count} times)"))

    return issues
