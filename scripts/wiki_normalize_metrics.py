#!/usr/bin/env python3
"""Normalize metric names, units, baselines, and numeric values in claim graphs."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, json_dump, read_text, write_text


MULTIPLIERS = {"": 1.0, "%": 1.0, "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def load_claims(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def clean_key(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    text = re.sub(r"\b(reported|claim|value|metric|model|score|result)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def baseline_key(text: str) -> str:
    lowered = clean_key(text)
    if not lowered or lowered in {"as stated in source", "not applicable", "none"}:
        return ""
    return lowered[:120]


def metric_family(predicate: str, unit: str, claim_text: str) -> str:
    hay = f"{predicate} {unit} {claim_text}".lower()
    if any(word in hay for word in ["parameter", "activated", "active"]):
        return "parameters"
    if "token" in hay or "context" in hay:
        return "tokens"
    if any(word in hay for word in ["bleu", "accuracy", "pass@", "score", "mmlu", "aime", "gpqa", "humaneval", "%"]):
        return "score"
    if "language" in hay:
        return "languages"
    if "expert" in hay:
        return "experts"
    return "numeric"


def normalize_unit(unit: str, family: str) -> str:
    unit_lower = unit.lower().strip()
    if unit_lower == "%":
        return "%"
    if family == "parameters":
        return "parameters"
    if family == "tokens":
        return "tokens"
    if family == "score":
        return "score"
    if family == "languages":
        return "languages"
    if family == "experts":
        return "experts"
    return unit_lower


def normalized_value(value: object, unit: str, family: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    unit_lower = unit.lower().strip()
    if unit_lower in MULTIPLIERS and family in {"parameters", "tokens", "numeric"}:
        return number * MULTIPLIERS[unit_lower]
    return number


def normalize_claim(claim: dict[str, object]) -> dict[str, object]:
    if claim.get("claim_type") != "metric":
        claim.setdefault("metric_key", "")
        claim.setdefault("normalized_value", None)
        claim.setdefault("normalized_unit", "")
        claim.setdefault("unit_family", "")
        claim.setdefault("baseline_key", baseline_key(str(claim.get("baseline", ""))))
        claim.setdefault("protocol_key", "")
        return claim
    predicate = str(claim.get("predicate", ""))
    unit = str(claim.get("unit", ""))
    object_text = str(claim.get("object", ""))
    family = metric_family(predicate, unit, object_text)
    norm_unit = normalize_unit(unit, family)
    claim["metric_key"] = clean_key(predicate) or clean_key(object_text) or "reported numeric claim"
    claim["unit_family"] = family
    claim["normalized_unit"] = norm_unit
    claim["normalized_value"] = normalized_value(claim.get("value"), unit, family)
    claim["baseline_key"] = baseline_key(str(claim.get("baseline", "")))
    claim["protocol_key"] = protocol_key(predicate, object_text)
    claim["normalization_warnings"] = normalization_warnings(claim)
    return claim


def protocol_key(predicate: str, object_text: str) -> str:
    hay = f"{predicate} {object_text}".lower()
    keys = []
    for marker in ["zero-shot", "few-shot", "pass@1", "pass@10", "base", "big", "eval", "benchmark"]:
        if marker in hay:
            keys.append(marker)
    return ",".join(keys)


def normalization_warnings(claim: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if claim.get("claim_type") != "metric":
        return warnings
    if claim.get("normalized_value") is None:
        warnings.append("missing_normalized_value")
    if not claim.get("metric_key") or claim.get("metric_key") == "reported numeric claim":
        warnings.append("generic_metric_name")
    if not claim.get("baseline_key") and str(claim.get("baseline", "")).lower() not in {"", "not applicable"}:
        warnings.append("baseline_not_normalized")
    return warnings


def report(rows: list[dict[str, object]], output: Path) -> str:
    metric_rows = [row for row in rows if row.get("claim_type") == "metric"]
    warnings: dict[str, int] = {}
    families: dict[str, int] = {}
    for row in metric_rows:
        families[str(row.get("unit_family", ""))] = families.get(str(row.get("unit_family", "")), 0) + 1
        for warning in row.get("normalization_warnings", []):
            warnings[str(warning)] = warnings.get(str(warning), 0) + 1
    family_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(families.items())) or "- none"
    warning_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(warnings.items())) or "- none"
    return (
        "# Metric Normalization Report\n"
        f"- date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"- output: {output.as_posix()}\n"
        f"- claims: {len(rows)}\n"
        f"- metric_claims: {len(metric_rows)}\n\n"
        "## Unit Families\n\n"
        f"{family_lines}\n\n"
        "## Warnings\n\n"
        f"{warning_lines}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize metrics in a claim graph.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--claims", type=Path, help="Defaults to <vault>/claims/claims.jsonl.")
    parser.add_argument("--output", type=Path, help="Defaults to <vault>/claims/normalized-claims.jsonl.")
    parser.add_argument("--report", type=Path, help="Defaults to <vault>/claims/metric-normalization-report.md.")
    parser.add_argument("--in-place", action="store_true", help="Also replace claims/claims.jsonl with normalized rows.")
    parser.add_argument("--format", choices=["summary", "json"], default="summary")
    args = parser.parse_args()

    vault = args.vault.resolve()
    claims_path = (args.claims or vault / "claims" / "claims.jsonl").resolve()
    output = ensure_within(
        args.output or vault / "claims" / "normalized-claims.jsonl",
        vault / "claims",
        "normalization output must stay under claims/",
    )
    report_path = ensure_within(
        args.report or vault / "claims" / "metric-normalization-report.md",
        vault / "claims",
        "normalization report must stay under claims/",
    )
    rows = [normalize_claim(dict(row)) for row in load_claims(claims_path)]
    write_jsonl(output, rows)
    if args.in_place:
        write_jsonl(claims_path, rows)
    write_text(report_path, report(rows, output))
    if args.format == "json":
        print(json_dump({"claims": len(rows), "output": str(output), "report": str(report_path)}))
    else:
        print(f"claims: {len(rows)}")
        print(f"output: {output}")
        print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
