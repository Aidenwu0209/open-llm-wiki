#!/usr/bin/env python3
"""Revise concept pages from normalized wiki claims."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_vault_subpath, read_text, write_text


START = "<!-- open-llm-wiki:semantic-claims:start -->"
END = "<!-- open-llm-wiki:semantic-claims:end -->"


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
    if claim.get("claim_type") == "metric" and (not claim.get("baseline_key") or "generic_metric_name" in reasons):
        reasons.append("scientific_context_review")
    return sorted(set(str(reason) for reason in reasons if reason))


def is_review_approved(claim: dict[str, object]) -> bool:
    return str(claim.get("science_review", "")).lower() == "approved"


def semantic_section(concept_id: str, claims: list[dict[str, object]], include_review_required: bool) -> str:
    rows = []
    held_for_review = 0
    for claim in sorted(claims, key=lambda item: (str(item.get("source_id")), str(item.get("claim_id")))):
        reasons = review_reasons(claim)
        if reasons and not include_review_required and not is_review_approved(claim):
            held_for_review += 1
            continue
        if len(rows) >= 24:
            break
        rows.append(
            "| [[{source_id}]] | {claim_type} | {claim} | {evidence} |".format(
                source_id=claim.get("source_id", ""),
                claim_type=claim.get("claim_type", ""),
                claim=claim_label(claim).replace("|", "/"),
                evidence=str(claim.get("evidence", "")).replace("|", "/"),
            )
        )
    table = "\n".join(rows) if rows else "| - | - | - | - |"
    return (
        "## Semantic Claim Matrix\n\n"
        f"{START}\n"
        "| Source | Type | Claim | Evidence |\n"
        "| --- | --- | --- | --- |\n"
        f"{table}\n"
        f"{END}\n\n"
        "## Revision Notes\n\n"
        "- This section is generated from `claims/claims.jsonl` and excludes claims that require second-pass scientific review unless they are marked `science_review: approved`.\n"
        f"- Held for review in this concept: {held_for_review}.\n"
        "- Treat cross-source comparisons as inference unless units, baselines, and evaluation protocol are aligned.\n"
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
    parser.add_argument("--apply", action="store_true")
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
        path = ensure_vault_subpath(
            vault / "concepts" / f"{concept_id}.md",
            vault,
            "concepts",
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
        log_path = vault / "log.md"
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
