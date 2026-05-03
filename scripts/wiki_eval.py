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

        review_vault = Path(tmp) / "review-vault"
        (review_vault / "claims").mkdir(parents=True)
        claim = {
            "claim_id": "claim-missing-protocol",
            "source_id": "LLM-0001",
            "claim_type": "metric",
            "predicate": "Accuracy",
            "object": "92%",
            "value": 92,
            "unit": "%",
            "baseline": "baseline model",
            "baseline_key": "baseline model",
            "protocol_key": "",
            "metric_key": "accuracy",
            "normalized_value": 92,
            "normalized_unit": "%",
            "unit_family": "score",
            "normalization_warnings": [],
            "needs_review": False,
            "evidence": "sources/LLM-0001.md#Key Data",
            "concepts": [],
        }
        (review_vault / "claims" / "claims.jsonl").write_text(
            json.dumps(claim, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        review_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_science_review.py",
                str(review_vault),
                "--format",
                "json",
                "--fail-on-review-required",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if review_result.returncode == 0:
            raise SystemExit("science review eval did not fail on missing protocol context")
        review_items = json.loads(review_result.stdout)["items"]
        reasons = review_items[0].get("review_reasons", []) if review_items else []
        if "scientific_context_review" not in reasons:
            raise SystemExit("science review eval did not queue missing protocol context")

    print("runtime eval passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
