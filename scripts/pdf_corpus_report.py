#!/usr/bin/env python3
"""Report and validate PDF-to-Markdown corpus conversion outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdf_to_markdown import SUSPICIOUS_TEXT_TOKENS


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect_outputs(raw_dir: Path, combined_name: str) -> tuple[list[Path], list[Path], list[Path]]:
    pdfs = sorted(raw_dir.glob("*.pdf"))
    combined = sorted(raw_dir.glob(f"*_markdown/{combined_name}"))
    manifests = sorted(raw_dir.glob("*_markdown/manifest.json"))
    return pdfs, combined, manifests


def parse_attempts(manifests: list[Path]) -> list[int]:
    attempts: list[int] = []
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("attempts")
        if isinstance(value, int):
            attempts.append(value)
    return attempts


def parser_warnings(manifests: list[Path]) -> list[tuple[Path, str]]:
    warnings: list[tuple[Path, str]] = []
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("warnings", [])
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str) and item.strip():
                warnings.append((path, item.strip()))
    return warnings


def suspicious_files(combined_files: list[Path]) -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    for path in combined_files:
        text = read_text(path)
        count = sum(text.count(token) for token in SUSPICIOUS_TEXT_TOKENS)
        if count:
            hits.append((path, count))
    return hits


def short_files(combined_files: list[Path], min_bytes: int) -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    for path in combined_files:
        size = path.stat().st_size
        if size < min_bytes:
            hits.append((path, size))
    return hits


def semantic_matches(combined_files: list[Path], terms: list[str]) -> int:
    if not terms:
        return 0
    count = 0
    for path in combined_files:
        text = read_text(path)
        if any(term in text for term in terms):
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate converted PDF corpus outputs.")
    parser.add_argument("raw_dir", type=Path, help="Directory containing PDFs and *_markdown outputs.")
    parser.add_argument("--combined-name", default="combined.md")
    parser.add_argument("--expect-count", type=int)
    parser.add_argument("--semantic-term", action="append", default=[])
    parser.add_argument(
        "--min-combined-bytes",
        "--min-bytes",
        dest="min_combined_bytes",
        type=int,
        default=100,
        help="Flag combined Markdown outputs smaller than this many bytes.",
    )
    parser.add_argument("--fail-on-missing", action="store_true")
    parser.add_argument("--fail-on-parser-warnings", action="store_true")
    parser.add_argument("--fail-on-short", action="store_true")
    parser.add_argument("--fail-on-suspicious", action="store_true")
    args = parser.parse_args()
    if args.min_combined_bytes < 0:
        raise SystemExit("--min-combined-bytes must be zero or greater")

    raw_dir = args.raw_dir.resolve()
    if not raw_dir.exists() or not raw_dir.is_dir():
        raise SystemExit(f"raw_dir not found or not a directory: {raw_dir}")

    pdfs, combined, manifests = collect_outputs(raw_dir, args.combined_name)
    attempts = parse_attempts(manifests)
    warnings = parser_warnings(manifests)
    suspicious = suspicious_files(combined)
    short = short_files(combined, args.min_combined_bytes)
    semantic = semantic_matches(combined, args.semantic_term)
    total_bytes = sum(path.stat().st_size for path in combined)

    print(f"raw_dir: {raw_dir}")
    print(f"pdfs: {len(pdfs)}")
    print(f"combined_files: {len(combined)}")
    print(f"manifests: {len(manifests)}")
    print(f"total_combined_bytes: {total_bytes}")
    if attempts:
        print(f"attempts_min: {min(attempts)}")
        print(f"attempts_max: {max(attempts)}")
        print(f"attempts_sum: {sum(attempts)}")
    else:
        print("attempts_min: n/a")
        print("attempts_max: n/a")
        print("attempts_sum: n/a")
    if args.semantic_term:
        print(f"semantic_matches: {semantic}")
        print(f"semantic_terms: {', '.join(args.semantic_term)}")
    print(f"parser_warnings: {len(warnings)}")
    for path, warning in warnings:
        print(f"parser_warning: {path}: {warning}")
    print(f"suspicious_files: {len(suspicious)}")
    for path, count in suspicious:
        print(f"suspicious: {path} tokens={count}")
    print(f"short_files: {len(short)}")
    print(f"min_combined_bytes: {args.min_combined_bytes}")
    for path, size in short:
        print(f"short: {path} bytes={size}")

    failures: list[str] = []
    if args.expect_count is not None:
        if len(pdfs) != args.expect_count:
            failures.append(f"expected {args.expect_count} PDFs, found {len(pdfs)}")
        if len(combined) != args.expect_count:
            failures.append(f"expected {args.expect_count} combined files, found {len(combined)}")
        if len(manifests) != args.expect_count:
            failures.append(f"expected {args.expect_count} manifests, found {len(manifests)}")
    if args.fail_on_missing and (len(combined) != len(pdfs) or len(manifests) != len(pdfs)):
        failures.append("not every PDF has combined Markdown and a manifest")
    if args.fail_on_parser_warnings and warnings:
        failures.append("parser warnings found")
    if args.fail_on_short and short:
        failures.append("suspiciously short combined Markdown outputs found")
    if args.fail_on_suspicious and (suspicious or short):
        failures.append("suspicious text markers or suspiciously short outputs found")
    if args.semantic_term and semantic != len(combined):
        failures.append("not every combined Markdown file matched the semantic terms")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
