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
from wiki_source_registry import load_registry, validate_registry as validate_registry_rows


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
CONCEPT_FIELDS = {"id", "title", "created", "updated"}
STALE_WORDS = ("latest", "current", "state of the art", "sota", "now")
CLAIM_LEDGER_REQUIRED = {"claim_id", "source_id", "source_uuid", "claim_text", "evidence_quote", "evidence_hash", "anchor", "verdict", "created_at", "updated_at"}
VALID_VERDICTS = frozenset({"unreviewed", "supported", "weak", "contradicted", "retracted", "stale"})
VERDICT_EXCLUDED = frozenset({"contradicted", "retracted", "stale"})
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
            missing = SOURCE_FIELDS - set(fields)
            if missing:
                findings.append(Finding("P0", relpath, f"missing source frontmatter fields: {sorted(missing)}"))
                continue
            source_id = source_id_from_path(path)
            if not source_id:
                findings.append(Finding("P1", relpath, "source filename must be LLM-NNNN.md"))
            elif fields.get("id") != source_id:
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
    import hashlib

    claims_path = vault / "claims" / "claims.jsonl"
    if not claims_path.exists():
        findings.append(Finding("P2", "claims/claims.jsonl", "claim graph has not been generated"))
        return
    source_ids = {path.stem for path in (vault / "sources").glob("LLM-*.md")}
    seen_sources: set[str] = set()
    seen_claim_ids: dict[str, int] = {}
    for number, line in enumerate(read_text(claims_path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            findings.append(Finding("P1", f"claims/claims.jsonl:{number}", "claim row is not valid JSON"))
            continue

        claim_id = str(item.get("claim_id", ""))
        source_id = str(item.get("source_id", ""))

        # claim_id uniqueness
        if claim_id:
            if claim_id in seen_claim_ids:
                findings.append(Finding("P1", f"claims/claims.jsonl:{number}", f"duplicate claim_id {claim_id!r} (also row {seen_claim_ids[claim_id]})"))
            else:
                seen_claim_ids[claim_id] = number

        # source reference
        if source_id not in source_ids:
            findings.append(Finding("P1", f"claims/claims.jsonl:{number}", f"claim references missing source {source_id!r}"))
        else:
            seen_sources.add(source_id)

        if not claim_id or not item.get("evidence"):
            findings.append(Finding("P2", f"claims/claims.jsonl:{number}", "claim is missing claim_id or evidence"))

        # Claim ledger required fields
        missing_ledger = CLAIM_LEDGER_REQUIRED - set(item)
        if missing_ledger:
            findings.append(Finding("P1", f"claims/claims.jsonl:{number}", f"claim missing ledger fields: {', '.join(sorted(missing_ledger)[:6])}"))

        # evidence_hash validation
        evidence_quote = str(item.get("evidence_quote", ""))
        stored_hash = str(item.get("evidence_hash", ""))
        if evidence_quote and stored_hash:
            expected_hash = hashlib.sha256(evidence_quote.encode("utf-8")).hexdigest()[:16]
            if stored_hash != expected_hash:
                findings.append(Finding("P1", f"claims/claims.jsonl:{number}", f"evidence_hash mismatch: stored={stored_hash} expected={expected_hash}"))

        # verdict validation
        verdict = str(item.get("verdict", "unreviewed"))
        if verdict not in VALID_VERDICTS:
            findings.append(Finding("P1", f"claims/claims.jsonl:{number}", f"invalid verdict: {verdict!r}"))

    missing = sorted(source_ids - seen_sources)
    if source_ids and missing:
        findings.append(Finding("P2", "claims/claims.jsonl", f"sources missing extracted claims: {', '.join(missing[:8])}"))


def check_synthesis_verdicts(vault: Path, findings: list[Finding]) -> None:
    """Check that concept pages don't contain contradicted/retracted/stale claims in synthesis."""
    claims_path = vault / "claims" / "claims.jsonl"
    if not claims_path.exists():
        return
    excluded_claims: set[str] = set()
    for line in read_text(claims_path).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        verdict = str(item.get("verdict", ""))
        if verdict in VERDICT_EXCLUDED:
            excluded_claims.add(str(item.get("claim_id", "")))

    for page in load_pages(vault, folders=("concepts",)):
        if "<!-- open-llm-wiki:semantic-claims:start -->" not in page.body:
            continue
        for claim_id in excluded_claims:
            if claim_id in page.body:
                findings.append(Finding("P1", page.relpath, f"concept synthesis contains excluded claim {claim_id} (contradicted/retracted/stale)"))


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


def check_source_registry(vault: Path, findings: list[Finding]) -> None:
    registry_path = vault / "_state" / "source-registry.jsonl"
    if not registry_path.exists():
        return
    rows = load_registry(registry_path)
    for location, message in validate_registry_rows(rows):
        findings.append(Finding("P1", f"_state/source-registry.jsonl ({location})", message))

    # Check artifact/source_page link existence
    source_ids_on_disk = {p.stem for p in (vault / "sources").glob("LLM-*.md")}
    for i, row in enumerate(rows):
        source_id = row.get("source_id", "")
        status = row.get("status", "")
        if status in ("published", "qa_passed") and source_id not in source_ids_on_disk:
            findings.append(Finding(
                "P1",
                f"_state/source-registry.jsonl (row {i + 1})",
                f"published/qa_passed source_id {source_id} has no matching source page in sources/",
            ))

def check_ingest_plan(vault: Path, findings: list[Finding]) -> None:
    plan_path = vault / "_state" / "ingest-plan.json"
    if not plan_path.exists():
        return
    try:
        plan = json.loads(read_text(plan_path))
    except json.JSONDecodeError as exc:
        findings.append(Finding("P1", "_state/ingest-plan.json", f"invalid JSON: {exc}"))
        return
    if not isinstance(plan, dict):
        findings.append(Finding("P1", "_state/ingest-plan.json", "plan must be a JSON object"))
        return

    # Check plan schema
    for field in ("version", "generated_at", "vault", "total_sources", "items"):
        if field not in plan:
            findings.append(Finding("P1", "_state/ingest-plan.json", f"missing required field: {field}"))

    items = plan.get("items", [])
    if not isinstance(items, list):
        findings.append(Finding("P1", "_state/ingest-plan.json", "items must be a list"))
        return

    valid_states = {"ready", "stageable", "blocked", "cached", "published", "failed", "stale"}
    required_item_fields = {"source_path", "source_uuid", "source_id", "state", "reason", "recommended_action", "freshness_verdict"}

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            findings.append(Finding("P1", f"_state/ingest-plan.json (item {i + 1})", "plan item must be a JSON object"))
            continue
        missing = required_item_fields - set(item.keys())
        if missing:
            findings.append(Finding("P1", f"_state/ingest-plan.json (item {i + 1})", f"missing fields: {sorted(missing)}"))
        state = item.get("state", "")
        if state and state not in valid_states:
            findings.append(Finding("P1", f"_state/ingest-plan.json (item {i + 1})", f"invalid state: {state!r}"))

    # Cross-check with registry
    registry_path = vault / "_state" / "source-registry.jsonl"
    if registry_path.exists():
        registry_rows = load_registry(registry_path)
        registry_by_uuid = {r.get("source_uuid", ""): r for r in registry_rows if r.get("source_uuid")}
        for i, item in enumerate(items):
            uuid_val = item.get("source_uuid", "")
            if uuid_val and uuid_val in registry_by_uuid:
                reg_row = registry_by_uuid[uuid_val]
                # Published in plan but not in registry
                if item.get("state") == "published" and reg_row.get("status") != "published":
                    findings.append(Finding(
                        "P1",
                        f"_state/ingest-plan.json (item {i + 1})",
                        f"plan says published but registry status is {reg_row.get('status')!r}",
                    ))
                # Stale in plan but registry says fresh
                if item.get("state") == "stale" and reg_row.get("status") == "published":
                    findings.append(Finding(
                        "P2",
                        f"_state/ingest-plan.json (item {i + 1})",
                        "plan says stale but registry still says published; re-run ingest plan",
                    ))


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
    check_synthesis_verdicts(vault, findings)
    check_state_jsonl(vault, findings)
    check_source_registry(vault, findings)
    check_ingest_plan(vault, findings)
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
