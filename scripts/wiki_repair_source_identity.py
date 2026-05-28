#!/usr/bin/env python3
"""Repair legacy source_uuid values after the stable source_id contract."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, json_dump, read_text, write_text
from wiki_source_registry import load_registry, save_registry, source_uuid_from_id


JSONL_FILES = [
    Path("claims/claims.jsonl"),
    Path("_state/science-review-queue.jsonl"),
    Path("_state/growth-queue.jsonl"),
    Path("_state/desktop-source-registry.jsonl"),
    Path("_state/desktop-artifacts.jsonl"),
]

JSON_FILES = [
    Path("_state/ingest-plan.json"),
    Path("_state/desktop-ingest-plan.json"),
]


@dataclass
class Change:
    path: str
    changed: int
    total: int

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "changed": self.changed, "total": self.total}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{number}: invalid JSONL row: {exc}") from exc
        if not isinstance(item, dict):
            raise SystemExit(f"{path}:{number}: JSONL row must be an object")
        rows.append(item)
    return rows


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def canonical_uuid_for_item(item: dict[str, Any]) -> str:
    source_id = str(item.get("source_id") or item.get("sourceId") or "")
    if not source_id:
        return ""
    return source_uuid_from_id(source_id)


def rewrite_object(value: Any, replacements: dict[str, str]) -> tuple[Any, int]:
    if isinstance(value, dict):
        changed = 0
        updated: dict[str, Any] = {}
        for key, nested in value.items():
            new_nested, nested_changed = rewrite_object(nested, replacements)
            updated[key] = new_nested
            changed += nested_changed

        canonical = canonical_uuid_for_item(updated)
        if canonical:
            for key in ("source_uuid", "sourceUuid"):
                old = updated.get(key)
                if isinstance(old, str) and old != canonical:
                    updated[key] = canonical
                    changed += 1
        return updated, changed

    if isinstance(value, list):
        changed = 0
        updated_items = []
        for item in value:
            new_item, item_changed = rewrite_object(item, replacements)
            updated_items.append(new_item)
            changed += item_changed
        return updated_items, changed

    if isinstance(value, str) and value in replacements:
        return replacements[value], 1

    return value, 0


def registry_repair_plan(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, str]], int]:
    updated_rows: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    replacement_rows: list[dict[str, str]] = []
    changed = 0

    for row in rows:
        updated = dict(row)
        source_id = str(updated.get("source_id", ""))
        current = str(updated.get("source_uuid", ""))
        if source_id:
            expected = source_uuid_from_id(source_id)
            if current != expected:
                if current:
                    previous = replacements.get(current)
                    if previous and previous != expected:
                        raise SystemExit(
                            f"cannot repair ambiguous source_uuid {current!r}: maps to both {previous!r} and {expected!r}"
                        )
                    replacements[current] = expected
                updated["source_uuid"] = expected
                replacement_rows.append({"source_id": source_id, "from": current, "to": expected})
                changed += 1
        updated_rows.append(updated)

    return updated_rows, replacements, replacement_rows, changed


def repair_jsonl(path: Path, replacements: dict[str, str], write: bool) -> Change:
    rows = load_jsonl(path)
    updated_rows: list[dict[str, Any]] = []
    changed = 0
    for row in rows:
        updated, row_changed = rewrite_object(row, replacements)
        if not isinstance(updated, dict):
            raise SystemExit(f"{path}: repaired JSONL row must remain an object")
        updated_rows.append(updated)
        if row_changed:
            changed += 1
    if write and changed:
        save_jsonl(path, updated_rows)
    return Change(path.as_posix(), changed, len(rows))


def repair_json(path: Path, replacements: dict[str, str], write: bool) -> Change:
    data = json.loads(read_text(path))
    updated, changed = rewrite_object(data, replacements)
    if write and changed:
        write_text(path, json_dump(updated) + "\n")
    return Change(path.as_posix(), 1 if changed else 0, 1)


def markdown_report(report: dict[str, object]) -> str:
    files = report.get("files", [])
    file_lines = "\n".join(
        f"- `{item['path']}`: {item['changed']} changed / {item['total']} total"
        for item in files
        if isinstance(item, dict)
    ) or "- none"
    replacement_count = len(report.get("replacements", []))
    return (
        "# Source Identity Repair\n\n"
        f"- mode: {report['mode']}\n"
        f"- registry_rows_changed: {report['registry_rows_changed']}\n"
        f"- replacement_count: {replacement_count}\n\n"
        "## Files\n\n"
        f"{file_lines}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair legacy source_uuid values so registry, claims, and ingest state use stable source_id-derived UUIDs."
    )
    parser.add_argument("vault", type=Path)
    parser.add_argument("--write", action="store_true", help="Write repaired state files. Default is dry-run.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    vault = args.vault.resolve()
    registry_path = ensure_within(vault / "_state" / "source-registry.jsonl", vault, "registry must stay inside the vault")
    if not registry_path.exists():
        raise SystemExit("missing _state/source-registry.jsonl")

    registry_rows = load_registry(registry_path)
    repaired_registry, replacements, replacement_rows, registry_changed = registry_repair_plan(registry_rows)

    file_changes: list[Change] = []
    for relpath in JSONL_FILES:
        path = ensure_within(vault / relpath, vault, f"{relpath} must stay inside the vault")
        if path.exists():
            file_changes.append(repair_jsonl(path, replacements, args.write))
    for relpath in JSON_FILES:
        path = ensure_within(vault / relpath, vault, f"{relpath} must stay inside the vault")
        if path.exists():
            file_changes.append(repair_json(path, replacements, args.write))

    if args.write and registry_changed:
        save_registry(registry_path, repaired_registry)

    report = {
        "vault": str(vault),
        "mode": "write" if args.write else "dry-run",
        "registry_rows_changed": registry_changed,
        "replacements": replacement_rows,
        "files": [change.as_dict() for change in file_changes],
    }
    print(json_dump(report) if args.format == "json" else markdown_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
