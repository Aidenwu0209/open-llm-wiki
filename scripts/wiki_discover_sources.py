#!/usr/bin/env python3
"""Discover, fingerprint, and deduplicate source candidates for a wiki vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, json_dump, parse_frontmatter, read_text, write_text
from wiki_raw_support import is_auxiliary_raw_source_path
from wiki_source_registry import (
    allocate_source_id,
    load_registry,
    raw_hash as compute_raw_hash,
    save_registry,
    source_uuid_from_id,
)


ARXIV_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
IGNORED_RAW_DIRS = frozenset({"__MACOSX", "inbox"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm_title(text: str) -> str:
    text = re.sub(r"[_\-]+", " ", text.lower())
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_generic_title_candidate(text: str) -> bool:
    key = norm_title(text)
    return (
        not key
        or bool(re.fullmatch(r"page \d+", key))
        or key in {"abstract", "introduction", "references", "contents", "keywords"}
    )


def ids_from_text(text: str) -> tuple[str, str]:
    arxiv = ARXIV_RE.search(text)
    doi = DOI_RE.search(text)
    return (arxiv.group(1) if arxiv else "", doi.group(0).lower() if doi else "")


def parsed_text_for_raw(vault: Path, path: Path) -> str:
    candidates = [
        path.parent / f"{path.stem}_markdown" / "combined.md",
        vault / "raw" / f"{path.stem}_markdown" / "combined.md",
        path.with_suffix(".md"),
        path.with_suffix(".txt"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return read_text(candidate)[:20000]
    return ""


def is_ignored_raw_path(raw_dir: Path, path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        parts = path.relative_to(raw_dir).parts[:-1]
    except ValueError:
        return True
    return any(part.startswith(".") or part.endswith("_markdown") or part in IGNORED_RAW_DIRS for part in parts)


def title_from_markdown(text: str) -> str:
    first_text_line = ""
    for line in text.splitlines()[:80]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if len(title) > 4 and not is_generic_title_candidate(title):
                return title
            continue
        if (
            not first_text_line
            and len(stripped) > 4
            and not is_generic_title_candidate(stripped)
            and not stripped.startswith(("http://", "https://"))
        ):
            first_text_line = stripped
    if first_text_line:
        return first_text_line
    return ""


def registry_from_raw(vault: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    raw_dir = vault / "raw"
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or is_ignored_raw_path(raw_dir, path) or is_auxiliary_raw_source_path(path):
            continue
        parsed_text = parsed_text_for_raw(vault, path)
        arxiv, doi = ids_from_text(f"{path.name}\n{parsed_text}")
        title = title_from_markdown(parsed_text) or path.stem
        rows.append(
            {
                "kind": "raw",
                "path": path.relative_to(vault).as_posix(),
                "title": title,
                "title_key": norm_title(title),
                "arxiv": arxiv,
                "doi": doi,
                "sha256": sha256(path),
                "raw_hash": compute_raw_hash(path) if path.is_file() else "",
                "status": "candidate",
            }
        )
    return rows


def registry_from_sources(vault: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((vault / "sources").glob("LLM-*.md")):
        fields, body = parse_frontmatter(path)
        hay = " ".join([path.name, fields.get("title", ""), fields.get("source", ""), body[:2000]])
        arxiv, doi = ids_from_text(hay)
        rows.append(
            {
                "kind": "source",
                "path": path.relative_to(vault).as_posix(),
                "source_id": fields.get("id", path.stem),
                "title": fields.get("title", path.stem),
                "title_key": norm_title(fields.get("title", path.stem)),
                "arxiv": arxiv,
                "doi": doi,
                "sha256": "",
                "raw_hash": "",
                "status": "published",
            }
        )
    return rows


def fetch_arxiv(query: str, max_results: int) -> list[dict[str, object]]:
    params = urllib.parse.urlencode({"search_query": query, "start": 0, "max_results": max_results})
    url = f"https://export.arxiv.org/api/query?{params}"
    data = urllib.request.urlopen(url, timeout=30).read().decode("utf-8", errors="replace")
    entries = re.findall(r"<entry>(.*?)</entry>", data, flags=re.DOTALL)
    rows: list[dict[str, object]] = []
    for entry in entries:
        title_match = re.search(r"<title>(.*?)</title>", entry, flags=re.DOTALL)
        id_match = re.search(r"<id>https?://arxiv.org/abs/([^<]+)</id>", entry)
        published = re.search(r"<published>(.*?)</published>", entry)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else "Untitled"
        arxiv = id_match.group(1).split("v", 1)[0] if id_match else ""
        rows.append(
            {
                "kind": "arxiv",
                "path": f"https://arxiv.org/abs/{arxiv}" if arxiv else "",
                "title": title,
                "title_key": norm_title(title),
                "arxiv": arxiv,
                "doi": "",
                "sha256": "",
                "published": published.group(1) if published else "",
                "status": "discovered",
            }
        )
    return rows


def duplicate_groups(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups = []
    for key_name in ["arxiv", "doi", "sha256", "title_key"]:
        buckets: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            key = str(row.get(key_name, ""))
            if not key:
                continue
            buckets.setdefault(key, []).append(row)
        for key, items in sorted(buckets.items()):
            if len(items) > 1:
                groups.append(
                    {
                        "key_type": key_name,
                        "key": key,
                        "items": [str(item.get("path", "")) for item in items],
                    }
                )
    return groups


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def ensure_discovery_identity(row: dict[str, object], state_dir: Path) -> None:
    if not row.get("source_id") and row.get("status") != "discovered":
        source_id = allocate_source_id(state_dir)
        row["source_id"] = source_id
        row["source_uuid"] = source_uuid_from_id(source_id)
    elif row.get("source_id") and not row.get("source_uuid"):
        row["source_uuid"] = source_uuid_from_id(str(row["source_id"]))


def report(rows: list[dict[str, object]], duplicates: list[dict[str, object]]) -> str:
    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[str(row.get("kind", ""))] = by_kind.get(str(row.get("kind", "")), 0) + 1
    kind_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(by_kind.items())) or "- none"
    duplicate_lines = "\n".join(
        f"- {item['key_type']} `{item['key']}`: {', '.join(item['items'])}" for item in duplicates
    ) or "- none"
    return (
        "# Source Discovery Report\n"
        f"- date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- candidates: {len(rows)}\n"
        f"- duplicate_groups: {len(duplicates)}\n\n"
        "## By Kind\n\n"
        f"{kind_lines}\n\n"
        "## Duplicate Groups\n\n"
        f"{duplicate_lines}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and deduplicate wiki source candidates.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--arxiv-query", help="Optional arXiv API query, for example cat:cs.CL AND deepseek.")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--registry", type=Path, help="Defaults to <vault>/_state/source-registry.jsonl.")
    parser.add_argument("--report", type=Path, help="Defaults to <vault>/_state/source-discovery-report.md.")
    parser.add_argument("--fail-on-duplicates", action="store_true")
    parser.add_argument("--format", choices=["summary", "json"], default="summary")
    args = parser.parse_args()

    vault = args.vault.resolve()
    registry = ensure_within(args.registry or vault / "_state" / "source-registry.jsonl", vault, "discovery outputs must stay inside the vault")
    report_path = ensure_within(args.report or vault / "_state" / "source-discovery-report.md", vault, "discovery outputs must stay inside the vault")
    state_dir = ensure_within(vault / "_state", vault, "state directory must stay inside the vault")

    existing_rows = [
        row for row in load_registry(registry)
        if not is_auxiliary_raw_source_path(row.get("raw_path") or row.get("path", ""))
    ]
    existing_by_path = {}
    existing_by_source_id = {}
    for row in existing_rows:
        p = row.get("raw_path") or row.get("path", "")
        if p:
            existing_by_path[p] = row
        sid = row.get("source_id", "")
        if sid:
            existing_by_source_id[sid] = row

    fresh_rows = registry_from_raw(vault) + registry_from_sources(vault)
    if args.arxiv_query:
        fresh_rows.extend(fetch_arxiv(args.arxiv_query, args.max_results))

    merged = list(existing_rows)
    merged_paths = {row.get("raw_path") or row.get("path", "") for row in merged}
    merged_source_ids = {row.get("source_id", "") for row in merged if row.get("source_id")}
    for fresh in fresh_rows:
        fp = fresh.get("path", "")
        fresh_sid = fresh.get("source_id", "")
        if fp in existing_by_path:
            existing = existing_by_path[fp]
            for key in ("title", "title_key", "arxiv", "doi"):
                if key in fresh:
                    existing[key] = fresh[key]
            for key in ("sha256", "raw_hash"):
                if key in fresh and (existing.get("status") not in {"published", "stale"} or not existing.get(key)):
                    existing[key] = fresh[key]
            ensure_discovery_identity(existing, state_dir)
        elif fresh_sid and fresh_sid in existing_by_source_id:
            existing = existing_by_source_id[fresh_sid]
            for key in ("title", "title_key", "arxiv", "doi", "status"):
                if key in fresh:
                    existing[key] = fresh[key]
            for key in ("sha256", "raw_hash"):
                if fresh.get(key) and (existing.get("status") not in {"published", "stale"} or not existing.get(key)):
                    existing[key] = fresh[key]
            ensure_discovery_identity(existing, state_dir)
        elif fp not in merged_paths and fresh_sid not in merged_source_ids:
            ensure_discovery_identity(fresh, state_dir)
            fresh_sid = fresh.get("source_id", "")
            if "raw_path" not in fresh:
                fresh["raw_path"] = fp
            merged.append(fresh)
            merged_paths.add(fp)
            if fresh_sid:
                merged_source_ids.add(fresh_sid)

    duplicates = duplicate_groups(merged)
    save_registry(registry, merged)
    write_text(report_path, report(merged, duplicates))
    if args.format == "json":
        print(json_dump({"candidates": len(merged), "duplicates": duplicates, "registry": str(registry)}))
    else:
        print(f"candidates: {len(merged)}")
        print(f"duplicates: {len(duplicates)}")
        print(f"registry: {registry}")
        print(f"report: {report_path}")
    return 1 if args.fail_on_duplicates and duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())
