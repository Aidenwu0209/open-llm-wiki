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


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


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
        rows = load_jsonl(growth_vault / "claims" / "claims.jsonl")
        layer_claims = [row for row in rows if row.get("predicate") == "Base model layers"]
        if not layer_claims:
            raise SystemExit("claim eval did not extract Base model layers")
        layer_claim = layer_claims[0]
        if (
            layer_claim.get("value") is not None
            or layer_claim.get("unit")
            or not layer_claim.get("needs_review")
        ):
            raise SystemExit("claim eval treated a compound layer count as a scalar metric")
        run([sys.executable, "scripts/wiki_queue.py", str(growth_vault), "list"])
        run([sys.executable, "scripts/wiki_lint.py", str(growth_vault), "--fail-on", "p1"])

        test_vault = Path(tmp) / "vault"
        run([sys.executable, "scripts/wiki_init.py", str(test_vault), "--repo-root", str(ROOT)])
        run([sys.executable, "scripts/wiki_lint.py", str(test_vault), "--fail-on", "p1"])

        normalization_vault = Path(tmp) / "normalization-vault"
        (normalization_vault / "claims").mkdir(parents=True)
        write_jsonl(
            normalization_vault / "claims" / "claims.jsonl",
            [
                {
                    "claim_id": "claim-generic",
                    "source_id": "LLM-0001",
                    "claim_type": "metric",
                    "predicate": "Metric",
                    "object": "42",
                    "value": 42,
                    "unit": "",
                    "baseline": "not applicable",
                    "evidence": "sources/LLM-0001.md#Key Data",
                    "concepts": [],
                },
                {
                    "claim_id": "claim-missing-baseline",
                    "source_id": "LLM-0001",
                    "claim_type": "metric",
                    "predicate": "Accuracy",
                    "object": "92%",
                    "value": 92,
                    "unit": "%",
                    "baseline": "",
                    "evidence": "sources/LLM-0001.md#Key Data",
                    "concepts": [],
                }
            ],
        )
        run([sys.executable, "scripts/wiki_normalize_metrics.py", str(normalization_vault)])
        normalized = load_jsonl(normalization_vault / "claims" / "normalized-claims.jsonl")
        by_id = {row.get("claim_id"): row for row in normalized}
        generic_warnings = by_id["claim-generic"].get("normalization_warnings", [])
        baseline_warnings = by_id["claim-missing-baseline"].get("normalization_warnings", [])
        if "generic_metric_name" not in generic_warnings:
            raise SystemExit("normalization eval did not flag a generic metric name")
        if "missing_baseline" not in baseline_warnings:
            raise SystemExit("normalization eval did not flag a missing baseline")

    print("runtime eval passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
