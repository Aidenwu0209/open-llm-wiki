#!/usr/bin/env python3
"""Smoke evaluation for the open-llm-wiki runtime."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path = ROOT) -> str:
    result = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit(result.returncode)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Run runtime smoke evaluations.")
    parser.add_argument("--vault", type=Path, default=ROOT / "examples" / "minimal-vault")
    args = parser.parse_args()

    vault = args.vault.resolve()
    run([sys.executable, "scripts/wiki_lint.py", str(vault), "--fail-on", "p1"])
    search_output = run([sys.executable, "scripts/wiki_search.py", str(vault), "attention transformer", "--limit", "2"])
    if "Attention Is All You Need" not in search_output:
        raise SystemExit("search eval did not find expected source page")
    proposal = run(
        [
            sys.executable,
            "scripts/wiki_writeback.py",
            str(vault),
            "--target",
            "concepts/attention-mechanisms.md",
            "--query",
            "Why did attention become central?",
            "--body",
            "Attention became central because it created direct token-to-token interaction paths. [[LLM-0001]]",
        ]
    )
    if "Query-Derived Note" not in proposal or "Proposed log entry" not in proposal:
        raise SystemExit("writeback eval did not produce a reviewable proposal")

    with tempfile.TemporaryDirectory() as tmp:
        growth_vault = Path(tmp) / "growth-vault"
        shutil.copytree(vault, growth_vault)
        run(
            [
                sys.executable,
                "scripts/wiki_grow.py",
                str(growth_vault),
                "--discover-sources",
                "--plan-queue",
                "--queue-cadence",
                "weekly",
                "--science-review",
                "--apply-concept-revision",
            ]
        )
        run([sys.executable, "scripts/wiki_queue.py", str(growth_vault), "list"])
        run([sys.executable, "scripts/wiki_lint.py", str(growth_vault), "--fail-on", "p1"])

        test_vault = Path(tmp) / "vault"
        run([sys.executable, "scripts/wiki_init.py", str(test_vault), "--repo-root", str(ROOT)])
        run([sys.executable, "scripts/wiki_lint.py", str(test_vault), "--fail-on", "p1"])

        corpus_vault = Path(tmp) / "corpus-vault"
        run([sys.executable, "scripts/wiki_init.py", str(corpus_vault), "--repo-root", str(ROOT)])
        raw_dir = corpus_vault / "raw"
        parsed_dir = raw_dir / "2501.00001_markdown"
        parsed_dir.mkdir(parents=True)
        (raw_dir / "2501.00001.pdf").write_bytes(b"%PDF-1.4\n% synthetic placeholder\n")
        (parsed_dir / "combined.md").write_text(
            "# DeepSeek Synthetic Evaluation Paper\n\n"
            "Abstract\n\n"
            "This paper studies DeepSeek benchmark evaluation for a synthetic model. "
            "It reports 7B parameters and HumanEval accuracy at 71% under a stated protocol. "
            "The content is long enough for corpus ingestion, source discovery, claim extraction, "
            "metric normalization, semantic QA, and concept revision.\n\n"
            "Results\n\n"
            "HumanEval accuracy reaches 71% with baseline model 1.\n\n"
            "Architecture\n\n"
            "The model has 7B parameters for the experiment.\n",
            encoding="utf-8",
        )
        run(
            [
                sys.executable,
                "scripts/wiki_grow.py",
                str(corpus_vault),
                "--discover-sources",
                "--ingest-corpus",
                "--semantic-fail-on",
                "none",
                "--skip-lint",
            ]
        )
        registry_rows = [
            json.loads(line)
            for line in (corpus_vault / "_state" / "source-registry.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        kinds = {str(row.get("kind")) for row in registry_rows}
        if not {"raw", "source"}.issubset(kinds):
            raise SystemExit("grow eval did not refresh source registry after corpus ingest")

    print("runtime eval passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
