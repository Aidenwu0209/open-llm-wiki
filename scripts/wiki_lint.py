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
CONCEPT_FIELDS = {"id", "title", "created", "updated"}
STALE_WORDS = ("latest", "current", "state of the art", "sota", "now")


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


def lint(vault: Path) -> list[Finding]:
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
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint an open-llm-wiki vault.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--fail-on", choices=["none", "p0", "p1", "p2"], default="p1")
    args = parser.parse_args()

    vault = args.vault.resolve()
    findings = lint(vault)

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
