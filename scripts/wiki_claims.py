#!/usr/bin/env python3
"""Extract normalized claims from open-llm-wiki source pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from wiki_common import WIKILINK_RE, ensure_within, json_dump, parse_frontmatter, read_text, rel, write_text


NUMBER_RE = re.compile(r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*([A-Za-z%]+)?")

LEDGER_FIELDS = frozenset({
    "claim_id", "source_uuid", "source_id", "chunk_id", "claim_text",
    "normalized_claim", "claim_type", "entities", "concepts",
    "evidence_quote", "evidence_hash", "anchor", "confidence",
    "verdict", "contradiction_group", "created_at", "updated_at",
    # legacy / normalization fields kept for backward compatibility
    "source_title", "page", "subject", "predicate", "object",
    "value", "unit", "baseline", "evidence",
    "metric_key", "normalized_value", "normalized_unit", "unit_family",
    "baseline_key", "protocol_key", "normalization_warnings", "needs_review",
})

VALID_VERDICTS = frozenset({
    "unreviewed", "supported", "weak", "contradicted", "retracted", "stale",
})

MAX_EVIDENCE_QUOTE_LENGTH = 300


def source_uuid_from_id(source_id: str) -> str:
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:32]


def extract_evidence_quote(body: str, heading: str, max_len: int = MAX_EVIDENCE_QUOTE_LENGTH) -> str:
    sec = section(body, heading)
    if not sec:
        return ""
    lines = [line.strip() for line in sec.splitlines() if line.strip() and not line.strip().startswith("|") and not line.strip().startswith("#")]
    text = " ".join(lines)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def compute_evidence_hash(evidence_quote: str) -> str:
    return hashlib.sha256(evidence_quote.encode("utf-8")).hexdigest()[:16]


def extract_entities(text: str) -> list[str]:
    words = re.findall(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\b", text)
    seen: list[str] = []
    for w in words:
        if w not in seen and len(w) > 2:
            seen.append(w)
    return seen[:8]


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


def source_page_path(vault: Path, path: Path) -> Path:
    sources = vault / "sources"
    if sources.is_symlink():
        raise SystemExit("claim source directory must not be a symlink")
    if path.is_symlink():
        try:
            display = path.relative_to(vault).as_posix()
        except ValueError:
            display = path.as_posix()
        raise SystemExit(f"claim source page must not be a symlink: {display}")
    return ensure_within(path, sources, "claim source page must stay under sources/")


def contribution_claim(source_id: str, title: str, body: str, concepts: list[str], relpath: str, chunk_id: str = "") -> dict[str, object] | None:
    contribution = normalize_space(section(body, "One-Sentence Contribution"))
    if not contribution:
        return None
    claim_id = f"claim-{short_hash(source_id + contribution)}"
    evidence_quote = extract_evidence_quote(body, "One-Sentence Contribution")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "claim_id": claim_id,
        "source_uuid": source_uuid_from_id(source_id),
        "source_id": source_id,
        "chunk_id": chunk_id,
        "claim_text": contribution,
        "normalized_claim": normalize_space(contribution.lower()),
        "claim_type": "contribution",
        "entities": extract_entities(contribution),
        "concepts": concepts,
        "evidence_quote": evidence_quote,
        "evidence_hash": compute_evidence_hash(evidence_quote),
        "anchor": relpath + "#One-Sentence Contribution",
        "confidence": 0.74,
        "verdict": "unreviewed",
        "contradiction_group": "",
        "created_at": now,
        "updated_at": now,
        # legacy fields
        "source_title": title,
        "page": relpath,
        "subject": title,
        "predicate": "contributes",
        "object": contribution,
        "value": None,
        "unit": "",
        "baseline": "",
        "evidence": relpath + "#One-Sentence Contribution",
        "needs_review": False,
    }


def metric_claims(source_id: str, title: str, body: str, concepts: list[str], relpath: str, chunk_id: str = "") -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    key_data = section(body, "Key Data")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for row in parse_table_rows(key_data):
        if len(row) < 4:
            continue
        metric, raw_value, baseline, evidence = row[:4]
        numeric, unit = parse_value(raw_value)
        claim_id = f"claim-{short_hash(source_id + metric + raw_value + evidence)}"
        anchor = source_section_anchor(relpath, "Key Data", evidence)
        claim_text = f"{metric}: {raw_value}"
        evidence_quote = evidence if len(evidence) <= MAX_EVIDENCE_QUOTE_LENGTH else evidence[:MAX_EVIDENCE_QUOTE_LENGTH].rsplit(" ", 1)[0] + "..."
        claims.append(
            {
                "claim_id": claim_id,
                "source_uuid": source_uuid_from_id(source_id),
                "source_id": source_id,
                "chunk_id": chunk_id,
                "claim_text": claim_text,
                "normalized_claim": normalize_space(claim_text.lower()),
                "claim_type": "metric",
                "entities": extract_entities(claim_text),
                "concepts": concepts,
                "evidence_quote": evidence_quote,
                "evidence_hash": compute_evidence_hash(evidence_quote),
                "anchor": anchor,
                "confidence": 0.82 if evidence else 0.55,
                "verdict": "unreviewed",
                "contradiction_group": "",
                "created_at": now,
                "updated_at": now,
                # legacy fields
                "source_title": title,
                "page": relpath,
                "subject": title,
                "predicate": metric,
                "object": raw_value,
                "value": numeric,
                "unit": unit,
                "baseline": baseline,
                "evidence": anchor,
                "needs_review": needs_metric_review(raw_value, evidence, numeric),
            }
        )
    return claims


def extract_claims(vault: Path) -> list[dict[str, object]]:
    concept_names = {path.stem for path in (vault / "concepts").glob("*.md")}
    claims: list[dict[str, object]] = []
    for candidate in sorted((vault / "sources").glob("LLM-*.md")):
        path = source_page_path(vault, candidate)
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


def mark_stale_claims(claims_path: Path, stale_source_ids: set[str]) -> int:
    """Mark claims as stale when their source_id is in stale_source_ids.

    Returns the number of claims marked stale. Writes updated claims back.
    """
    claims = []
    for line in read_text(claims_path).splitlines():
        if not line.strip():
            continue
        claims.append(json.loads(line))
    marked = 0
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for claim in claims:
        if str(claim.get("source_id", "")) in stale_source_ids and str(claim.get("verdict", "")) != "stale":
            claim["verdict"] = "stale"
            claim["updated_at"] = now
            marked += 1
    write_jsonl(claims_path, claims)
    return marked


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
    output = ensure_within(
        args.output or vault / "claims" / "claims.jsonl",
        vault / "claims",
        "claim output must stay under claims/",
    )
    report_path = ensure_within(
        args.report or vault / "claims" / "claim-report.md",
        vault / "claims",
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
