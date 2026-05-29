#!/usr/bin/env python3
"""Export a read-only knowledge graph from an open-llm-wiki vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from wiki_common import (
    SOURCE_ID_RE,
    WIKILINK_RE,
    ensure_within,
    json_dump,
    parse_frontmatter,
    read_text,
    rel,
    source_id_from_path,
    write_text,
)


NODE_TYPES = [
    "source",
    "draft",
    "concept",
    "claim",
    "metric",
    "qa-report",
    "contradiction",
    "science-review",
    "raw",
    "queue-task",
]
EDGE_TYPES = [
    "cites",
    "derived-from",
    "supports",
    "contradicts",
    "needs-review",
    "reviewed-by",
    "updates",
    "related-to",
]
GRAPH_SCHEMA_SOURCE = Path(__file__).resolve().parents[1] / "graph" / "graph.schema.json"
SOURCE_OR_CONCEPT_FOLDERS = ("sources", "drafts", "concepts")
CANVAS_NODE_COLORS = {
    "source": "#fb923c",
    "draft": "#fbbf24",
    "concept": "#c084fc",
    "claim": "#60a5fa",
    "metric": "#38bdf8",
    "qa-report": "#4ade80",
    "contradiction": "#f87171",
    "science-review": "#f97316",
    "raw": "#94a3b8",
    "queue-task": "#2dd4bf",
}
CANVAS_EDGE_COLORS = {
    "cites": "#64748b",
    "derived-from": "#475569",
    "supports": "#2563eb",
    "contradicts": "#ef4444",
    "needs-review": "#f97316",
    "reviewed-by": "#22c55e",
    "updates": "#8b5cf6",
    "related-to": "#94a3b8",
}
CANVAS_GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))


def stable_edge_id(source: str, target: str, edge_type: str, label: str = "") -> str:
    payload = f"{source}\0{target}\0{edge_type}\0{label}".encode("utf-8")
    return "edge:" + hashlib.sha1(payload).hexdigest()[:16]


def brief(text: str, limit: int = 220) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("---") or line.startswith("| ---"):
            continue
        if line.startswith("#"):
            continue
        lines.append(re.sub(r"\s+", " ", line))
        if len(" ".join(lines)) >= limit:
            break
    value = " ".join(lines).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def parse_tags(value: str) -> list[str]:
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("'\"") for item in text.split(",") if item.strip()]


def read_jsonl(path: Path, issues: list[dict[str, str]]) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return []
    rows: list[tuple[int, dict[str, Any]]] = []
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(
                {
                    "priority": "P1",
                    "path": f"{path.name}:{number}",
                    "message": f"state or claim row is not valid JSON: {exc}",
                    "fix": "repair the JSONL row before exporting the graph",
                }
            )
            continue
        if isinstance(item, dict):
            rows.append((number, item))
        else:
            issues.append(
                {
                    "priority": "P1",
                    "path": f"{path.name}:{number}",
                    "message": "JSONL row must be an object",
                    "fix": "rewrite the row as a JSON object",
                }
            )
    return rows


def heading_exists(path: Path, anchor: str) -> bool:
    normalized = anchor.strip().lower().replace("-", " ")
    for line in read_text(path).splitlines():
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip().lower().replace("-", " ")
        if heading == normalized:
            return True
    return False


def line_anchor_exists(path: Path, anchor: str) -> bool | None:
    match = re.fullmatch(r"L(\d+)", anchor.strip(), re.IGNORECASE)
    if not match:
        return None
    line_number = int(match.group(1))
    if line_number < 1:
        return False
    return line_number <= len(read_text(path).splitlines())


def validate_evidence(vault: Path, evidence: str, fallback_source_id: str, issues: list[dict[str, str]]) -> None:
    if not evidence:
        issues.append(
            {
                "priority": "P2",
                "path": f"claims/{fallback_source_id or 'unknown'}",
                "message": "claim is missing an evidence anchor",
                "fix": "add an evidence field pointing to a source page section or raw extraction",
            }
        )
        return

    page_part, _, anchor = evidence.partition("#")
    if not page_part:
        return
    if not page_part.endswith(".md"):
        return
    page_path = vault / page_part
    if not page_path.exists():
        issues.append(
            {
                "priority": "P1",
                "path": evidence,
                "message": "claim evidence points to a missing Markdown page",
                "fix": "update the evidence page path or restore the referenced page",
            }
        )
        return
    if anchor:
        line_anchor_valid = line_anchor_exists(page_path, anchor)
        if line_anchor_valid is True:
            return
        if line_anchor_valid is False:
            issues.append(
                {
                    "priority": "P2",
                    "path": evidence,
                    "message": "claim evidence line anchor was not found",
                    "fix": "update the evidence anchor to an existing line",
                }
            )
            return
    if anchor and not heading_exists(page_path, anchor):
        issues.append(
            {
                "priority": "P2",
                "path": evidence,
                "message": "claim evidence heading anchor was not found",
                "fix": "update the evidence anchor to an existing heading",
            }
        )


def source_node_id(source_id: str) -> str:
    return f"source:{source_id}"


def draft_node_id(source_id: str) -> str:
    return f"draft:{source_id}"


def concept_node_id(stem: str) -> str:
    return f"concept:{stem}"


def claim_node_id(claim_id: str) -> str:
    return f"claim:{claim_id}"


def raw_node_id(path: str) -> str:
    return f"raw:{path}"


def qa_node_id(source_id: str) -> str:
    return f"qa-report:{source_id}"


def contradiction_node_id(source_id: str) -> str:
    return f"contradiction:{source_id}"


def review_node_id(review_id: str) -> str:
    return f"science-review:{review_id}"


def queue_node_id(task_id: str) -> str:
    return f"queue-task:{task_id}"


class GraphBuilder:
    def __init__(self, vault: Path) -> None:
        self.vault = vault.resolve()
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.issues: list[dict[str, str]] = []
        self.link_targets: dict[str, str] = {}
        self.evidence_paths: list[dict[str, str]] = []

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        *,
        path: str = "",
        summary: str = "",
        tags: Iterable[str] = (),
        status: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if node_id in self.nodes:
            existing = self.nodes[node_id]
            existing["metadata"].update(metadata or {})
            return
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "path": path,
            "summary": summary,
            "tags": sorted(set(tags)),
            "status": status,
            "metadata": metadata or {},
        }

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        label: str = "",
        weight: float = 0.7,
        evidence: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        edge_id = stable_edge_id(source, target, edge_type, label)
        if edge_id in self.edges:
            return
        self.edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": edge_type,
            "label": label,
            "weight": weight,
            "evidence": evidence,
            "metadata": metadata or {},
        }

    def add_page_nodes(self) -> None:
        for folder in SOURCE_OR_CONCEPT_FOLDERS:
            for path in sorted((self.vault / folder).glob("*.md")):
                fields, body = parse_frontmatter(path)
                relpath = rel(path, self.vault)
                tags = parse_tags(fields.get("tags", ""))
                if folder == "concepts":
                    node_id = concept_node_id(path.stem)
                    label = fields.get("title") or path.stem
                    self.link_targets[path.stem] = node_id
                    self.add_node(
                        node_id,
                        "concept",
                        label,
                        path=relpath,
                        summary=brief(body),
                        tags=tags,
                        metadata={"frontmatter": fields},
                    )
                    continue

                source_id = source_id_from_path(path) or fields.get("id") or path.stem
                node_id = source_node_id(source_id) if folder == "sources" else draft_node_id(source_id)
                node_type = "source" if folder == "sources" else "draft"
                self.link_targets[source_id] = node_id
                self.add_node(
                    node_id,
                    node_type,
                    fields.get("title") or source_id,
                    path=relpath,
                    summary=brief(body),
                    tags=tags,
                    status=fields.get("status", ""),
                    metadata={"frontmatter": fields},
                )

    def add_raw_nodes(self) -> None:
        raw_dir = self.vault / "raw"
        if not raw_dir.exists():
            return
        for path in sorted(raw_dir.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            relpath = rel(path, self.vault)
            self.add_node(
                raw_node_id(relpath),
                "raw",
                path.name,
                path=relpath,
                summary="Raw evidence or parsed Markdown. Graph nodes do not include raw file content.",
                metadata={"size_bytes": path.stat().st_size},
            )

    def add_wikilink_edges(self) -> None:
        for folder in SOURCE_OR_CONCEPT_FOLDERS:
            for path in sorted((self.vault / folder).glob("*.md")):
                relpath = rel(path, self.vault)
                if folder == "concepts":
                    from_id = concept_node_id(path.stem)
                else:
                    source_id = source_id_from_path(path) or path.stem
                    from_id = source_node_id(source_id) if folder == "sources" else draft_node_id(source_id)
                _, body = parse_frontmatter(path)
                for target in sorted({item.strip() for item in WIKILINK_RE.findall(body)}):
                    target_id = self.link_targets.get(target)
                    if not target_id:
                        continue
                    target_type = self.nodes[target_id]["type"]
                    from_type = self.nodes[from_id]["type"]
                    if from_type == "concept" and target_type in {"source", "draft"}:
                        edge_type = "cites"
                    elif from_type in {"source", "draft"} and target_type == "concept":
                        edge_type = "updates"
                    else:
                        edge_type = "related-to"
                    self.add_edge(from_id, target_id, edge_type, label=f"wikilink [[{target}]]", metadata={"path": relpath})

    def add_claims(self) -> None:
        claims_path = self.vault / "claims" / "claims.jsonl"
        for number, row in read_jsonl(claims_path, self.issues):
            claim_id = str(row.get("claim_id") or f"row-{number}")
            source_id = str(row.get("source_id") or "")
            claim_type = str(row.get("claim_type") or "claim")
            node_type = "metric" if claim_type == "metric" else "claim"
            label = str(row.get("predicate") or row.get("object") or claim_id)
            evidence = str(row.get("evidence") or "")
            self.add_node(
                claim_node_id(claim_id),
                node_type,
                label,
                path="claims/claims.jsonl",
                summary=brief(str(row.get("object") or label)),
                tags=[claim_type] if claim_type else [],
                status="needs-review" if row.get("needs_review") else "ready",
                metadata={k: v for k, v in row.items() if k not in {"object"}},
            )
            validate_evidence(self.vault, evidence, source_id, self.issues)
            if source_id:
                target = source_node_id(source_id)
                if target in self.nodes:
                    self.add_edge(claim_node_id(claim_id), target, "derived-from", label="source evidence", evidence=evidence, weight=1.0)
                else:
                    self.issues.append(
                        {
                            "priority": "P1",
                            "path": f"claims/claims.jsonl:{number}",
                            "message": f"claim references missing source {source_id!r}",
                            "fix": "restore the source page or correct the claim source_id",
                        }
                    )
            else:
                self.issues.append(
                    {
                        "priority": "P1",
                        "path": f"claims/claims.jsonl:{number}",
                        "message": "claim is missing source_id, so the evidence path is broken",
                        "fix": "add source_id to the claim row",
                    }
                )

            concepts = row.get("concepts") if isinstance(row.get("concepts"), list) else []
            for concept in concepts:
                concept_id = concept_node_id(str(concept))
                if concept_id not in self.nodes:
                    self.issues.append(
                        {
                            "priority": "P2",
                            "path": f"claims/claims.jsonl:{number}",
                            "message": f"claim points to missing concept {concept!r}",
                            "fix": "create the concept page or remove the stale concept id",
                        }
                    )
                    continue
                self.add_edge(claim_node_id(claim_id), concept_id, "supports", label="claim supports concept", evidence=evidence, weight=0.9)
                if source_id and source_node_id(source_id) in self.nodes:
                    self.evidence_paths.append(
                        {
                            "concept": concept_id,
                            "claim": claim_node_id(claim_id),
                            "source": source_node_id(source_id),
                            "evidence": evidence,
                        }
                    )

            if row.get("needs_review"):
                review_id = str(row.get("review_id") or claim_id)
                self.add_node(
                    review_node_id(review_id),
                    "science-review",
                    f"Review required: {label}",
                    path="_state/science-review-queue.jsonl",
                    summary="Claim requires second-pass scientific review before durable synthesis.",
                    status="pending",
                    metadata={"claim_id": claim_id, "source": "claim.needs_review"},
                )
                self.add_edge(claim_node_id(claim_id), review_node_id(review_id), "needs-review", label="needs science review", weight=1.0)

    def add_reports(self) -> None:
        reports_dir = self.vault / "qa-reports"
        if not reports_dir.exists():
            return
        for path in sorted(reports_dir.glob("*.md")):
            relpath = rel(path, self.vault)
            text = read_text(path)
            source_match = SOURCE_ID_RE.search(path.stem)
            source_id = source_match.group(0) if source_match else ""
            if path.stem.endswith("-contradiction") and source_id:
                node_id = contradiction_node_id(source_id)
                self.add_node(
                    node_id,
                    "contradiction",
                    f"Contradiction report: {source_id}",
                    path=relpath,
                    summary=brief(text),
                    metadata={"source_id": source_id},
                )
                self.add_edge(source_node_id(source_id), node_id, "reviewed-by", label="contradiction scan", weight=0.8)
                continue
            label = f"QA report: {source_id}" if source_id else path.stem
            verdict_match = re.search(r"verdict:\s*([A-Z]+)", text)
            self.add_node(
                qa_node_id(source_id or path.stem),
                "qa-report",
                label,
                path=relpath,
                summary=brief(text),
                status=verdict_match.group(1) if verdict_match else "",
                metadata={"source_id": source_id},
            )
            if source_id:
                self.add_edge(source_node_id(source_id), qa_node_id(source_id), "reviewed-by", label="independent QA", weight=1.0)

    def add_state_nodes(self) -> None:
        review_claim_ids: set[str] = set()
        for number, row in read_jsonl(self.vault / "_state" / "science-review-queue.jsonl", self.issues):
            review_id = str(row.get("review_id") or row.get("claim_id") or f"row-{number}")
            claim_id = str(row.get("claim_id") or "")
            review_claim_ids.add(claim_id)
            self.add_node(
                review_node_id(review_id),
                "science-review",
                str(row.get("review_id") or f"Science review {number}"),
                path="_state/science-review-queue.jsonl",
                summary=brief(" ".join(str(item) for item in row.get("review_reasons", []))) if isinstance(row.get("review_reasons"), list) else "",
                status=str(row.get("review_status") or "pending"),
                metadata=row,
            )
            if claim_id and claim_node_id(claim_id) in self.nodes:
                self.add_edge(claim_node_id(claim_id), review_node_id(review_id), "needs-review", label="science review queue", weight=1.0)
            elif claim_id:
                self.issues.append(
                    {
                        "priority": "P2",
                        "path": f"_state/science-review-queue.jsonl:{number}",
                        "message": f"science review item references missing claim {claim_id!r}",
                        "fix": "restore the claim row or update the review queue item",
                    }
                )

        for number, row in read_jsonl(self.vault / "_state" / "growth-queue.jsonl", self.issues):
            task_id = str(row.get("task_id") or f"row-{number}")
            self.add_node(
                queue_node_id(task_id),
                "queue-task",
                str(row.get("action") or task_id),
                path="_state/growth-queue.jsonl",
                summary=str(row.get("reason") or ""),
                status=str(row.get("status") or ""),
                metadata=row,
            )
            target = str(row.get("target") or "")
            target_id = self.resolve_focus(target, strict=False) if target else ""
            if target_id:
                self.add_edge(queue_node_id(task_id), target_id, "related-to", label="queue target", weight=0.5)

        for number, row in read_jsonl(self.vault / "_state" / "source-registry.jsonl", self.issues):
            source_id = str(row.get("source_id") or row.get("id") or "")
            raw_path = str(row.get("path") or row.get("raw_path") or row.get("file") or "")
            if raw_path and raw_path.startswith("raw/"):
                self.add_node(raw_node_id(raw_path), "raw", Path(raw_path).name, path=raw_path, summary="Raw evidence registry entry.", metadata=row)
            if source_id and source_node_id(source_id) in self.nodes and raw_path:
                self.add_edge(source_node_id(source_id), raw_node_id(raw_path), "derived-from", label="source registry", weight=0.8)
            elif raw_path and not source_id:
                self.issues.append(
                    {
                        "priority": "P3",
                        "path": f"_state/source-registry.jsonl:{number}",
                        "message": "registry row has raw path but no source_id yet",
                        "fix": "run ingest when the source is ready for QA",
                    }
                )
            _ = review_claim_ids

    def add_contradiction_markers(self) -> None:
        marker_re = re.compile(r"\[CONTRADICTION[^\]]*\]")
        for folder in ("sources", "concepts"):
            for path in sorted((self.vault / folder).glob("*.md")):
                text = read_text(path)
                if not marker_re.search(text):
                    continue
                if folder == "concepts":
                    owner_id = concept_node_id(path.stem)
                else:
                    source_id = source_id_from_path(path) or path.stem
                    owner_id = source_node_id(source_id)
                marker_id = f"contradiction-marker:{rel(path, self.vault)}"
                self.add_node(
                    marker_id,
                    "contradiction",
                    f"Contradiction marker in {path.name}",
                    path=rel(path, self.vault),
                    summary="Page contains an explicit contradiction marker.",
                )
                self.add_edge(owner_id, marker_id, "contradicts", label="marked contradiction", weight=1.0)

    def resolve_focus(self, focus: str, *, strict: bool = True) -> str:
        value = focus.strip()
        if not value:
            return ""
        if value in self.nodes:
            return value
        if value.startswith("claim:") and value in self.nodes:
            return value
        if value.startswith("source:") and value in self.nodes:
            return value
        if value.startswith("concept:") and value in self.nodes:
            return value
        if value.startswith("claims/") and "#" in value:
            claim_id = value.rsplit("#", 1)[-1]
            node_id = claim_node_id(claim_id)
            if node_id in self.nodes:
                return node_id
        if value.startswith("sources/") and value.endswith(".md"):
            source_id = source_id_from_path(Path(value)) or Path(value).stem
            node_id = source_node_id(source_id)
            if node_id in self.nodes:
                return node_id
        if value.startswith("drafts/") and value.endswith(".md"):
            source_id = source_id_from_path(Path(value)) or Path(value).stem
            node_id = draft_node_id(source_id)
            if node_id in self.nodes:
                return node_id
        if value.startswith("concepts/") and value.endswith(".md"):
            node_id = concept_node_id(Path(value).stem)
            if node_id in self.nodes:
                return node_id
        if SOURCE_ID_RE.fullmatch(value):
            node_id = source_node_id(value)
            if node_id in self.nodes:
                return node_id
        node_id = claim_node_id(value)
        if node_id in self.nodes:
            return node_id
        node_id = concept_node_id(value)
        if node_id in self.nodes:
            return node_id
        if strict:
            raise SystemExit(f"focus target not found in graph: {focus}")
        return ""

    def build(self) -> dict[str, Any]:
        self.add_page_nodes()
        self.add_raw_nodes()
        self.add_wikilink_edges()
        self.add_claims()
        self.add_reports()
        self.add_state_nodes()
        self.add_contradiction_markers()
        return make_graph(self.vault, self.nodes.values(), self.edges.values(), self.evidence_paths, self.issues)


def make_graph(
    vault: Path,
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    evidence_paths: list[dict[str, str]],
    issues: list[dict[str, str]],
    focus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_list = sorted(nodes, key=lambda item: (item["type"], item["id"]))
    edge_list = sorted(edges, key=lambda item: (item["type"], item["source"], item["target"], item["id"]))
    node_counts = Counter(item["type"] for item in node_list)
    edge_counts = Counter(item["type"] for item in edge_list)
    layers = [
        {"id": node_type, "label": node_type, "node_ids": [node["id"] for node in node_list if node["type"] == node_type]}
        for node_type in NODE_TYPES
        if node_counts.get(node_type)
    ]
    return {
        "version": "1.0",
        "kind": "llm-wiki-graph",
        "vault": str(vault),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "focus": focus,
        "nodes": node_list,
        "edges": edge_list,
        "layers": layers,
        "evidence_paths": evidence_paths,
        "issues": sorted(issues, key=lambda item: (item["priority"], item["path"], item["message"])),
        "counts": {
            "nodes": dict(sorted(node_counts.items())),
            "edges": dict(sorted(edge_counts.items())),
        },
    }


def build_graph(vault: Path, focus: str = "", depth: int = 2) -> dict[str, Any]:
    builder = GraphBuilder(vault)
    graph = builder.build()
    if focus:
        focus_id = builder.resolve_focus(focus)
        return focus_graph(graph, focus_id, depth)
    return graph


def focus_graph(graph: dict[str, Any], focus_id: str, depth: int) -> dict[str, Any]:
    if depth < 0:
        raise SystemExit("--depth must be >= 0")
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])

    selected = {focus_id}
    queue: deque[tuple[str, int]] = deque([(focus_id, 0)])
    while queue:
        node_id, level = queue.popleft()
        if level >= depth:
            continue
        for neighbor in sorted(adjacency.get(node_id, set())):
            if neighbor in selected:
                continue
            selected.add(neighbor)
            queue.append((neighbor, level + 1))

    nodes = [node for node in graph["nodes"] if node["id"] in selected]
    edges = [edge for edge in graph["edges"] if edge["source"] in selected and edge["target"] in selected]
    evidence_paths = [
        path
        for path in graph["evidence_paths"]
        if path["concept"] in selected and path["claim"] in selected and path["source"] in selected
    ]
    issues = [
        issue
        for issue in graph["issues"]
        if not issue.get("node_id") or issue.get("node_id") in selected
    ]
    return make_graph(
        Path(graph["vault"]),
        nodes,
        edges,
        evidence_paths,
        issues,
        focus={"node_id": focus_id, "depth": depth},
    )


def ensure_graph_output(vault: Path, output: Path, graph_format: str) -> Path:
    output = ensure_within(output, vault, "graph output must stay inside the vault")
    relpath = rel(output, vault)
    first = relpath.split("/", 1)[0]
    if graph_format == "json" and first != ".graph":
        raise SystemExit("graph JSON output must stay under .graph/")
    if graph_format == "obsidian-canvas" and first != "canvas":
        raise SystemExit("Obsidian Canvas output must stay under canvas/")
    return output


def ensure_graph_aux_output(vault: Path, filename: str, message: str) -> Path:
    graph_dir = ensure_within(
        vault / ".graph",
        vault,
        ".graph output directory must stay inside the vault",
    )
    graph_dir.mkdir(parents=True, exist_ok=True)
    return ensure_within(graph_dir / filename, graph_dir, message)


def default_output(vault: Path, graph_format: str) -> Path:
    if graph_format == "obsidian-canvas":
        return vault / "canvas" / "wiki-graph.canvas"
    return vault / ".graph" / "graph.json"


def resolve_output_arg(vault: Path, output: Path | None, graph_format: str) -> Path:
    if output is None:
        return default_output(vault, graph_format)
    if output.is_absolute():
        return output
    return vault / output


def render_report(graph: dict[str, Any], output_path: Path | None = None) -> str:
    lines = [
        "# Wiki Graph Report",
        f"- vault: {graph['vault']}",
        f"- generated_at: {graph['generated_at']}",
        f"- nodes: {len(graph['nodes'])}",
        f"- edges: {len(graph['edges'])}",
        f"- evidence_paths: {len(graph['evidence_paths'])}",
    ]
    if graph.get("focus"):
        lines.append(f"- focus: {graph['focus']['node_id']} depth={graph['focus']['depth']}")
    if output_path:
        lines.append(f"- output: {output_path}")
    lines.extend(["", "## Node Counts"])
    for node_type, count in graph["counts"]["nodes"].items():
        lines.append(f"- {node_type}: {count}")
    lines.extend(["", "## Edge Counts"])
    for edge_type, count in graph["counts"]["edges"].items():
        lines.append(f"- {edge_type}: {count}")
    lines.extend(["", "## Issues"])
    if graph["issues"]:
        for issue in graph["issues"]:
            fix = f" Fix: {issue['fix']}" if issue.get("fix") else ""
            lines.append(f"- [{issue['priority']}] `{issue['path']}`: {issue['message']}{fix}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def canvas_degrees(edges: Iterable[dict[str, Any]]) -> Counter[str]:
    degree: Counter[str] = Counter()
    for edge in edges:
        degree[str(edge["source"])] += 1
        degree[str(edge["target"])] += 1
    return degree


def canvas_display_nodes(graph: dict[str, Any], degree: Counter[str]) -> tuple[list[dict[str, Any]], int]:
    nodes: list[dict[str, Any]] = []
    hidden_isolated_raw = 0
    for node in graph["nodes"]:
        if node["type"] == "raw":
            raw_name = Path(str(node.get("path") or node.get("label") or "")).name
            if raw_name.startswith("."):
                continue
            if degree[node["id"]] == 0:
                hidden_isolated_raw += 1
                continue
        nodes.append(node)
    if hidden_isolated_raw:
        nodes.append(
            {
                "id": "canvas:unlinked-raw-summary",
                "type": "raw",
                "label": f"{hidden_isolated_raw} unlinked raw files",
                "path": "raw/",
                "summary": "Unlinked raw files are hidden from this Canvas view to keep the evidence graph readable.",
                "tags": [],
                "status": "hidden-from-canvas",
                "metadata": {"hidden_isolated_raw": hidden_isolated_raw},
            }
        )
    return nodes, hidden_isolated_raw


def canvas_node_sort_key(node: dict[str, Any], degree: Counter[str]) -> tuple[int, int, str, str]:
    try:
        type_rank = NODE_TYPES.index(node["type"])
    except ValueError:
        type_rank = len(NODE_TYPES)
    return (-degree[node["id"]], type_rank, str(node.get("label") or ""), node["id"])


def canvas_initial_positions(nodes: list[dict[str, Any]], degree: Counter[str]) -> dict[str, tuple[float, float]]:
    if not nodes:
        return {}
    if len(nodes) == 1:
        return {nodes[0]["id"]: (0.0, 0.0)}

    sorted_nodes = sorted(nodes, key=lambda node: canvas_node_sort_key(node, degree))
    spread = max(460.0, math.sqrt(len(sorted_nodes)) * 170.0)
    positions: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(sorted_nodes):
        angle = index * CANVAS_GOLDEN_ANGLE
        radius = spread * math.sqrt((index + 0.5) / len(sorted_nodes))
        if degree[node["id"]] == 0:
            radius = spread * 1.15
        positions[node["id"]] = (math.cos(angle) * radius, math.sin(angle) * radius)
    return positions


def canvas_layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], degree: Counter[str]) -> dict[str, tuple[float, float]]:
    positions = canvas_initial_positions(nodes, degree)
    node_ids = [node["id"] for node in nodes]
    visible_ids = set(node_ids)
    visible_edges = [edge for edge in edges if edge["source"] in visible_ids and edge["target"] in visible_ids]
    if len(nodes) <= 1:
        return positions
    if len(nodes) > 650:
        return positions

    area = max(1, len(nodes)) * 160_000.0
    ideal_distance = math.sqrt(area / len(nodes))
    temperature = max(120.0, math.sqrt(len(nodes)) * 45.0)
    iterations = 120 if len(nodes) <= 120 else 80 if len(nodes) <= 300 else 45
    max_weight = max((float(edge.get("weight") or 1.0) for edge in visible_edges), default=1.0)

    for _ in range(iterations):
        displacement: dict[str, list[float]] = {
            node_id: [-positions[node_id][0] * 0.006, -positions[node_id][1] * 0.006]
            for node_id in node_ids
        }
        for index, source in enumerate(node_ids):
            source_x, source_y = positions[source]
            for target in node_ids[index + 1 :]:
                target_x, target_y = positions[target]
                dx = source_x - target_x
                dy = source_y - target_y
                distance = max(math.hypot(dx, dy), 0.01)
                force = ideal_distance * ideal_distance / distance
                fx = dx / distance * force
                fy = dy / distance * force
                displacement[source][0] += fx
                displacement[source][1] += fy
                displacement[target][0] -= fx
                displacement[target][1] -= fy

        for edge in visible_edges:
            source = edge["source"]
            target = edge["target"]
            source_x, source_y = positions[source]
            target_x, target_y = positions[target]
            dx = source_x - target_x
            dy = source_y - target_y
            distance = max(math.hypot(dx, dy), 0.01)
            weight = max(0.2, min(2.2, float(edge.get("weight") or 1.0) / max_weight + 0.35))
            force = distance * distance / ideal_distance * weight
            fx = dx / distance * force
            fy = dy / distance * force
            displacement[source][0] -= fx
            displacement[source][1] -= fy
            displacement[target][0] += fx
            displacement[target][1] += fy

        for node_id in node_ids:
            dx, dy = displacement[node_id]
            length = max(math.hypot(dx, dy), 0.01)
            step = min(length, temperature)
            x, y = positions[node_id]
            positions[node_id] = (x + dx / length * step, y + dy / length * step)
        temperature *= 0.92

    return positions


def canvas_node_dimensions(node: dict[str, Any], degree: int, max_degree: int) -> tuple[int, int]:
    ratio = math.sqrt(degree / max(max_degree, 1)) if degree else 0.0
    if node.get("path") and str(node["path"]).endswith(".md"):
        return int(240 + ratio * 70), int(112 + ratio * 34)
    if node["type"] in {"claim", "metric", "science-review", "contradiction"}:
        return int(220 + ratio * 64), int(92 + ratio * 34)
    return int(210 + ratio * 58), int(86 + ratio * 28)


def canvas_node_text(node: dict[str, Any]) -> str:
    lines = [f"**{node['label']}**", "", f"Type: `{node['type']}`"]
    if node.get("status"):
        lines.append(f"Status: `{node['status']}`")
    if node.get("path"):
        lines.append(f"Path: `{node['path']}`")
    if node.get("summary"):
        lines.extend(["", brief(str(node["summary"]), 120)])
    return "\n".join(lines)


def canvas_side_between(source: tuple[float, float], target: tuple[float, float]) -> tuple[str, str]:
    dx = target[0] - source[0]
    dy = target[1] - source[1]
    if abs(dx) >= abs(dy):
        return ("right", "left") if dx >= 0 else ("left", "right")
    return ("bottom", "top") if dy >= 0 else ("top", "bottom")


def canvas_edge_label(edge: dict[str, Any]) -> str:
    if edge["type"] in {"contradicts", "needs-review"}:
        return edge["type"]
    return ""


def to_canvas(graph: dict[str, Any]) -> dict[str, Any]:
    degree = canvas_degrees(graph["edges"])
    display_nodes, _ = canvas_display_nodes(graph, degree)
    display_ids = {node["id"] for node in display_nodes}
    display_edges = [edge for edge in graph["edges"] if edge["source"] in display_ids and edge["target"] in display_ids]
    positions = canvas_layout(display_nodes, display_edges, degree)
    max_degree = max((degree[node["id"]] for node in display_nodes), default=1)
    dimensions = {
        node["id"]: canvas_node_dimensions(node, degree[node["id"]], max_degree)
        for node in display_nodes
    }

    min_left = min((positions[node["id"]][0] - dimensions[node["id"]][0] / 2 for node in display_nodes), default=0)
    min_top = min((positions[node["id"]][1] - dimensions[node["id"]][1] / 2 for node in display_nodes), default=0)
    shift_x = 96 - min_left if min_left < 96 else 0
    shift_y = 96 - min_top if min_top < 96 else 0

    canvas_nodes: list[dict[str, Any]] = []
    for node in display_nodes:
        center_x, center_y = positions[node["id"]]
        width, height = dimensions[node["id"]]
        base = {
            "id": node["id"],
            "x": int(round(center_x - width / 2 + shift_x)),
            "y": int(round(center_y - height / 2 + shift_y)),
            "width": width,
            "height": height,
            "color": CANVAS_NODE_COLORS.get(node["type"], "#94a3b8"),
        }
        if node.get("path") and str(node["path"]).endswith(".md"):
            canvas_nodes.append({**base, "type": "file", "file": node["path"]})
        else:
            canvas_nodes.append({**base, "type": "text", "text": canvas_node_text(node)})

    canvas_edges: list[dict[str, Any]] = []
    for edge in display_edges:
        source_position = positions.get(edge["source"])
        target_position = positions.get(edge["target"])
        if not source_position or not target_position:
            continue
        from_side, to_side = canvas_side_between(source_position, target_position)
        canvas_edge = {
            "id": edge["id"],
            "fromNode": edge["source"],
            "fromSide": from_side,
            "toNode": edge["target"],
            "toSide": to_side,
            "color": CANVAS_EDGE_COLORS.get(edge["type"], "#94a3b8"),
        }
        label = canvas_edge_label(edge)
        if label:
            canvas_edge["label"] = label
        canvas_edges.append(canvas_edge)
    return {"nodes": canvas_nodes, "edges": canvas_edges}


def graph_findings(vault: Path) -> list[dict[str, str]]:
    graph = build_graph(vault)
    findings = list(graph["issues"])
    connected: Counter[str] = Counter()
    for edge in graph["edges"]:
        connected[edge["source"]] += 1
        connected[edge["target"]] += 1
    for node in graph["nodes"]:
        if node["type"] in {"source", "concept"} and connected[node["id"]] == 0:
            findings.append(
                {
                    "priority": "P2",
                    "path": node.get("path") or node["id"],
                    "message": f"{node['type']} node is isolated in the graph",
                    "fix": "add wikilinks or claim references that connect this page to evidence",
                }
            )
    for node_type in ("source", "concept"):
        if not any(node["type"] == node_type for node in graph["nodes"]):
            findings.append(
                {
                    "priority": "P2",
                    "path": ".graph",
                    "message": f"graph has no {node_type} nodes",
                    "fix": "run ingest before relying on the graph view",
                }
            )
    if any(node["type"] in {"claim", "metric"} for node in graph["nodes"]) and not graph["evidence_paths"]:
        findings.append(
            {
                "priority": "P2",
                "path": "claims/claims.jsonl",
                "message": "graph has claims but no complete concept -> claim -> source evidence paths",
                "fix": "connect claims to concepts and source evidence",
            }
        )
    return findings


def write_graph_outputs(vault: Path, graph: dict[str, Any], output: Path, graph_format: str) -> None:
    if graph_format == "json":
        write_text(output, json_dump(graph) + "\n")
        schema_target = ensure_graph_aux_output(
            vault,
            "graph.schema.json",
            "graph schema output must stay inside .graph",
        )
        if GRAPH_SCHEMA_SOURCE.exists():
            shutil.copy2(GRAPH_SCHEMA_SOURCE, schema_target)
        report_target = ensure_graph_aux_output(
            vault,
            "graph-report.md",
            "graph report output must stay inside .graph",
        )
        write_text(report_target, render_report(graph, output))
        return
    canvas = to_canvas(graph)
    write_text(output, json_dump(canvas) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a read-only graph from an open-llm-wiki vault.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--format", choices=["json", "obsidian-canvas"], default="json")
    parser.add_argument("--output", type=Path, help="Output path inside .graph/ for JSON or canvas/ for Obsidian Canvas.")
    parser.add_argument("--focus", help="Node id, source id, claim id, or relative page path to export a local graph.")
    parser.add_argument("--depth", type=int, default=2, help="Neighborhood depth when --focus is set.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    output = ensure_graph_output(vault, resolve_output_arg(vault, args.output, args.format), args.format)
    graph = build_graph(vault, focus=args.focus or "", depth=args.depth)
    write_graph_outputs(vault, graph, output, args.format)
    print(render_report(graph, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
