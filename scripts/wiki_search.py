#!/usr/bin/env python3
"""Local markdown search for open-llm-wiki vaults."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiki_common import json_dump, load_pages, score_text


def snippets(text: str, terms: list[str], limit: int = 2) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    hits: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(term in lower for term in terms):
            hits.append(line[:240])
        if len(hits) >= limit:
            break
    return hits


def claim_search_text(row: dict[str, object]) -> str:
    fields = [
        "claim_id",
        "claim_text",
        "normalized_claim",
        "evidence_quote",
        "evidence",
        "anchor",
        "page",
        "source_id",
        "source_title",
        "verdict",
    ]
    values: list[str] = []
    for field in fields:
        value = row.get(field)
        if value is not None:
            values.append(str(value))
    concepts = row.get("concepts")
    if isinstance(concepts, list):
        values.extend(str(item) for item in concepts)
    return "\n".join(values)


def load_claim_results(vault: Path, terms: list[str]) -> list[dict[str, object]]:
    claims_path = vault / "claims" / "claims.jsonl"
    if not claims_path.exists():
        return []

    results: list[dict[str, object]] = []
    with claims_path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            text = claim_search_text(row)
            score = score_text(terms, text)
            if score <= 0:
                continue
            claim_id = str(row.get("claim_id") or f"line-{line_number}")
            results.append(
                {
                    "type": "claim",
                    "path": "claims/claims.jsonl",
                    "title": claim_id,
                    "score": score,
                    "snippets": snippets(text, terms),
                    "claim_id": claim_id,
                    "source_id": row.get("source_id", ""),
                    "evidence": row.get("evidence") or row.get("anchor") or row.get("page", ""),
                    "needs_review": bool(row.get("needs_review", False)),
                }
            )
    return results


def search(vault: Path, query: str, limit: int) -> list[dict[str, object]]:
    terms = [term.lower() for term in query.split() if term.strip()]
    results: list[dict[str, object]] = []
    for page in load_pages(vault, folders=("sources", "concepts")):
        text = page.frontmatter.get("title", "") + "\n" + page.body
        score = score_text(terms, text)
        if score <= 0:
            continue
        results.append(
            {
                "path": page.relpath,
                "title": page.frontmatter.get("title", page.path.stem),
                "score": score,
                "snippets": snippets(text, terms),
            }
        )
    results.extend(load_claim_results(vault, terms))
    results.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return results[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Search an open-llm-wiki vault.")
    parser.add_argument("vault", type=Path, help="Vault root to search.")
    parser.add_argument("query", help="Search terms to match against source pages, concept pages, and claim evidence.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of matching pages to return.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format for search results.")
    args = parser.parse_args()

    results = search(args.vault.resolve(), args.query, args.limit)
    if args.format == "json":
        print(json_dump({"query": args.query, "results": results}))
        return 0

    print(f"# Search: {args.query}")
    if not results:
        print("- no matches")
        return 1
    for item in results:
        print(f"\n## {item['title']}")
        print(f"- path: `{item['path']}`")
        print(f"- score: {item['score']}")
        if item.get("type") == "claim":
            print(f"- type: claim")
            if item.get("evidence"):
                print(f"- evidence: `{item['evidence']}`")
            print(f"- needs review: {str(item.get('needs_review', False)).lower()}")
        for line in item["snippets"]:
            print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
