#!/usr/bin/env python3
"""Revise concept pages from normalized wiki claims."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, read_text, write_text


START = "<!-- open-llm-wiki:semantic-claims:start -->"
END = "<!-- open-llm-wiki:semantic-claims:end -->"

# Verdict categories for concept synthesis filtering
VERDICT_ALLOWED_FOR_SYNTHESIS = frozenset({"supported"})
VERDICT_REQUIRES_REVIEW = frozenset({"weak", "unreviewed"})
VERDICT_EXCLUDED_FROM_SYNTHESIS = frozenset({"contradicted", "retracted", "stale"})


def load_claims(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def claim_label(claim: dict[str, object]) -> str:
    if claim.get("claim_type") == "contribution":
        return str(claim.get("object", ""))[:160]
    predicate = str(claim.get("predicate", "claim"))
    obj = str(claim.get("object", ""))
    return f"{predicate}: {obj}"[:160]


def review_reasons(claim: dict[str, object]) -> list[str]:
    reasons = list(claim.get("normalization_warnings", []))
    if claim.get("needs_review"):
        reasons.append("claim_marked_needs_review")
    if claim.get("claim_type") == "metric" and (
        not claim.get("baseline_key")
        or not claim.get("protocol_key")
        or "generic_metric_name" in reasons
    ):
        reasons.append("scientific_context_review")
    return sorted(set(str(reason) for reason in reasons if reason))


def is_review_approved(claim: dict[str, object]) -> bool:
    return str(claim.get("science_review", "")).lower() == "approved"


def semantic_section(concept_id: str, claims: list[dict[str, object]], include_review_required: bool) -> str:
    rows = []
    held_for_review = 0
    excluded_count = 0
    review_queue_items: list[str] = []
    for claim in sorted(claims, key=lambda item: (str(item.get("source_id")), str(item.get("claim_id")))):
        verdict = str(claim.get("verdict", "unreviewed"))

        # Verdict-based filtering: contradicted/retracted/stale never enter synthesis
        if verdict in VERDICT_EXCLUDED_FROM_SYNTHESIS:
            excluded_count += 1
            continue

        # weak/unreviewed only enter review queue unless explicitly approved
        if verdict in VERDICT_REQUIRES_REVIEW:
            if not include_review_required and not is_review_approved(claim):
                review_queue_items.append(
                    f"| [[{claim.get('source_id', '')}]] | {claim.get('claim_type', '')} | {claim.get('claim_id', '')} | {verdict} |"
                )
                held_for_review += 1
                continue

        # supported claims (or approved review-required) pass through
        reasons = review_reasons(claim)
        if reasons and not include_review_required and not is_review_approved(claim):
            held_for_review += 1
            continue
        if len(rows) >= 24:
            break
        rows.append(
            "| [[{source_id}]] | {claim_type} | {claim} | {verdict} | {evidence} |".format(
                source_id=claim.get("source_id", ""),
                claim_type=claim.get("claim_type", ""),
                claim=claim_label(claim).replace("|", "/"),
                verdict=verdict,
                evidence=str(claim.get("evidence", "")).replace("|", "/"),
            )
        )
    table = "\n".join(rows) if rows else "| - | - | - | - | - |"
    review_table = "\n".join(review_queue_items) if review_queue_items else "- none"

    return (
        "## Semantic Claim Matrix\n\n"
        f"{START}\n"
        "| Source | Type | Claim | Verdict | Evidence |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"{table}\n"
        f"{END}\n\n"
        "## Revision Notes\n\n"
        "- This section is generated from `claims/claims.jsonl` and only uses `supported` claims by default.\n"
        f"- Held for review in this concept: {held_for_review}.\n"
        f"- Excluded from synthesis (contradicted/retracted/stale): {excluded_count}.\n"
        "- Treat cross-source comparisons as inference unless units, baselines, and evaluation protocol are aligned.\n\n"
        "## Review Queue\n\n"
        "Claims with `weak` or `unreviewed` verdict awaiting confirmation:\n\n"
        "| Source | Type | Claim | Verdict |\n"
        "| --- | --- | --- | --- |\n"
        f"{review_table}\n"
    )


def replace_section(text: str, new_section: str) -> str:
    heading = "## Semantic Claim Matrix"
    if heading in text and START in text and END in text:
        start = text.index(heading)
        end = text.index(END, start) + len(END)
        tail = text[end:]
        while tail.lstrip("\n").startswith("## Revision Notes"):
            stripped = tail.lstrip("\n")
            next_heading = stripped.find("\n## ", len("## Revision Notes"))
            if next_heading == -1:
                tail = ""
                break
            tail = stripped[next_heading:]
        return text[:start].rstrip() + "\n\n" + new_section.rstrip() + "\n\n" + tail.lstrip("\n")
    marker = "\n## Open Questions"
    if marker in text:
        before, after = text.split(marker, 1)
        return before.rstrip() + "\n\n" + new_section.rstrip() + marker + after
    return text.rstrip() + "\n\n" + new_section.rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Update concept pages from normalized claims.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--claims", type=Path, help="Defaults to <vault>/claims/claims.jsonl.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updated concept pages and log entries. Omit for preview mode, which reports changes without writing files.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum concept pages to process; 0 means all.")
    parser.add_argument("--include-review-required", action="store_true", help="Include claims that have not passed second-pass scientific review.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    claims_path = (args.claims or vault / "claims" / "claims.jsonl").resolve()
    claims = load_claims(claims_path)
    by_concept: dict[str, list[dict[str, object]]] = defaultdict(list)
    for claim in claims:
        for concept in claim.get("concepts", []):
            by_concept[str(concept)].append(claim)

    changed: list[str] = []
    for index, (concept_id, items) in enumerate(sorted(by_concept.items()), 1):
        if args.limit and index > args.limit:
            break
        path = ensure_within(
            vault / "concepts" / f"{concept_id}.md",
            vault / "concepts",
            "concept revision target must stay under concepts/",
        )
        if not path.exists():
            continue
        before = read_text(path)
        after = replace_section(before, semantic_section(concept_id, items, args.include_review_required))
        if before != after:
            changed.append(path.relative_to(vault).as_posix())
            if args.apply:
                write_text(path, after)

    if args.apply and changed:
        log_path = ensure_within(
            vault / "log.md",
            vault,
            "concept revision log output must stay inside the vault",
        )
        log = read_text(log_path) if log_path.exists() else "# Wiki Log\n"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entries = "\n".join(
            f"[{stamp}] concept-update | {path} | semantic-claim-revision | refreshed semantic claim matrix"
            for path in changed
        )
        write_text(log_path, log.rstrip() + "\n" + entries + "\n")

    print("# Concept Revision")
    print(f"- mode: {'apply' if args.apply else 'preview'}")
    print(f"- changed: {len(changed)}")
    for path in changed:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
