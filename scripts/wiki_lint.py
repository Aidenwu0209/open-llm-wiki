#!/usr/bin/env python3
"""Deterministic linter for open-llm-wiki vaults."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from wiki_common import (
    Finding,
    LOG_RE,
    SOURCE_ID_RE,
    WIKILINK_RE,
    existing_targets,
    json_dump,
    load_pages,
    markdown_findings,
    parse_frontmatter,
    read_text,
    rel,
    source_id_from_path,
)


REQUIRED_DIRS = ["raw", "sources", "concepts", "drafts", "qa-reports", "claims", "templates", "_state", "log-archive"]
REQUIRED_FILES = [
    "SCHEMA.md",
    "index.md",
    "log.md",
    "_state/id-counter.md",
    "_state/growth-queue.jsonl",
    "_state/source-registry.jsonl",
    "_state/science-review-queue.jsonl",
]
SOURCE_FIELDS = {"id", "title", "status", "created", "updated", "source", "tags"}
SOURCE_EXTENDED_FIELDS = {"type", "source_id", "source_uuid", "title", "status",
                          "source_sha256", "artifact_sha256", "parser", "parser_version",
                          "published_at", "updated_at", "qa_verdict",
                          "claims_total", "claims_supported", "claims_needing_review", "concepts"}
SOURCE_REQUIRED_SECTIONS = [
    "## One-Sentence Conclusion",
    "## Why It Matters",
    "## Key Metrics",
    "## Evidence & Source Anchors",
    "## QA/Review Status",
]
CONCEPT_FIELDS = {"id", "title", "created", "updated"}
CONCEPT_EXTENDED_FIELDS = {"type", "concept_id", "status", "updated_at",
                           "supporting_claims", "contradicted_claims", "stale_claims", "related_concepts"}
CONCEPT_REQUIRED_SECTIONS = [
    "## Definition",
    "## Why It Matters",
    "## Supporting Evidence",
    "## Representative Sources",
]
STALE_WORDS = ("latest", "current", "state of the art", "sota", "now")
OBSIDIAN_SORTSPEC_ENTRIES = [
    "_dashboard.md",
    "index.md",
    "sources",
    "drafts",
    "concepts",
    "claims",
    "qa-reports",
    "raw",
    "templates",
    "templates/agent-prompts",
    "_state",
]


def parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_overall(report: str) -> float | None:
    match = re.search(r"overall:\s*([0-9]+(?:\.[0-9]+)?)\s*/?\s*10?", report, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def check_structure(vault: Path, findings: list[Finding]) -> None:
    for item in REQUIRED_DIRS:
        if not (vault / item).is_dir():
            findings.append(Finding("P0", item, "required directory is missing", "create the directory"))
    for item in REQUIRED_FILES:
        if not (vault / item).is_file():
            findings.append(Finding("P0", item, "required file is missing", "run wiki_init.py or restore the file"))


def check_pages(vault: Path, findings: list[Finding]) -> None:
    ids: dict[str, str] = {}
    for source_dir, expected_status in (("sources", "stable"), ("drafts", "draft")):
        for path in sorted((vault / source_dir).glob("*.md")):
            relpath = rel(path, vault)
            fields, body = parse_frontmatter(path)

            # Core fields required for all source pages
            missing = SOURCE_FIELDS - set(fields)
            if missing:
                findings.append(Finding("P0", relpath, f"missing source frontmatter fields: {sorted(missing)}"))
                continue

            # Extended fields check (P2 for gradual migration)
            if fields.get("type") == "source":
                extended_missing = SOURCE_EXTENDED_FIELDS - set(fields)
                if extended_missing:
                    findings.append(Finding("P2", relpath, f"missing extended source frontmatter fields: {sorted(extended_missing)}"))

                # Validate source_id matches filename
                source_id_field = fields.get("source_id", "")
                source_id = source_id_from_path(path)
                if source_id and source_id_field and source_id_field != source_id:
                    findings.append(Finding("P0", relpath, f"source_id {source_id_field!r} does not match filename {source_id}"))

                # Validate qa_verdict consistency
                qa_verdict = fields.get("qa_verdict", "").strip('"')
                if expected_status == "stable" and qa_verdict and qa_verdict != "PASS":
                    findings.append(Finding("P1", relpath, f"source is stable but qa_verdict is {qa_verdict!r}"))

                # Check required sections
                for section in SOURCE_REQUIRED_SECTIONS:
                    if section not in body:
                        findings.append(Finding("P2", relpath, f"source page missing required section: {section}"))
            else:
                # Legacy source pages: check id matches filename
                source_id = source_id_from_path(path)
                if not source_id:
                    findings.append(Finding("P1", relpath, "source filename must be LLM-NNNN.md"))
                elif fields.get("id") != source_id:
                    findings.append(Finding("P0", relpath, f"id {fields.get('id')!r} does not match filename {source_id}"))

            source_id = source_id_from_path(path)
            if not source_id:
                findings.append(Finding("P1", relpath, "source filename must be LLM-NNNN.md"))
            elif fields.get("id") and fields.get("id") != source_id:
                findings.append(Finding("P0", relpath, f"id {fields.get('id')!r} does not match filename {source_id}"))
            if fields.get("status") != expected_status:
                findings.append(Finding("P0", relpath, f"status must be {expected_status!r} in {source_dir}/"))
            if fields.get("id") in ids:
                findings.append(Finding("P0", relpath, f"duplicate source id also used by {ids[fields['id']]}"))
            ids[fields.get("id", relpath)] = relpath
            if "evidence:" not in body.lower() and "evidence |" not in body.lower():
                findings.append(Finding("P2", relpath, "source page lacks explicit evidence anchors"))

    for path in sorted((vault / "concepts").glob("*.md")):
        relpath = rel(path, vault)
        fields, body = parse_frontmatter(path)
        missing = CONCEPT_FIELDS - set(fields)
        if missing:
            findings.append(Finding("P1", relpath, f"missing concept frontmatter fields: {sorted(missing)}"))

        # Extended fields check for new-style concept pages
        if fields.get("type") == "concept":
            extended_missing = CONCEPT_EXTENDED_FIELDS - set(fields)
            if extended_missing:
                findings.append(Finding("P2", relpath, f"missing extended concept frontmatter fields: {sorted(extended_missing)}"))

            # Check required sections
            for section in CONCEPT_REQUIRED_SECTIONS:
                if section not in body:
                    findings.append(Finding("P2", relpath, f"concept page missing required section: {section}"))

            # Check stale claims consistency
            supporting = int(fields.get("supporting_claims", "0") or "0")
            stale = int(fields.get("stale_claims", "0") or "0")
            contradicted = int(fields.get("contradicted_claims", "0") or "0")
            total = supporting + stale + contradicted
            if total > 0 and stale > supporting:
                findings.append(Finding("P2", relpath, "concept has more stale claims than supporting claims, may need refresh"))

        if "[[" not in body:
            findings.append(Finding("P2", relpath, "concept page has no wiki citations"))


def check_qa(vault: Path, findings: list[Finding]) -> None:
    for path in sorted((vault / "sources").glob("LLM-*.md")):
        source_id = source_id_from_path(path)
        if not source_id:
            continue
        qa_path = vault / "qa-reports" / f"{source_id}.md"
        relpath = rel(path, vault)
        if not qa_path.exists():
            findings.append(Finding("P0", relpath, f"missing QA report qa-reports/{source_id}.md"))
            continue
        qa = read_text(qa_path)
        if "verdict: PASS" not in qa:
            findings.append(Finding("P0", rel(qa_path, vault), "QA report does not contain verdict: PASS"))
        overall = parse_overall(qa)
        if overall is None or overall < 7.0:
            findings.append(Finding("P0", rel(qa_path, vault), "QA overall score is missing or below 7.0"))
        contradiction = vault / "qa-reports" / f"{source_id}-contradiction.md"
        if not contradiction.exists():
            findings.append(Finding("P1", relpath, f"missing contradiction report qa-reports/{source_id}-contradiction.md"))


def check_links(vault: Path, findings: list[Finding]) -> None:
    targets = existing_targets(vault)
    pages = load_pages(vault)
    inbound: dict[str, int] = {target: 0 for target in targets}
    for page in pages:
        for target in page.links:
            if target not in targets:
                findings.append(Finding("P1", page.relpath, f"unresolved wikilink [[{target}]]"))
            else:
                inbound[target] = inbound.get(target, 0) + 1
    for concept in sorted((vault / "concepts").glob("*.md")):
        if inbound.get(concept.stem, 0) == 0:
            findings.append(Finding("P2", rel(concept, vault), "concept page has no inbound links"))


def check_index(vault: Path, findings: list[Finding]) -> None:
    index_path = vault / "index.md"
    if not index_path.exists():
        return
    index = read_text(index_path)
    for path in sorted((vault / "sources").glob("LLM-*.md")):
        source_id = source_id_from_path(path)
        if source_id and f"[[{source_id}]]" not in index:
            findings.append(Finding("P1", "index.md", f"missing source link [[{source_id}]]"))
    for path in sorted((vault / "concepts").glob("*.md")):
        if f"[[{path.stem}]]" not in index:
            findings.append(Finding("P1", "index.md", f"missing concept link [[{path.stem}]]"))


def check_log(vault: Path, findings: list[Finding]) -> None:
    log_path = vault / "log.md"
    if not log_path.exists():
        return
    for number, line in enumerate(read_text(log_path).splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if not LOG_RE.match(line):
            findings.append(Finding("P2", f"log.md:{number}", "log entry does not match required format"))


def check_claim_hygiene(vault: Path, findings: list[Finding]) -> None:
    today = date.today()
    for page in load_pages(vault, folders=("sources", "concepts")):
        updated = parse_date(page.frontmatter.get("updated", ""))
        if not updated:
            continue
        age = (today - updated).days
        if age <= 90:
            continue
        body_lower = page.body.lower()
        if any(word in body_lower for word in STALE_WORDS):
            findings.append(Finding("P2", page.relpath, "time-sensitive wording on a page older than 90 days"))


def check_claim_graph(vault: Path, findings: list[Finding]) -> None:
    claims_path = vault / "claims" / "claims.jsonl"
    if not claims_path.exists():
        findings.append(Finding("P2", "claims/claims.jsonl", "claim graph has not been generated"))
        return
    source_ids = {path.stem for path in (vault / "sources").glob("LLM-*.md")}
    seen_sources: set[str] = set()
    for number, line in enumerate(read_text(claims_path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            findings.append(Finding("P1", f"claims/claims.jsonl:{number}", "claim row is not valid JSON"))
            continue
        source_id = str(item.get("source_id", ""))
        if source_id not in source_ids:
            findings.append(Finding("P1", f"claims/claims.jsonl:{number}", f"claim references missing source {source_id!r}"))
        else:
            seen_sources.add(source_id)
        if not item.get("claim_id") or not item.get("evidence"):
            findings.append(Finding("P2", f"claims/claims.jsonl:{number}", "claim is missing claim_id or evidence"))
    missing = sorted(source_ids - seen_sources)
    if source_ids and missing:
        findings.append(Finding("P2", "claims/claims.jsonl", f"sources missing extracted claims: {', '.join(missing[:8])}"))


def check_state_jsonl(vault: Path, findings: list[Finding]) -> None:
    for relpath in ["_state/growth-queue.jsonl", "_state/source-registry.jsonl", "_state/science-review-queue.jsonl"]:
        path = vault / relpath
        if not path.exists():
            continue
        for number, line in enumerate(read_text(path).splitlines(), 1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                findings.append(Finding("P1", f"{relpath}:{number}", "state row is not valid JSON"))


def load_optional_json(path: Path, vault: Path, findings: list[Finding], expected_type: type) -> object | None:
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        findings.append(Finding("P1", rel(path, vault), f"invalid JSON: {exc}"))
        return None
    if not isinstance(data, expected_type):
        findings.append(Finding("P1", rel(path, vault), f"expected JSON {expected_type.__name__}"))
        return None
    return data


def check_obsidian(vault: Path, findings: list[Finding]) -> None:
    obsidian_dir = vault / ".obsidian"
    if not obsidian_dir.exists():
        findings.append(Finding("P2", ".obsidian", "Obsidian integration is not configured"))
        return

    app_path = obsidian_dir / "app.json"
    if not app_path.exists():
        findings.append(Finding("P2", ".obsidian/app.json", "Obsidian app settings are missing"))
    else:
        app = load_optional_json(app_path, vault, findings, dict)
        if isinstance(app, dict) and app.get("communityPluginsEnabled") is not True:
            findings.append(
                Finding(
                    "P2",
                    ".obsidian/app.json",
                    "communityPluginsEnabled is not true, so configured plugins may remain disabled",
                    "run wiki_obsidian_setup.py or enable community plugins in Obsidian",
                )
            )

    plugins_path = obsidian_dir / "community-plugins.json"
    if not plugins_path.exists():
        findings.append(Finding("P2", ".obsidian/community-plugins.json", "community plugin list is missing"))
    else:
        plugins = load_optional_json(plugins_path, vault, findings, list)
        if isinstance(plugins, list):
            seen: set[str] = set()
            for plugin_id in plugins:
                if not isinstance(plugin_id, str):
                    findings.append(Finding("P1", ".obsidian/community-plugins.json", "plugin ids must be strings"))
                    continue
                if plugin_id in seen:
                    findings.append(Finding("P2", ".obsidian/community-plugins.json", f"duplicate plugin id {plugin_id!r}"))
                seen.add(plugin_id)
                manifest = obsidian_dir / "plugins" / plugin_id / "manifest.json"
                if not manifest.exists():
                    findings.append(
                        Finding(
                            "P2",
                            f".obsidian/plugins/{plugin_id}",
                            "enabled plugin is missing manifest.json",
                            "rerun wiki_obsidian_setup.py without --skip-downloads or install the plugin manually",
                        )
                    )

    sortspec_path = vault / "sortspec.md"
    if not sortspec_path.exists():
        findings.append(Finding("P2", "sortspec.md", "Custom Sort sortspec is missing"))
    else:
        sortspec = read_text(sortspec_path)
        missing = [item for item in OBSIDIAN_SORTSPEC_ENTRIES if item not in sortspec]
        if missing:
            findings.append(Finding("P2", "sortspec.md", f"sortspec missing core entries: {', '.join(missing)}"))

    index_path = vault / "index.md"
    if index_path.exists():
        index = read_text(index_path)
        missing_sections = [heading for heading in ["## Sources", "## Concepts"] if heading not in index]
        if missing_sections:
            findings.append(Finding("P2", "index.md", f"homepage index missing sections: {', '.join(missing_sections)}"))

    inbox = vault / "raw" / "inbox"
    if inbox.exists():
        pending = [path for path in inbox.iterdir() if not path.name.startswith(".")]
        if pending:
            findings.append(Finding("P3", "raw/inbox", f"unprocessed inbox items: {len(pending)}"))

    diagram_paths = []
    if (vault / "canvas").exists():
        diagram_paths.extend(sorted((vault / "canvas").glob("*.canvas")))
    excalidraw_dir = vault / "assets" / "excalidraw"
    if excalidraw_dir.exists():
        diagram_paths.extend(sorted(excalidraw_dir.rglob("*.excalidraw.md")))
        diagram_paths.extend(sorted(excalidraw_dir.rglob("*.excalidraw")))
    if diagram_paths:
        page_text = "\n".join(page.body for page in load_pages(vault, folders=("sources", "concepts")))
        for diagram in diagram_paths:
            diagram_rel = rel(diagram, vault)
            if diagram.stem not in page_text and diagram_rel not in page_text:
                findings.append(
                    Finding(
                        "P2",
                        diagram_rel,
                        "diagram is not referenced from a source or concept page",
                        "link explanatory diagrams from cited source/concept pages",
                    )
                )


def check_graph(vault: Path, findings: list[Finding]) -> None:
    try:
        from wiki_graph_export import graph_findings
    except ImportError as exc:
        findings.append(
            Finding(
                "P1",
                "scripts/wiki_graph_export.py",
                f"graph export runtime is unavailable: {exc}",
                "copy wiki_graph_export.py into the vault runtime",
            )
        )
        return
    for issue in graph_findings(vault):
        findings.append(
            Finding(
                str(issue.get("priority", "P2")),
                str(issue.get("path", ".graph")),
                str(issue.get("message", "graph issue")),
                str(issue.get("fix", "")),
            )
        )


def lint(vault: Path, obsidian: bool = False, graph: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    check_structure(vault, findings)
    check_pages(vault, findings)
    check_qa(vault, findings)
    check_links(vault, findings)
    check_index(vault, findings)
    check_log(vault, findings)
    check_claim_hygiene(vault, findings)
    check_claim_graph(vault, findings)
    check_state_jsonl(vault, findings)
    if obsidian:
        check_obsidian(vault, findings)
    if graph:
        check_graph(vault, findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint an open-llm-wiki vault.")
    parser.add_argument("vault", type=Path)
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format for the lint report.",
    )
    parser.add_argument(
        "--fail-on",
        choices=["none", "p0", "p1", "p2"],
        default="p1",
        help="Exit non-zero at this severity threshold: p0 only, p1 includes P0/P1, p2 includes P0/P1/P2, none never fails.",
    )
    parser.add_argument(
        "--obsidian",
        action="store_true",
        help="Also check optional Obsidian settings, plugin list, sortspec, inbox, and diagram references.",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Also build the optional read-only knowledge graph and check evidence path connectivity.",
    )
    args = parser.parse_args()

    vault = args.vault.resolve()
    findings = lint(vault, obsidian=args.obsidian, graph=args.graph)

    if args.format == "json":
        print(json_dump({"vault": str(vault), "findings": [item.as_dict() for item in findings]}))
    else:
        print("# Wiki Lint Report")
        print(f"- vault: {vault}")
        print(f"- findings: {len(findings)}")
        print("\n## Findings")
        print(markdown_findings(findings))

    priorities = {item.priority for item in findings}
    if args.fail_on == "p0" and "P0" in priorities:
        return 1
    if args.fail_on == "p1" and priorities.intersection({"P0", "P1"}):
        return 1
    if args.fail_on == "p2" and priorities.intersection({"P0", "P1", "P2"}):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
