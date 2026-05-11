#!/usr/bin/env python3
"""Generate an explicit ingest plan from raw/inbox, raw artifacts, and existing sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_common import (
    SOURCE_ID_RE,
    ensure_within,
    json_dump,
    parse_frontmatter,
    read_text,
    rel,
    source_id_from_path,
    write_text,
)


VALID_PLAN_STATES = frozenset({
    "ready", "stageable", "blocked", "cached", "failed", "published", "stale",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def read_id_counter(vault: Path) -> int:
    path = vault / "_state" / "id-counter.md"
    if not path.exists():
        return 1
    for line in read_text(path).splitlines():
        if line.startswith("next:"):
            try:
                return int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                return 1
    return 1


def write_id_counter(vault: Path, value: int) -> None:
    path = vault / "_state" / "id-counter.md"
    write_text(path, f"next: {value}\n")


def allocate_id(vault: Path) -> str:
    counter = read_id_counter(vault)
    source_id = f"LLM-{counter:04d}"
    write_id_counter(vault, counter + 1)
    return source_id


def scan_inbox(vault: Path) -> list[dict[str, Any]]:
    inbox = vault / "raw" / "inbox"
    if not inbox.exists():
        return []
    candidates = []
    for path in sorted(inbox.iterdir()):
        if path.name.startswith(".") or path.is_dir():
            continue
        candidates.append({
            "path": rel(path, vault),
            "filename": path.name,
            "sha256": sha256_file(path),
            "source": "inbox",
        })
    return candidates


def scan_raw_artifacts(vault: Path) -> list[dict[str, Any]]:
    raw = vault / "raw"
    if not raw.exists():
        return []
    candidates = []
    for combined in sorted(raw.glob("*_markdown/combined.md")):
        parent = combined.parent
        stem = parent.name.removesuffix("_markdown")
        source_path = raw / f"{stem}.pdf"
        source_rel = rel(source_path, vault) if source_path.exists() else ""
        artifact_rel = rel(combined, vault)
        manifest_path = parent / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(read_text(manifest_path))
            except json.JSONDecodeError:
                pass
        if not source_rel and isinstance(manifest.get("source_path"), str):
            source_rel = str(manifest.get("source_path", ""))
            source_path = vault / source_rel
        source_hash = sha256_file(source_path) if source_rel and source_path.exists() else ""
        candidates.append({
            "path": source_rel or artifact_rel,
            "filename": source_path.name if source_rel else combined.name,
            "sha256": source_hash,
            "artifact_path": artifact_rel,
            "artifact_sha256": sha256_file(combined),
            "manifest_path": rel(manifest_path, vault) if manifest_path.exists() else "",
            "has_manifest": bool(manifest),
            "source": "raw_source" if source_rel else "raw_artifact",
            "text_hash": sha256_text(read_text(combined)),
        })
    return candidates


def scan_existing_sources(vault: Path) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for path in sorted((vault / "sources").glob("LLM-*.md")):
        source_id = source_id_from_path(path) or path.stem
        fields, body = parse_frontmatter(path)
        sources[source_id] = {
            "source_id": source_id,
            "path": rel(path, vault),
            "status": fields.get("status", "unknown"),
            "title": fields.get("title", ""),
            "updated": fields.get("updated", ""),
            "body_hash": sha256_text(body),
        }
    return sources


def scan_drafts(vault: Path) -> dict[str, dict[str, Any]]:
    drafts: dict[str, dict[str, Any]] = {}
    for path in sorted((vault / "drafts").glob("*.md")):
        source_id = source_id_from_path(path) or path.stem
        fields, body = parse_frontmatter(path)
        drafts[source_id] = {
            "source_id": source_id,
            "path": rel(path, vault),
            "status": fields.get("status", "draft"),
            "title": fields.get("title", ""),
            "body_hash": sha256_text(body),
        }
    return drafts


def scan_registry(vault: Path) -> dict[str, dict[str, Any]]:
    registry = load_jsonl(vault / "_state" / "source-registry.jsonl")
    by_sha: dict[str, dict[str, Any]] = {}
    for row in registry:
        sha = str(row.get("sha256", ""))
        if sha:
            by_sha[sha] = row
    return by_sha


def build_plan(vault: Path) -> list[dict[str, Any]]:
    vault = vault.resolve()
    inbox_candidates = scan_inbox(vault)
    raw_artifacts = scan_raw_artifacts(vault)
    existing_sources = scan_existing_sources(vault)
    existing_drafts = scan_drafts(vault)
    registry_by_sha = scan_registry(vault)

    all_candidates = inbox_candidates + raw_artifacts
    existing_hashes = {s["body_hash"] for s in existing_sources.values()}
    existing_hashes.update(d["body_hash"] for d in existing_drafts.values())

    plan: list[dict[str, Any]] = []
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for candidate in all_candidates:
        sha = candidate.get("sha256", "")
        text_hash = candidate.get("text_hash", "")
        registry_row = registry_by_sha.get(sha, {})
        existing_source_id = str(registry_row.get("source_id", ""))
        plan_state = "ready"
        reason = ""

        if existing_source_id and existing_source_id in existing_sources:
            plan_state = "cached"
            reason = f"source already published as {existing_source_id}"
        elif existing_source_id and existing_source_id in existing_drafts:
            plan_state = "stageable"
            reason = f"draft exists as {existing_source_id}, needs QA"
        elif text_hash and text_hash in existing_hashes:
            plan_state = "cached"
            reason = "content hash matches existing source or draft"
        elif candidate.get("source") == "inbox" and not candidate.get("has_manifest"):
            plan_state = "ready"
            reason = "inbox file needs parsing before drafting"

        plan.append({
            "candidate_path": candidate.get("path", ""),
            "candidate_source": candidate.get("source", ""),
            "candidate_sha256": sha,
            "artifact_path": candidate.get("artifact_path", ""),
            "artifact_sha256": candidate.get("artifact_sha256", ""),
            "text_hash": text_hash,
            "has_manifest": candidate.get("has_manifest", False),
            "manifest_path": candidate.get("manifest_path", ""),
            "plan_state": plan_state,
            "source_id": existing_source_id,
            "reason": reason,
            "created_at": now,
        })

    for source_id, info in sorted(existing_sources.items()):
        if info["status"] == "stable":
            plan.append({
                "candidate_path": info["path"],
                "candidate_source": "published",
                "candidate_sha256": "",
                "artifact_path": "",
                "artifact_sha256": "",
                "text_hash": info["body_hash"],
                "has_manifest": False,
                "manifest_path": "",
                "plan_state": "published",
                "source_id": source_id,
                "reason": f"stable source {source_id}",
                "created_at": now,
            })
        else:
            plan.append({
                "candidate_path": info["path"],
                "candidate_source": "published",
                "candidate_sha256": "",
                "artifact_path": "",
                "artifact_sha256": "",
                "text_hash": info["body_hash"],
                "has_manifest": False,
                "manifest_path": "",
                "plan_state": "stale",
                "source_id": source_id,
                "reason": f"source {source_id} has non-stable status: {info['status']}",
                "created_at": now,
            })

    return plan


def render_plan(plan: list[dict[str, Any]], vault: Path) -> str:
    by_state: dict[str, list[dict[str, Any]]] = {}
    for item in plan:
        state = item.get("plan_state", "unknown")
        by_state.setdefault(state, []).append(item)

    lines = [
        "# Ingest Plan",
        f"- vault: {vault}",
        f"- generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- candidates: {len(plan)}",
        "",
    ]
    for state in sorted(by_state):
        items = by_state[state]
        lines.append(f"## {state} ({len(items)})")
        lines.append("")
        for item in items:
            path = item.get("candidate_path", "")
            sid = item.get("source_id", "")
            reason = item.get("reason", "")
            manifest = "manifest" if item.get("has_manifest") else "no manifest"
            label = f"`{path}`"
            if sid:
                label += f" -> {sid}"
            lines.append(f"- [{state.upper()}] {label} ({manifest}) — {reason}")
        lines.append("")

    lines.append("## Plan States")
    lines.append("")
    lines.append("| State | Meaning |")
    lines.append("| --- | --- |")
    lines.append("| `ready` | Raw source or inbox file ready for parse and draft |")
    lines.append("| `stageable` | Draft exists; needs QA before publishing |")
    lines.append("| `blocked` | Missing dependency (e.g. no parsed text) |")
    lines.append("| `cached` | Content hash matches existing source; will skip unless forced |")
    lines.append("| `failed` | Previous ingest attempt failed |")
    lines.append("| `published` | Source is stable and published |")
    lines.append("| `stale` | Source exists but has non-stable status |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ingest plan from raw/inbox, artifacts, and existing sources.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--write", action="store_true", help="Write plan to _state/ingest-plan.jsonl")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    vault = args.vault.resolve()
    plan = build_plan(vault)

    if args.write:
        plan_path = ensure_within(
            vault / "_state" / "ingest-plan.jsonl",
            vault / "_state",
            "ingest plan must stay under _state/",
        )
        text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in plan)
        write_text(plan_path, text)
        json_path = ensure_within(
            vault / "_state" / "ingest-plan.json",
            vault / "_state",
            "ingest plan must stay under _state/",
        )
        write_text(json_path, json.dumps({"vault": str(vault), "plan": plan}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    if args.format == "json":
        print(json_dump({"vault": str(vault), "plan": plan}))
    else:
        print(render_plan(plan, vault))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
