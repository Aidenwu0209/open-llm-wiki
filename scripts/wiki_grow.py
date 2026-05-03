#!/usr/bin/env python3
"""Run the semantic self-growth loop for an open-llm-wiki vault."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover sources, extract and normalize claims, QA them, scan contradictions, revise concepts, and lint.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--discover-sources", action="store_true", help="Refresh _state/source-registry.jsonl first.")
    parser.add_argument("--ingest-corpus", action="store_true", help="First ingest raw/*_markdown/combined.md files.")
    parser.add_argument("--plan-queue", action="store_true", help="Plan durable growth queue tasks.")
    parser.add_argument("--queue-cadence", choices=["now", "daily", "weekly", "monthly"], default="now", help="Cadence used when planning queue tasks.")
    parser.add_argument("--skip-queue", action="store_true", help="Do not plan queue tasks when called by the queue runner.")
    parser.add_argument("--apply-concept-revision", action="store_true")
    parser.add_argument("--science-review", action="store_true", help="Write a second-pass scientific review packet.")
    parser.add_argument("--semantic-fail-on", choices=["none", "p0", "p1", "p2"], default="p1")
    parser.add_argument("--skip-lint", action="store_true")
    args = parser.parse_args()

    vault = str(args.vault.resolve())
    if args.discover_sources:
        run([sys.executable, str(SCRIPTS / "wiki_discover_sources.py"), vault])
    if args.ingest_corpus:
        run([sys.executable, str(SCRIPTS / "wiki_ingest_corpus.py"), vault, "--resume"])
        if args.discover_sources:
            run([sys.executable, str(SCRIPTS / "wiki_discover_sources.py"), vault])
    if args.plan_queue and not args.skip_queue:
        run([sys.executable, str(SCRIPTS / "wiki_queue.py"), vault, "plan", "--cadence", args.queue_cadence])
    run([sys.executable, str(SCRIPTS / "wiki_claims.py"), vault])
    run([sys.executable, str(SCRIPTS / "wiki_normalize_metrics.py"), vault, "--in-place"])
    run(
        [
            sys.executable,
            str(SCRIPTS / "wiki_semantic_qa.py"),
            vault,
            "--write-report",
            "--fail-on",
            args.semantic_fail_on,
        ]
    )
    if args.science_review:
        run([sys.executable, str(SCRIPTS / "wiki_science_review.py"), vault, "--queue", "--write-report"])
    run([sys.executable, str(SCRIPTS / "wiki_contradictions.py"), vault, "--write-report"])
    revision = [sys.executable, str(SCRIPTS / "wiki_concept_revision.py"), vault]
    if args.apply_concept_revision:
        revision.append("--apply")
    run(revision)
    if not args.skip_lint:
        run([sys.executable, str(SCRIPTS / "wiki_lint.py"), vault, "--fail-on", "p1"])
    print("semantic growth loop completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
