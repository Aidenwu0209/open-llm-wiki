#!/usr/bin/env python3
"""Extract normalized claims from open-llm-wiki source pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from wiki_common import WIKILINK_RE, ensure_vault_subpath, json_dump, parse_frontmatter, read_text, rel, write_text


NUMBER_RE = re.compile(r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*([A-Za-z%]+)?")


def parse_tags(raw: str) -> list[str]:
    return [item.strip(" []'\"") for item in raw.split(",") if item.strip(" []'\"")]


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE | re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def parse_table_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [normalize_space(cell) for cell in stripped.strip("|").split("|")]
        if cells and cells[0].lower() not in {"metric", ""}:
            rows.append(cells)
    return rows


def parse_value(value: str) -> tuple[float | None, str]:
    normalized = value.replace(",", "")
    matches = list(NUMBER_RE.finditer(normalized))
    if len(matches) != 1:
        return None, ""
    match = matches[0]
    prefix = normalized[: match.start()].strip().lower()
    suffix = normalized[match.end() :].strip()
    if prefix not in {"", "about", "approx", "approx.", "approximately", "~"} or suffix:
        return None, ""
    number = float(match.group(1))
    unit = match.group(2) or ""
    return number, unit


def has_numeric_text(value: str) -> bool:
    return NUMBER_RE.search(value.replace(",", "")) is not None


def needs_metric_review(raw_value: str, evidence: str, numeric: float | None) -> bool:
    return (
        "not available" in evidence.lower()
        or not evidence
        or (numeric is None and has_numeric_text(raw_value))
    )


def source_section_anchor(relpath: str, heading: str, evidence: str) -> str:
    clean = normalize_space(evidence)
    if not clean:
        return ""
    if clean.startswith(("sources/", "raw/")):
        return clean
    return f"{relpath}#{heading}"


def concept_links(body: str, concept_names: set[str]) -> list[str]:
    links = []
    for link in WIKILINK_RE.findall(body):
        clean = link.strip()
        if clean in concept_names:
            links.append(clean)
    return sorted(dict.fromkeys(links))


def contribution_claim(source_id: str, title: str, body: str, concepts: list[str], relpath: str) -> dict[str, object] | None:
    contribution = normalize_space(section(body, "One-Sentence Contribution"))
    if not contribution:
        return None
    claim_id = f"claim-{short_hash(source_id + contribution)}"
    return {
        "claim_id": claim_id,
        "source_id": source_id,
        "source_title": title,
        "page": relpath,
        "claim_type": "contribution",
        "subject": title,
        "predicate": "contributes",
        "object": contribution,
        "value": None,
        "unit": "",
        "baseline": "",
        "evidence": relpath + "#One-Sentence Contribution",
        "concepts": concepts,
        "confidence": 0.74,
        "needs_review": False,
    }


def metric_claims(source_id: str, title: str, body: str, concepts: list[str], relpath: str) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    key_data = section(body, "Key Data")
    for row in parse_table_rows(key_data):
        if len(row) < 4:
            continue
        metric, raw_value, baseline, evidence = row[:4]
        numeric, unit = parse_value(raw_value)
        claim_id = f"claim-{short_hash(source_id + metric + raw_value + evidence)}"
        anchor = source_section_anchor(relpath, "Key Data", evidence)
        claims.append(
            {
                "claim_id": claim_id,
                "source_id": source_id,
                "source_title": title,
                "page": relpath,
                "claim_type": "metric",
                "subject": title,
                "predicate": metric,
                "object": raw_value,
                "value": numeric,
                "unit": unit,
                "baseline": baseline,
                "evidence": anchor,
                "concepts": concepts,
                "confidence": 0.82 if evidence else 0.55,
                "needs_review": needs_metric_review(raw_value, evidence, numeric),
            }
        )
    return claims


def extract_claims(vault: Path) -> list[dict[str, object]]:
    concept_names = {path.stem for path in (vault / "concepts").glob("*.md")}
    claims: list[dict[str, object]] = []
    for path in sorted((vault / "sources").glob("LLM-*.md")):
        fields, body = parse_frontmatter(path)
        source_id = fields.get("id", path.stem)
        title = fields.get("title", path.stem)
        concepts = concept_links(body, concept_names)
        relpath = rel(path, vault)
        first = contribution_claim(source_id, title, body, concepts, relpath)
        if first:
            claims.append(first)
        claims.extend(metric_claims(source_id, title, body, concepts, relpath))
    return claims


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    write_text(path, text)


def report(claims: list[dict[str, object]], output: Path) -> str:
    by_type: dict[str, int] = {}
    by_concept: dict[str, int] = {}
    review_needed = 0
    for claim in claims:
        by_type[str(claim["claim_type"])] = by_type.get(str(claim["claim_type"]), 0) + 1
        if claim.get("needs_review"):
            review_needed += 1
        for concept in claim.get("concepts", []):
            by_concept[str(concept)] = by_concept.get(str(concept), 0) + 1
    concept_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(by_concept.items())) or "- none"
    type_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(by_type.items())) or "- none"
    return (
        "# Claim Extraction Report\n"
        f"- date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- output: {output.as_posix()}\n"
        f"- claims: {len(claims)}\n"
        f"- needs_review: {review_needed}\n\n"
        "## By Type\n\n"
        f"{type_lines}\n\n"
        "## By Concept\n\n"
        f"{concept_lines}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract normalized claims from source pages.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--output", type=Path, help="JSONL output path. Defaults to <vault>/claims/claims.jsonl.")
    parser.add_argument("--report", type=Path, help="Markdown report path. Defaults to <vault>/claims/claim-report.md.")
    parser.add_argument("--format", choices=["summary", "json"], default="summary")
    args = parser.parse_args()

    vault = args.vault.resolve()
    if not (vault / "sources").is_dir():
        raise SystemExit(f"sources directory not found: {vault / 'sources'}")
    output = ensure_vault_subpath(
        args.output or vault / "claims" / "claims.jsonl",
        vault,
        "claims",
        "claim output must stay under claims/",
    )
    report_path = ensure_vault_subpath(
        args.report or vault / "claims" / "claim-report.md",
        vault,
        "claims",
        "claim report must stay under claims/",
    )

    claims = extract_claims(vault)
    write_jsonl(output, claims)
    write_text(report_path, report(claims, output))
    if args.format == "json":
        print(json_dump({"claims": len(claims), "output": str(output), "report": str(report_path)}))
    else:
        print(f"claims: {len(claims)}")
        print(f"output: {output}")
        print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
