#!/usr/bin/env python3
"""Generate a runtime-owned ingest plan from vault state.

Desktop clients should consume ``_state/ingest-plan.json`` instead of
maintaining their own ``desktop-ingest-plan.json`` or
``desktop-ingest-registry.jsonl``.  The runtime owns all plan and
registry state; desktop merely reads and executes actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, read_text, write_text
from wiki_raw_support import is_auxiliary_raw_source_path
from wiki_source_registry import (
    load_registry,
    raw_hash,
    find_by_raw_path,
)

PLAN_VERSION = 1
PLAN_STATES = frozenset({
    "ready", "stageable", "blocked", "cached",
    "published", "failed", "stale",
})
ARCHIVE_SUFFIXES = frozenset({".zip"})
IGNORED_RAW_DIRS = frozenset({"__MACOSX", "inbox"})


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_for_combined(vault: Path, combined: Path) -> dict[str, Any] | None:
    manifest_path = combined.parent / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(read_text(manifest_path))
    except (json.JSONDecodeError, OSError):
        return None


def _path_to_vault_rel(vault: Path, path_text: str) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(vault).as_posix()
        except ValueError:
            return ""
    clean = path.as_posix().lstrip("./")
    if clean == ".." or clean.startswith("../"):
        return ""
    return clean


def _raw_rels_from_manifest(vault: Path, manifest: dict[str, Any]) -> list[str]:
    rels: list[str] = []
    for key in ("source_path", "input"):
        rel = _path_to_vault_rel(vault, str(manifest.get(key, "")))
        if rel.startswith("raw/") and rel not in rels:
            rels.append(rel)
    return rels


def _fallback_raw_rel_for_combined(raw_dir: Path, combined: Path) -> str:
    parent_rel = combined.parent.relative_to(raw_dir)
    markdown_dir = parent_rel.name
    if not markdown_dir.endswith("_markdown"):
        return ""
    source_name = f"{markdown_dir.removesuffix('_markdown')}.pdf"
    return Path("raw").joinpath(*parent_rel.parent.parts, source_name).as_posix()


def _combined_files_by_raw(vault: Path) -> dict[str, Path]:
    combined_files: dict[str, Path] = {}
    raw_dir = vault / "raw"
    if not raw_dir.exists():
        return combined_files
    for combined in raw_dir.rglob("*_markdown/combined.md"):
        manifest = _manifest_for_combined(vault, combined) or {}
        raw_rels = _raw_rels_from_manifest(vault, manifest)
        fallback = _fallback_raw_rel_for_combined(raw_dir, combined)
        if fallback and fallback not in raw_rels:
            raw_rels.append(fallback)
        for raw_rel in raw_rels:
            combined_files.setdefault(raw_rel, combined)
    return combined_files


def _is_ignored_raw_file(raw_dir: Path, path: Path) -> bool:
    try:
        rel_parts = path.relative_to(raw_dir).parts
    except ValueError:
        return True
    parent_parts = rel_parts[:-1]
    return (
        path.name.startswith(".")
        or is_auxiliary_raw_source_path(path)
        or any(part.startswith(".") or part.endswith("_markdown") or part in IGNORED_RAW_DIRS for part in parent_parts)
    )


def _raw_source_files(vault: Path) -> list[Path]:
    raw_dir = vault / "raw"
    if not raw_dir.exists():
        return []
    return sorted(
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and not _is_ignored_raw_file(raw_dir, path)
    )


def _parse_artifact_for_raw(vault: Path, raw_rel: str, combined_files: dict[str, Path]) -> dict[str, Any]:
    raw_path = vault / raw_rel
    result: dict[str, Any] = {
        "artifact_path": "",
        "artifact_hash": "",
        "manifest_source_hash": "",
        "parser": "",
        "parser_version": "",
    }
    combined = combined_files.get(raw_rel)
    if combined is None and raw_path.is_file():
        stem = raw_path.stem
        candidates = [
            raw_path.parent / f"{stem}_markdown" / "combined.md",
            vault / "raw" / f"{stem}_markdown" / "combined.md",
        ]
        combined = next((candidate for candidate in candidates if candidate.exists()), None)
    if combined and combined.exists():
        result["artifact_path"] = combined.relative_to(vault).as_posix()
        result["artifact_hash"] = _hash(combined)
        manifest = _manifest_for_combined(vault, combined)
        if manifest:
            result["manifest_source_hash"] = str(manifest.get("source_sha256", ""))
            result["parser"] = manifest.get("parser", "layout-api")
            result["parser_version"] = manifest.get("parser_version", manifest.get("version", ""))
    return result


def _source_page_for_registry_row(vault: Path, row: dict[str, Any]) -> dict[str, Any]:
    source_id = row.get("source_id", "")
    result: dict[str, Any] = {
        "source_page_path": "",
        "source_page_hash": "",
    }
    if not source_id:
        return result
    source_path = vault / "sources" / f"{source_id}.md"
    if source_path.exists():
        result["source_page_path"] = source_path.relative_to(vault).as_posix()
        result["source_page_hash"] = _hash(source_path)
    return result


def classify_source(
    vault: Path,
    row: dict[str, Any],
    combined_files: dict[str, Path],
) -> dict[str, Any]:
    raw_rel = row.get("raw_path", "") or row.get("path", "")
    registry_status = row.get("status", "candidate")
    source_id = row.get("source_id", "")
    source_uuid = row.get("source_uuid", "")

    artifact = _parse_artifact_for_raw(vault, raw_rel, combined_files)
    source_page = _source_page_for_registry_row(vault, row)

    plan_item: dict[str, Any] = {
        "source_path": raw_rel,
        "source_hash": row.get("raw_hash", ""),
        "artifact_path": artifact["artifact_path"],
        "artifact_hash": artifact["artifact_hash"],
        "manifest_source_hash": artifact["manifest_source_hash"],
        "parser": artifact["parser"],
        "parser_version": artifact["parser_version"],
        "source_uuid": source_uuid,
        "source_id": source_id,
        "state": "",
        "reason": "",
        "recommended_action": "",
        "freshness_verdict": "",
    }

    has_artifact = bool(artifact["artifact_path"]) and bool(artifact["artifact_hash"])
    has_source_page = bool(source_page["source_page_path"])
    raw_file = vault / raw_rel if raw_rel else None
    raw_exists = raw_file is not None and raw_file.exists()

    if registry_status == "published" and has_source_page:
        # Check if raw source has changed since last ingest
        published_source_hash = row.get("raw_hash") or artifact["manifest_source_hash"]
        if raw_exists and published_source_hash:
            current_hash = _hash(raw_file)
            if current_hash != published_source_hash:
                plan_item["state"] = "stale"
                plan_item["reason"] = "raw source hash changed since last published ingest"
                plan_item["recommended_action"] = "re-parse and re-ingest"
                plan_item["freshness_verdict"] = "stale"
                return plan_item
        plan_item["state"] = "published"
        plan_item["reason"] = "source already published and unchanged"
        plan_item["recommended_action"] = "skip"
        plan_item["freshness_verdict"] = "fresh"
        return plan_item

    if registry_status == "failed":
        plan_item["state"] = "failed"
        plan_item["reason"] = row.get("last_error", "previous ingest failed")
        plan_item["recommended_action"] = "retry after fixing the error"
        plan_item["freshness_verdict"] = "failed"
        return plan_item

    if row.get("duplicate_of"):
        plan_item["state"] = "cached"
        plan_item["reason"] = f"duplicate of {row['duplicate_of']}"
        plan_item["recommended_action"] = "skip"
        plan_item["freshness_verdict"] = "duplicate"
        return plan_item

    if registry_status == "archived":
        plan_item["state"] = "cached"
        plan_item["reason"] = "source archived"
        plan_item["recommended_action"] = "skip"
        plan_item["freshness_verdict"] = "archived"
        return plan_item

    # Check staleness: artifact exists but source hash changed
    artifact_source_hash = row.get("raw_hash") or artifact["manifest_source_hash"]
    if has_artifact and raw_exists and artifact_source_hash:
        current_hash = _hash(raw_file)
        if current_hash != artifact_source_hash:
            plan_item["state"] = "stale"
            plan_item["reason"] = "raw source changed since artifact was parsed"
            plan_item["recommended_action"] = "re-parse the updated source"
            plan_item["freshness_verdict"] = "stale"
            return plan_item

    if has_artifact:
        plan_item["state"] = "ready"
        plan_item["reason"] = "parsed artifact exists and is fresh"
        plan_item["recommended_action"] = "ingest"
        plan_item["freshness_verdict"] = "fresh"
        return plan_item

    # No artifact yet
    if raw_rel in combined_files:
        plan_item["state"] = "stageable"
        plan_item["reason"] = "combined.md available for staging"
        plan_item["recommended_action"] = "ingest via combined.md"
        plan_item["freshness_verdict"] = "fresh"
        return plan_item

    # Check for other parseable formats
    if raw_file and raw_file.exists():
        suffix = raw_file.suffix.lower()
        if suffix in (".md", ".txt"):
            plan_item["state"] = "stageable"
            plan_item["reason"] = "local text/markdown file available for staging"
            plan_item["recommended_action"] = "ingest directly"
            plan_item["freshness_verdict"] = "fresh"
            return plan_item
        if suffix in ARCHIVE_SUFFIXES:
            plan_item["state"] = "blocked"
            plan_item["reason"] = "archive source must be extracted before contained evidence can be planned"
            plan_item["recommended_action"] = "extract archive into raw/ or raw/<corpus>/, then rerun ingest plan"
            plan_item["freshness_verdict"] = "archive"
            return plan_item

    plan_item["state"] = "blocked"
    plan_item["reason"] = "no parseable artifact and no text source available"
    plan_item["recommended_action"] = "run parser first"
    plan_item["freshness_verdict"] = "missing"
    return plan_item


def build_plan(vault: Path) -> dict[str, Any]:
    vault = vault.resolve()
    registry_path = vault / "_state" / "source-registry.jsonl"
    rows = [
        row for row in load_registry(registry_path)
        if not is_auxiliary_raw_source_path(row.get("raw_path") or row.get("path", ""))
    ]

    combined_files = _combined_files_by_raw(vault)

    # If registry is empty, scan raw/ for candidates
    if not rows:
        for path in _raw_source_files(vault):
            raw_rel = path.relative_to(vault).as_posix()
            h = ""
            try:
                h = raw_hash(path)
            except OSError:
                pass
            rows.append({
                "source_uuid": "",
                "source_id": "",
                "raw_path": raw_rel,
                "raw_hash": h,
                "status": "candidate",
                "kind": "raw",
            })

    plan_items = []
    for row in rows:
        if row.get("duplicate_of"):
            continue
        raw_rel = row.get("raw_path", "") or row.get("path", "")
        if raw_rel and is_auxiliary_raw_source_path(raw_rel):
            continue
        item = classify_source(vault, row, combined_files)
        plan_items.append(item)

    state_counts = {}
    for item in plan_items:
        state = item.get("state", "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1

    return {
        "version": PLAN_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "vault": str(vault),
        "total_sources": len(plan_items),
        "state_counts": state_counts,
        "items": plan_items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a runtime-owned ingest plan from vault state.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Desktop clients should read _state/ingest-plan.json instead of\n"
            "maintaining their own desktop-ingest-plan.json or registry.\n"
            "The runtime owns all plan and registry state.\n"
            "\n"
            "Plan states:\n"
            "  ready      - parsed artifact exists and is fresh\n"
            "  stageable  - Markdown/txt available for local staging\n"
            "  blocked    - needs parser or unsupported format\n"
            "  cached     - source/artifact unchanged, safe to skip\n"
            "  published  - already published, no re-ingest needed\n"
            "  failed     - previous ingest failed, needs retry\n"
            "  stale      - source hash changed, old artifact stale\n"
        ),
    )
    parser.add_argument("vault", type=Path)
    parser.add_argument("--write", action="store_true", help="Write plan to _state/ingest-plan.json")
    parser.add_argument("--format", choices=["json", "summary"], default="summary")
    args = parser.parse_args()

    vault = args.vault.resolve()
    plan = build_plan(vault)

    if args.format == "json":
        output = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        lines = [
            "# Ingest Plan",
            f"- vault: {vault}",
            f"- generated: {plan['generated_at']}",
            f"- total: {plan['total_sources']}",
            "",
            "## State Summary",
        ]
        for state, count in sorted(plan["state_counts"].items()):
            lines.append(f"- {state}: {count}")
        lines.append("")
        lines.append("## Items")
        for item in plan["items"]:
            lines.append(f"- [{item['state']}] {item['source_path']}: {item['reason']}")
        output = "\n".join(lines) + "\n"

    if args.write:
        plan_path = ensure_within(
            vault / "_state" / "ingest-plan.json",
            vault,
            "plan output must stay inside the vault",
        )
        write_text(plan_path, json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print(f"plan written to {plan_path}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
