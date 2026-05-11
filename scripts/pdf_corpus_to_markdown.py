#!/usr/bin/env python3
"""Batch-convert a directory of PDFs to Markdown through local or cloud parsers."""

from __future__ import annotations

import argparse
import csv
import os
import traceback
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from pdf_to_markdown import DEFAULT_API_URL, DEFAULT_TOKEN_ENV, PARSER_AUTO, convert


LOG_FIELDS = ["timestamp_utc", "status", "input", "output", "message"]


def write_log_row(log_path: Path, row: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    exists = log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS, delimiter="\t")
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def status_row(status: str, input_path: Path, output_dir: Path, message: str) -> dict[str, str]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "input": str(input_path),
        "output": str(output_dir),
        "message": message.replace("\n", " "),
    }


def convert_one(args: argparse.Namespace, input_path: Path, output_dir: Path) -> int:
    convert_args = Namespace(
        input=input_path,
        output=output_dir,
        api_url=args.api_url,
        token_env=args.token_env,
        parser=args.parser,
        file_type=0,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        max_bytes=args.max_bytes,
        options_file=args.options_file,
        combined_name=args.combined_name,
        fail_on_suspicious_text=args.fail_on_suspicious_text,
        download_images=args.download_images,
        dry_run=False,
    )
    return convert(convert_args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-convert PDFs in a directory to Markdown.")
    parser.add_argument("input_dir", type=Path, help="Directory containing PDF files.")
    parser.add_argument("--output-root", type=Path, help="Directory for <pdf-stem>_markdown outputs.")
    parser.add_argument("--pattern", default="*.pdf", help="Input glob pattern, relative to input_dir.")
    parser.add_argument("--api-url", default=os.environ.get("OPEN_LLM_WIKI_LAYOUT_API_URL", DEFAULT_API_URL))
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument(
        "--parser",
        choices=["auto", "local-text", "layout-api"],
        default=PARSER_AUTO,
        help="Parser backend. auto is local-text; use layout-api explicitly for external parsing.",
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay", type=int, default=5)
    parser.add_argument("--max-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--options-file", type=Path)
    parser.add_argument("--combined-name", default="combined.md")
    parser.add_argument("--log", type=Path, help="TSV log path.")
    parser.add_argument("--force", action="store_true", help="Reprocess PDFs even when combined Markdown exists.")
    parser.add_argument("--fail-on-suspicious-text", action="store_true")
    parser.add_argument("--no-download-images", dest="download_images", action="store_false")
    parser.add_argument("--dry-run", action="store_true", help="Print planned work without making API calls.")
    parser.set_defaults(download_images=True)
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input_dir not found or not a directory: {input_dir}")
    output_root = (args.output_root or input_dir).resolve()
    log_path = (args.log or (output_root / "pdf-corpus-to-markdown.tsv")).resolve()
    pdfs = sorted(path for path in input_dir.glob(args.pattern) if path.is_file())
    if not pdfs:
        raise SystemExit(f"no PDFs matched {args.pattern!r} in {input_dir}")

    failures = 0
    total = len(pdfs)
    for index, pdf in enumerate(pdfs, 1):
        output_dir = output_root / f"{pdf.stem}_markdown"
        combined = output_dir / args.combined_name
        if combined.exists() and not args.force:
            message = "skipped; combined Markdown already exists"
            print(f"SKIP {pdf.name}: {message}")
            if not args.dry_run:
                write_log_row(log_path, status_row("SKIP", pdf, output_dir, message))
            continue
        if args.dry_run:
            print(f"PLAN {pdf} -> {output_dir}")
            continue
        try:
            message = f"converting {index}/{total}"
            print(f"START {pdf.name}: {message}; output={output_dir}", flush=True)
            write_log_row(log_path, status_row("START", pdf, output_dir, message))
            convert_one(args, pdf, output_dir)
            write_log_row(log_path, status_row("OK", pdf, output_dir, "converted"))
        except SystemExit as exc:  # pragma: no cover - exercised by real API failures.
            failures += 1
            message = str(exc) or f"exited with {exc.code}"
            print(f"FAIL {pdf.name}: {message}")
            write_log_row(log_path, status_row("FAIL", pdf, output_dir, message))
        except Exception as exc:  # pragma: no cover - exercised by real API failures.
            failures += 1
            print(f"FAIL {pdf.name}: {exc}")
            write_log_row(log_path, status_row("FAIL", pdf, output_dir, traceback.format_exc()))

    if args.dry_run:
        print(f"planned PDFs: {len(pdfs)}")
        return 0
    print(f"processed PDFs: {len(pdfs)}; failures: {failures}; log: {log_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
