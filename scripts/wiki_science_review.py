#!/usr/bin/env python3
"""Prepare second-pass scientific review packets for human or LLM reviewers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, json_dump, read_text, write_text


def load_claims(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def review_items(claims: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    candidates = []
    for claim in claims:
        warnings = list(claim.get("normalization_warnings", []))
        if claim.get("needs_review"):
            warnings.append("claim_marked_needs_review")
        if claim.get("claim_type") == "metric" and (
            not claim.get("baseline_key")
            or not claim.get("protocol_key")
            or "generic_metric_name" in warnings
        ):
            warnings.append("scientific_context_review")
        if warnings:
            item = dict(claim)
            item["review_reasons"] = sorted(set(warnings))
            item["review_id"] = f"{item.get('source_id')}-{item.get('claim_id')}"
            item["review_status"] = "pending"
            item["review_decision"] = ""
            item["reviewed_by"] = ""
            item["reviewed_at"] = ""
            item["review_questions"] = [
                "Does the claim preserve the source meaning?",
                "Are metric, unit, protocol, and baseline comparable?",
                "May this claim be used as concept-page evidence without adding unsupported inference?",
            ]
            candidates.append(item)
    candidates.sort(key=lambda item: (str(item.get("source_id")), str(item.get("claim_id"))))
    return candidates[:limit] if limit else candidates


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def markdown_report(vault: Path, items: list[dict[str, object]]) -> str:
    verdict = "REVIEW_REQUIRED" if items else "PASS"
    lines = [
        "# Second-Pass Scientific Review",
        f"- date: {datetime.now().strftime('%Y-%m-%d')}",
        f"- vault: {vault}",
        "- reviewer_type: human-or-second-llm",
        f"- review_items: {len(items)}",
        f"- verdict: {verdict}",
        "",
        "## Review Queue",
    ]
    if not items:
        lines.append("- none")
    else:
        for item in items:
            lines.append(
                "- "
                + f"{item.get('source_id')} {item.get('claim_id')}: "
                + f"{item.get('predicate')} -> {item.get('object')} "
                + f"({', '.join(item.get('review_reasons', []))}) "
                + f"evidence={item.get('evidence')}"
            )
    lines.extend(
        [
            "",
            "## Instructions For Reviewer",
            "",
            "For each queued item, verify whether the claim preserves the source meaning, whether the metric/protocol/baseline are comparable, and whether the concept page may use it as evidence. Mark unsupported claims before concept writeback.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a second-pass scientific review queue and report.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--claims", type=Path, help="Defaults to <vault>/claims/claims.jsonl.")
    parser.add_argument("--queue", action="store_true", help="Write _state/science-review-queue.jsonl.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--report", type=Path, help="Defaults to <vault>/qa-reports/science-review-YYYY-MM-DD.md.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--fail-on-review-required", action="store_true")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    vault = args.vault.resolve()
    claims_path = (args.claims or vault / "claims" / "claims.jsonl").resolve()
    items = review_items(load_claims(claims_path), args.limit)
    if args.queue:
        queue_path = vault / "_state" / "science-review-queue.jsonl"
        write_jsonl(queue_path, items)
    if args.write_report:
        report = ensure_within(
            args.report or vault / "qa-reports" / f"science-review-{datetime.now().strftime('%Y-%m-%d')}.md",
            vault,
            "science review report must stay inside the vault",
        )
        write_text(report, markdown_report(vault, items))
        print(f"report: {report}")
    if args.format == "json":
        print(json_dump({"review_items": len(items), "items": items}))
    else:
        print(markdown_report(vault, items))
    return 1 if args.fail_on_review_required and items else 0


if __name__ == "__main__":
    raise SystemExit(main())
