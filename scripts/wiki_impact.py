#!/usr/bin/env python3
"""Change Impact Graph: track source/chunk/claim/concept staleness and propagation.

Builds and queries ``_state/impact-graph.jsonl`` and
``_state/stale-queue.jsonl`` to determine which downstream artefacts
are affected when an upstream item changes.

Usage::

    python wiki_impact.py <vault>                    # build/rebuild graph
    python wiki_impact.py <vault> --source LLM-0001  # trace impact for one source
    python wiki_impact.py <vault> --stale            # list stale items
    python wiki_impact.py <vault> --stale --write-queue  # write stale queue
    python wiki_impact.py <vault> --format json       # machine-readable output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, read_text, write_text

# ---------------------------------------------------------------------------
# Edge types (relationship values)
# ---------------------------------------------------------------------------

EDGE_TYPES = {
    "raw_source_to_parse_artifact",
    "parse_artifact_to_chunk",
    "chunk_to_claim",
    "claim_to_source_page_section",
    "claim_to_concept_section",
    "claim_to_contradiction_group",
    "concept_to_dashboard_card",  # placeholder for #73
    "concept_to_review_queue_item",
}

# ---------------------------------------------------------------------------
# Stale queue statuses
# ---------------------------------------------------------------------------

STALE_STATUSES = {"stale", "refreshed", "ignored", "review"}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(*parts: str) -> str:
    h = hashlib.sha1("\0".join(parts).encode()).hexdigest()[:12]
    return f"edge-{h}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    write_text(path, text)


def _artifact_path_from_source_body(body: str) -> str:
    import re
    patterns = [
        r"^- parsed markdown:\s+([^\s#]+(?:#\S+)?)\s*$",
        r"\b(raw/[^\s)]+_markdown/combined\.md)(?:#\S+)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.MULTILINE)
        if match:
            return match.group(1).split("#", 1)[0]
    return ""


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_edges(vault: Path) -> list[dict[str, Any]]:
    vault = vault.resolve()
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    now = _now()

    def _add_edge(from_type: str, from_id: str, to_type: str, to_id: str,
                  relationship: str, from_hash: str = "", to_hash: str = "") -> None:
        edge_id = _stable_id(from_type, from_id, to_type, to_id, relationship)
        if edge_id in seen:
            return
        seen.add(edge_id)
        edges.append({
            "edge_id": edge_id,
            "from_type": from_type,
            "from_id": from_id,
            "to_type": to_type,
            "to_id": to_id,
            "relationship": relationship,
            "from_hash": from_hash,
            "to_hash": to_hash,
            "created_at": now,
            "updated_at": now,
        })

    # --- raw_source -> parse_artifact ---
    raw_dir = vault / "raw"
    if raw_dir.exists():
        for combined in sorted(raw_dir.glob("*_markdown/combined.md")):
            stem = combined.parent.name.removesuffix("_markdown")
            raw_pdf = raw_dir / f"{stem}.pdf"
            raw_hash = _hash_file(raw_pdf) if raw_pdf.exists() else ""
            art_hash = _hash_file(combined)
            _add_edge("raw_source", stem, "parse_artifact", combined.relative_to(vault).as_posix(),
                      "raw_source_to_parse_artifact", raw_hash, art_hash)

    # --- parse_artifact -> chunk (source page as chunk proxy) ---
    # In this vault model each source page IS the primary chunk
    for source_path in sorted((vault / "sources").glob("LLM-*.md")):
        source_id = source_path.stem
        source_hash = _hash_file(source_path)
        body = ""
        try:
            from wiki_common import parse_frontmatter
            _fields, body = parse_frontmatter(source_path)
        except Exception:
            pass
        artifact_rel = _artifact_path_from_source_body(body)
        if artifact_rel:
            _add_edge("parse_artifact", artifact_rel, "chunk", source_id,
                      "parse_artifact_to_chunk", "", source_hash)

    # --- chunk -> claim ---
    claims_path = vault / "claims" / "claims.jsonl"
    if claims_path.exists():
        claims = _load_jsonl(claims_path)
        for claim in claims:
            claim_id = claim.get("claim_id", "")
            source_id = claim.get("source_id", "")
            if claim_id and source_id:
                _add_edge("chunk", source_id, "claim", claim_id,
                          "chunk_to_claim", "", "")

    # --- claim -> source_page_section ---
    for claim in _load_jsonl(claims_path) if claims_path.exists() else []:
        claim_id = claim.get("claim_id", "")
        evidence = str(claim.get("evidence", ""))
        if claim_id and evidence:
            _add_edge("claim", claim_id, "source_page_section", evidence,
                      "claim_to_source_page_section", "", "")

    # --- claim -> concept_section ---
    for claim in _load_jsonl(claims_path) if claims_path.exists() else []:
        claim_id = claim.get("claim_id", "")
        for concept in claim.get("concepts", []):
            if claim_id and concept:
                _add_edge("claim", claim_id, "concept_section", f"{concept}",
                          "claim_to_concept_section", "", "")

    # --- claim -> contradiction_group ---
    contra_path = vault / "qa-reports"
    if contra_path.exists():
        for report in sorted(contra_path.glob("*contradiction*.md")):
            report_text = read_text(report)
            # Extract source ids from contradiction reports
            for line in report_text.splitlines():
                line = line.strip()
                if line.startswith("- ") and "[[" in line:
                    import re
                    for m in re.finditer(r"\[\[([A-Za-z0-9_-]+)\]\]", line):
                        target_id = m.group(1)
                        if target_id.startswith("claim-"):
                            report_id = report.stem
                            _add_edge("claim", target_id, "contradiction_group", report_id,
                                      "claim_to_contradiction_group", "", "")

    # --- concept -> review_queue_item ---
    srq_path = vault / "_state" / "science-review-queue.jsonl"
    if srq_path.exists():
        for row in _load_jsonl(srq_path):
            review_id = row.get("review_id", "")
            claim_id = row.get("claim_id", "")
            if review_id and claim_id:
                # Find concept from claims
                for claim in _load_jsonl(claims_path) if claims_path.exists() else []:
                    if claim.get("claim_id") == claim_id:
                        for concept in claim.get("concepts", []):
                            _add_edge("concept", concept, "review_queue_item", review_id,
                                      "concept_to_review_queue_item", "", "")

    return edges


# ---------------------------------------------------------------------------
# Impact tracing
# ---------------------------------------------------------------------------

def trace_downstream(edges: list[dict[str, Any]], from_type: str, from_id: str,
                     max_depth: int = 10) -> list[dict[str, Any]]:
    """BFS trace downstream impact from a given node."""
    adjacency: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        key = (edge["from_type"], edge["from_id"])
        adjacency[key].append(edge)

    visited: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    queue: list[tuple[str, str, int]] = [(from_type, from_id, 0)]

    while queue:
        ftype, fid, depth = queue.pop(0)
        if depth > max_depth:
            continue
        key = (ftype, fid)
        if key in visited:
            continue
        visited.add(key)

        for edge in adjacency.get(key, []):
            result.append(edge)
            child_key = (edge["to_type"], edge["to_id"])
            if child_key not in visited:
                queue.append((edge["to_type"], edge["to_id"], depth + 1))

    return result


def find_affected_concepts(edges: list[dict[str, Any]], source_id: str) -> set[str]:
    """Find all concepts affected by changes to a source."""
    downstream = trace_downstream(edges, "chunk", source_id)
    concepts: set[str] = set()
    for edge in downstream:
        if edge["to_type"] == "concept_section" and edge["relationship"] == "claim_to_concept_section":
            concepts.add(edge["to_id"])
        if edge["from_type"] == "concept" and edge["relationship"] == "concept_to_review_queue_item":
            concepts.add(edge["from_id"])
    return concepts


# ---------------------------------------------------------------------------
# Stale propagation
# ---------------------------------------------------------------------------

def compute_stale_items(vault: Path, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute stale items by comparing current hashes with edge hashes."""
    vault = vault.resolve()
    stale: list[dict[str, Any]] = []
    now = _now()
    seen_ids: set[str] = set()

    def _add_stale(item_type: str, item_id: str, reason: str, upstream: str) -> None:
        key = f"{item_type}\0{item_id}"
        stale_id = f"stale-{hashlib.sha1(key.encode()).hexdigest()[:12]}"
        if stale_id in seen_ids:
            return
        seen_ids.add(stale_id)
        stale.append({
            "item_id": stale_id,
            "item_type": item_type,
            "item_ref": item_id,
            "reason": reason,
            "upstream": upstream,
            "status": "stale",
            "created_at": now,
            "updated_at": now,
        })

    # Rule 1: raw_source hash change -> artifact, chunks, claims stale
    raw_dir = vault / "raw"
    if raw_dir.exists():
        for edge in edges:
            if edge["relationship"] == "raw_source_to_parse_artifact":
                from_id = edge["from_id"]
                raw_pdf = raw_dir / f"{from_id}.pdf"
                if raw_pdf.exists() and edge["from_hash"]:
                    current = _hash_file(raw_pdf)
                    if current != edge["from_hash"]:
                        _add_stale("raw_source", from_id, "raw hash changed", from_id)
                        # Propagate downstream
                        downstream = trace_downstream(edges, "raw_source", from_id)
                        for d in downstream:
                            _add_stale(d["to_type"], d["to_id"],
                                      f"upstream raw_source {from_id} changed", from_id)

    # Rule 2: artifact hash change -> chunks, claims stale
    for edge in edges:
        if edge["relationship"] == "raw_source_to_parse_artifact":
            art_path = vault / edge["to_id"]
            if art_path.exists() and edge["to_hash"]:
                current = _hash_file(art_path)
                if current != edge["to_hash"]:
                    _add_stale("parse_artifact", edge["to_id"], "artifact hash changed", edge["to_id"])
                    downstream = trace_downstream(edges, "parse_artifact", edge["to_id"])
                    for d in downstream:
                        _add_stale(d["to_type"], d["to_id"],
                                  f"upstream artifact {edge['to_id']} changed", edge["to_id"])

    # Rule 3: source page hash change -> claims stale
    for source_path in sorted((vault / "sources").glob("LLM-*.md")):
        source_id = source_path.stem
        for edge in edges:
            if edge["relationship"] == "parse_artifact_to_chunk" and edge["to_id"] == source_id:
                current = _hash_file(source_path)
                if edge["to_hash"] and current != edge["to_hash"]:
                    _add_stale("chunk", source_id, "source page hash changed", source_id)
                    downstream = trace_downstream(edges, "chunk", source_id)
                    for d in downstream:
                        _add_stale(d["to_type"], d["to_id"],
                                  f"upstream source page {source_id} changed", source_id)

    # Rule 4: concept sections affected by stale claims
    claims_by_concept: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["relationship"] == "claim_to_concept_section":
            claims_by_concept[edge["to_id"]].append(edge["from_id"])

    stale_claim_ids = {s["item_ref"] for s in stale if s["item_type"] == "claim"}
    for concept, claim_ids in claims_by_concept.items():
        if any(cid in stale_claim_ids for cid in claim_ids):
            _add_stale("concept_section", concept,
                      "claim stale, concept section needs refresh",
                      ", ".join(cid for cid in claim_ids if cid in stale_claim_ids))

    return stale


