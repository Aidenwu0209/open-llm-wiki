#!/usr/bin/env python3
"""Find contradiction candidates in normalized wiki claims."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, json_dump, read_text, write_text


def load_claims(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def normalize_predicate(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    text = re.sub(r"\b(reported|claim|value|metric|base|big|model)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def numeric_conflicts(claims: list[dict[str, object]], tolerance: float) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for claim in claims:
        if claim.get("claim_type") != "metric" or claim.get("value") is None:
            continue
        predicate = str(claim.get("metric_key") or normalize_predicate(str(claim.get("predicate", ""))))
        unit = str(claim.get("normalized_unit") or claim.get("unit", "")).lower()
        if not predicate or not unit:
            continue
        for concept in claim.get("concepts", []):
            groups[(str(concept), predicate, unit)].append(claim)

    conflicts: list[dict[str, object]] = []
    for (concept, predicate, unit), items in sorted(groups.items()):
        source_ids = {str(item.get("source_id")) for item in items}
        if len(source_ids) < 2:
            continue
        values = [float(item.get("normalized_value") if item.get("normalized_value") is not None else item["value"]) for item in items]
        low, high = min(values), max(values)
        if high == 0:
            continue
        spread = (high - low) / abs(high)
        if spread > tolerance:
            conflicts.append(
                {
                    "concept": concept,
                    "predicate": predicate,
                    "unit": unit,
                    "low": low,
                    "high": high,
                    "spread": round(spread, 4),
                    "claims": [item["claim_id"] for item in items],
                    "sources": sorted(source_ids),
                    "status": "CANDIDATE_REVIEW_REQUIRED",
                }
            )
    return conflicts


def contradiction_markers(vault: Path) -> list[str]:
    markers: list[str] = []
    for path in sorted((vault / "concepts").glob("*.md")):
        for number, line in enumerate(read_text(path).splitlines(), 1):
            if "[CONTRADICTION" in line:
                markers.append(f"{path.relative_to(vault).as_posix()}#L{number}: {line.strip()}")
    return markers


def markdown_report(vault: Path, conflicts: list[dict[str, object]], markers: list[str]) -> str:
    verdict = "REVIEW_REQUIRED" if conflicts or markers else "NO_CONFIRMED_CONTRADICTION"
    lines = [
        "# Claim Contradiction Report",
        f"- date: {datetime.now().strftime('%Y-%m-%d')}",
        f"- vault: {vault}",
        f"- verdict: {verdict}",
        f"- numeric_conflict_candidates: {len(conflicts)}",
        f"- explicit_markers: {len(markers)}",
        "",
        "## Numeric Conflict Candidates",
    ]
    if not conflicts:
        lines.append("- none")
    else:
        for conflict in conflicts:
            lines.append(
                "- "
                + f"{conflict['concept']} / {conflict['predicate']} ({conflict['unit']}): "
                + f"{conflict['low']}..{conflict['high']} across {', '.join(conflict['sources'])}"
            )
    lines.append("\n## Explicit Contradiction Markers")
    if not markers:
        lines.append("- none")
    else:
        lines.extend(f"- {marker}" for marker in markers)
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "Candidates are not automatically treated as contradictions. A reviewer must verify protocol, unit, and baseline compatibility before adding `[CONTRADICTION YYYY-MM-DD]` to a concept page.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Find contradiction candidates in claim graphs.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--claims", type=Path, help="Defaults to <vault>/claims/claims.jsonl.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.35,
        help="Relative numeric spread threshold for candidate conflicts. Defaults to 0.35.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write qa-reports/claim-contradictions-YYYY-MM-DD.md, or --report when provided.",
    )
    parser.add_argument("--report", type=Path, help="Defaults to <vault>/qa-reports/claim-contradictions-YYYY-MM-DD.md.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument(
        "--fail-on-candidate",
        action="store_true",
        help="Exit non-zero when numeric contradiction candidates are found.",
    )
    args = parser.parse_args()

    vault = args.vault.resolve()
    claims_path = (args.claims or vault / "claims" / "claims.jsonl").resolve()
    claims = load_claims(claims_path)
    conflicts = numeric_conflicts(claims, args.tolerance)
    markers = contradiction_markers(vault)
    if args.format == "json":
        print(json_dump({"conflicts": conflicts, "markers": markers}))
    else:
        print(markdown_report(vault, conflicts, markers))
    if args.write_report:
        report = ensure_within(
            args.report or vault / "qa-reports" / f"claim-contradictions-{datetime.now().strftime('%Y-%m-%d')}.md",
            vault,
            "contradiction report must stay inside the vault",
        )
        write_text(report, markdown_report(vault, conflicts, markers))
        print(f"report: {report}")
    return 1 if args.fail_on_candidate and conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
