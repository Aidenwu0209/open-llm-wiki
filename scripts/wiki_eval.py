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

        contradiction_vault = Path(tmp) / "contradiction-vault"
        (contradiction_vault / "claims").mkdir(parents=True)
        rows = [
            {
                "claim_id": "claim-a",
                "source_id": "LLM-0001",
                "claim_type": "metric",
                "predicate": "Accuracy",
                "object": "not parsed",
                "value": None,
                "unit": "",
                "metric_key": "accuracy",
                "normalized_value": 10.0,
                "normalized_unit": "score",
                "unit_family": "score",
                "concepts": ["evals"],
            },
            {
                "claim_id": "claim-b",
                "source_id": "LLM-0002",
                "claim_type": "metric",
                "predicate": "Accuracy",
                "object": "not parsed",
                "value": None,
                "unit": "",
                "metric_key": "accuracy",
                "normalized_value": 20.0,
                "normalized_unit": "score",
                "unit_family": "score",
                "concepts": ["evals"],
            },
        ]
        (contradiction_vault / "claims" / "claims.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        contradiction_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_contradictions.py",
                str(contradiction_vault),
                "--format",
                "json",
                "--fail-on-candidate",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if contradiction_result.returncode == 0:
            raise SystemExit("contradiction eval did not fail on normalized-value conflict")
        conflicts = json.loads(contradiction_result.stdout)["conflicts"]
        if not conflicts:
            raise SystemExit("contradiction eval did not report normalized-value conflict")

    print("runtime eval passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