def load_stale_queue(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path)


def save_stale_queue(path: Path, items: list[dict[str, Any]]) -> None:
    _save_jsonl(path, items)


def mark_stale_item(queue: list[dict[str, Any]], item_id: str, status: str) -> bool:
    for item in queue:
        if item["item_id"] == item_id:
            item["status"] = status
            item["updated_at"] = _now()
            return True
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and query the change impact graph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Edge types:\n"
            "  raw_source_to_parse_artifact\n"
            "  parse_artifact_to_chunk\n"
            "  chunk_to_claim\n"
            "  claim_to_source_page_section\n"
            "  claim_to_concept_section\n"
            "  claim_to_contradiction_group\n"
            "  concept_to_dashboard_card  (placeholder for #73)\n"
            "  concept_to_review_queue_item\n"
            "\n"
            "Propagation rules:\n"
            "  raw_source hash change   -> artifact, chunks, claims stale\n"
            "  artifact hash change     -> chunks, claims stale\n"
            "  source page hash change  -> claims stale\n"
            "  claim stale              -> concept sections stale\n"
        ),
    )
    parser.add_argument("vault", type=Path)
    parser.add_argument("--source", help="Trace impact for a specific source (e.g. LLM-0001)")
    parser.add_argument("--stale", action="store_true", help="List stale items")
    parser.add_argument("--write-queue", action="store_true", help="Write stale queue to _state/stale-queue.jsonl")
    parser.add_argument("--mark-refreshed", help="Mark a stale queue item as refreshed by item_id")
    parser.add_argument("--mark-ignored", help="Mark a stale queue item as ignored by item_id")
    parser.add_argument("--build", action="store_true", help="Build/rebuild the impact graph")
    parser.add_argument("--format", choices=["json", "summary"], default="summary")
    args = parser.parse_args()

    vault = args.vault.resolve()
    state_dir = vault / "_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    graph_path = ensure_within(state_dir / "impact-graph.jsonl", state_dir,
                               "impact graph must stay under _state/")
    queue_path = ensure_within(state_dir / "stale-queue.jsonl", state_dir,
                               "stale queue must stay under _state/")

    # Build graph if requested or if graph doesn't exist yet
    if args.build or not graph_path.exists():
        edges = build_edges(vault)
        _save_jsonl(graph_path, edges)
        if not args.source and not args.stale and args.format == "summary":
            print(f"impact graph built: {len(edges)} edges")

    edges = _load_jsonl(graph_path)

    # Handle mark operations
    if args.mark_refreshed or args.mark_ignored:
        queue = load_stale_queue(queue_path)
        changed = False
        if args.mark_refreshed:
            changed = mark_stale_item(queue, args.mark_refreshed, "refreshed")
        if args.mark_ignored:
            changed = mark_stale_item(queue, args.mark_ignored, "ignored") or changed
        if changed:
            save_stale_queue(queue_path, queue)
            print(f"updated stale queue: {queue_path}")
        else:
            print("no matching stale item found")
        return 0

    # Trace source impact
    if args.source:
        source_id = args.source
        downstream = trace_downstream(edges, "chunk", source_id)
        concepts = find_affected_concepts(edges, source_id)

        if args.format == "json":
            print(json.dumps({
                "source": source_id,
                "downstream_edges": len(downstream),
                "affected_concepts": sorted(concepts),
                "edges": downstream,
            }, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"# Impact trace for {source_id}")
            print(f"downstream edges: {len(downstream)}")
            print(f"affected concepts: {', '.join(sorted(concepts)) or 'none'}")
            for edge in downstream:
                print(f"  {edge['from_type']}:{edge['from_id']} -> {edge['to_type']}:{edge['to_id']} [{edge['relationship']}]")
        return 0

    # Stale items
    if args.stale:
        stale_items = compute_stale_items(vault, edges)
        if args.write_queue:
            # Merge with existing queue
            existing = load_stale_queue(queue_path)
            existing_refs = {(i["item_type"], i["item_ref"]) for i in existing}
            for item in stale_items:
                if (item["item_type"], item["item_ref"]) not in existing_refs:
                    existing.append(item)
                    existing_refs.add((item["item_type"], item["item_ref"]))
            save_stale_queue(queue_path, existing)
            stale_items = existing

        if args.format == "json":
            print(json.dumps({"stale_count": len(stale_items), "items": stale_items},
                             ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"# Stale Items")
            print(f"total: {len(stale_items)}")
            by_status: dict[str, int] = {}
            for item in stale_items:
                s = item["status"]
                by_status[s] = by_status.get(s, 0) + 1
            for status, count in sorted(by_status.items()):
                print(f"  {status}: {count}")
            for item in stale_items:
                print(f"  [{item['status']}] {item['item_type']}:{item['item_ref']} - {item['reason']}")
        return 0

    # Default: summary
    if args.format == "json":
        print(json.dumps({
            "edges": len(edges),
            "edge_types": sorted({e["relationship"] for e in edges}),
        }, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        by_rel: dict[str, int] = {}
        for edge in edges:
            rel = edge["relationship"]
            by_rel[rel] = by_rel.get(rel, 0) + 1
        print(f"impact graph: {len(edges)} edges")
        for rel, count in sorted(by_rel.items()):
            print(f"  {rel}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
