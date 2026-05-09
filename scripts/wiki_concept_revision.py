#!/usr/bin/env python3
"""Revise concept pages from normalized wiki claims."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, parse_frontmatter, read_text, write_text


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
    if claim.get("claim_type") == "metric" and (
        not claim.get("baseline_key")
        or not claim.get("protocol_key")
        or "generic_metric_name" in reasons
    ):
        reasons.append("scientific_context_review")
    return sorted(set(str(reason) for reason in reasons if reason))


def is_review_approved(claim: dict[str, object]) -> bool:
    return str(claim.get("science_review", "")).lower() == "approved"


def claim_status_badge(claim: dict[str, object]) -> str:
    if bool(claim.get("needs_review")) and not is_review_approved(claim):
        return "review"
    if str(claim.get("science_review", "")).lower() == "rejected":
        return "contested"
    return "supported"


def semantic_section(concept_id: str, claims: list[dict[str, object]], include_review_required: bool) -> str:
    rows = []
    held_for_review = 0
    supporting = 0
    contested = 0
    stale = 0
    for claim in sorted(claims, key=lambda item: (str(item.get("source_id")), str(item.get("claim_id")))):
        reasons = review_reasons(claim)
        status = claim_status_badge(claim)
        if status == "supported":
            supporting += 1
        elif status == "contested":
            contested += 1
        else:
            stale += 1
        if reasons and not include_review_required and not is_review_approved(claim):
            held_for_review += 1
            continue
        if len(rows) >= 24:
            continue
        rows.append(
            "| [[{source_id}]] | {claim_type} | {status} | {claim} | {evidence} |".format(
                source_id=claim.get("source_id", ""),
                claim_type=claim.get("claim_type", ""),
                status=status,
                claim=claim_label(claim).replace("|", "/"),
                evidence=str(claim.get("evidence", "")).replace("|", "/"),
            )
        )
    table = "\n".join(rows) if rows else "| - | - | - | - | - |"
    return (
        "## Supporting Evidence\n\n"
        f"{START}\n"
        "| Source | Type | Status | Claim | Evidence |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"{table}\n"
        f"{END}\n\n"
        "## Revision Notes\n\n"
        "- This section is generated from `claims/claims.jsonl` and excludes claims that require second-pass scientific review unless they are marked `science_review: approved`.\n"
        f"- Claim counts: {supporting} supported, {contested} contested, {stale} needs-review.\n"
        f"- Held for review in this concept: {held_for_review}.\n"
        "- Treat cross-source comparisons as inference unless units, baselines, and evaluation protocol are aligned.\n"
    )


def update_frontmatter(text: str, supporting: int, contested: int, stale: int, concept_id: str) -> str:
    """Update concept frontmatter with claim counts."""
    if not text.startswith("---\n"):
        return text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return text
    fm = parts[1]
    body = parts[2]

    lines = fm.splitlines()
    new_lines = []
    updated_keys: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("supporting_claims:"):
            new_lines.append(f"supporting_claims: {supporting}")
            updated_keys.add("supporting_claims")
        elif stripped.startswith("contradicted_claims:"):
            new_lines.append(f"contradicted_claims: {contested}")
            updated_keys.add("contradicted_claims")
        elif stripped.startswith("stale_claims:"):
            new_lines.append(f"stale_claims: {stale}")
            updated_keys.add("stale_claims")
        elif stripped.startswith("updated_at:"):
            today = datetime.now().strftime("%Y-%m-%d")
            new_lines.append(f"updated_at: {today}")
            updated_keys.add("updated_at")
        elif stripped.startswith("updated:"):
            today = datetime.now().strftime("%Y-%m-%d")
            new_lines.append(f"updated: {today}")
            updated_keys.add("updated")
        else:
            new_lines.append(line)

    for key, value in [("supporting_claims", supporting), ("contradicted_claims", contested), ("stale_claims", stale)]:
        if key not in updated_keys:
            new_lines.append(f"{key}: {value}")

    return "---\n" + "\n".join(new_lines) + "\n---\n" + body


def replace_section(text: str, new_section: str) -> str:
    # Try new heading first
    heading = "## Supporting Evidence"
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
    # Fall back to old heading
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
    parser.add_argument("--only-affected", action="store_true", help="Only refresh concepts affected by stale items in the impact graph.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    claims_path = (args.claims or vault / "claims" / "claims.jsonl").resolve()
    claims = load_claims(claims_path)
    by_concept: dict[str, list[dict[str, object]]] = defaultdict(list)
    for claim in claims:
        for concept in claim.get("concepts", []):
            by_concept[str(concept)].append(claim)

    # Filter to only affected concepts if --only-affected
    if args.only_affected:
        try:
            from wiki_impact import build_edges, compute_stale_items
            edges = build_edges(vault)
            stale_items = compute_stale_items(vault, edges)
            stale_concepts = {
                item["item_ref"]
                for item in stale_items
                if item["item_type"] == "concept_section"
            }
            if stale_concepts:
                by_concept = {k: v for k, v in by_concept.items() if k in stale_concepts}
            else:
                by_concept = {}
        except ImportError:
            pass

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
        # Count claim statuses
        supporting = sum(1 for c in items if claim_status_badge(c) == "supported")
        contested = sum(1 for c in items if claim_status_badge(c) == "contested")
        stale = sum(1 for c in items if claim_status_badge(c) == "review")

        before = read_text(path)
        after = update_frontmatter(before, supporting, contested, stale, concept_id)
        after = replace_section(after, semantic_section(concept_id, items, args.include_review_required))
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
