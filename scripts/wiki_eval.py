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


def replace_with_symlink(path: Path, target: Path) -> bool:
    path.unlink()
    try:
        path.symlink_to(target)
    except (NotImplementedError, OSError):
        return False
    return True


def check_individual_pipeline_stages(vault: Path, tmp: str) -> None:
    stage_vault = Path(tmp) / "stage-vault"
    shutil.copytree(vault, stage_vault)

    run([sys.executable, "scripts/wiki_claims.py", str(stage_vault)])
    claims_path = stage_vault / "claims" / "claims.jsonl"
    claims = load_jsonl(claims_path)
    if not claims:
        raise SystemExit("individual stage eval produced no claims")
    if not all(isinstance(row, dict) and row.get("claim_id") for row in claims):
        raise SystemExit("individual stage eval found invalid claim JSONL rows")

    run([sys.executable, "scripts/wiki_normalize_metrics.py", str(stage_vault), "--in-place"])
    normalized_path = stage_vault / "claims" / "normalized-claims.jsonl"
    if not normalized_path.exists():
        raise SystemExit("individual stage eval did not write normalized-claims.jsonl")
    if not (stage_vault / "claims" / "metric-normalization-report.md").exists():
        raise SystemExit("individual stage eval did not write metric normalization report")
    normalized = load_jsonl(normalized_path)
    if not any(row.get("claim_type") == "metric" and "metric_key" in row for row in normalized):
        raise SystemExit("individual stage eval did not normalize metric claims")

    run([sys.executable, "scripts/wiki_semantic_qa.py", str(stage_vault), "--fail-on", "p1"])

    science_output = run([sys.executable, "scripts/wiki_science_review.py", str(stage_vault), "--format", "json"])
    science = json.loads(science_output)
    if int(science.get("review_items", 0)) <= 0:
        raise SystemExit("individual stage eval science review returned a fake PASS with no review items")

    contradiction_output = run([sys.executable, "scripts/wiki_contradictions.py", str(stage_vault), "--format", "json"])
    contradiction = json.loads(contradiction_output)
    if contradiction.get("conflicts") or contradiction.get("markers"):
        raise SystemExit("individual stage eval found unexpected confirmed contradiction markers")
    contradiction_markdown = run([sys.executable, "scripts/wiki_contradictions.py", str(stage_vault)])
    if "NO_CONFIRMED_CONTRADICTION" not in contradiction_markdown:
        raise SystemExit("individual stage eval contradiction report did not state NO_CONFIRMED_CONTRADICTION")

    concept_preview = run([sys.executable, "scripts/wiki_concept_revision.py", str(stage_vault)])
    if "- changed: 0" in concept_preview or "- changed: " not in concept_preview:
        raise SystemExit("individual stage eval concept revision preview did not report changed concepts")

    run([sys.executable, "scripts/wiki_queue.py", str(stage_vault), "plan", "--cadence", "now"])
    queue_rows = load_jsonl(stage_vault / "_state" / "growth-queue.jsonl")
    if not any(row.get("status") == "pending" for row in queue_rows):
        raise SystemExit("individual stage eval queue planning did not create pending tasks")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run runtime smoke evaluations.")
    parser.add_argument("--vault", type=Path, default=ROOT / "examples" / "minimal-vault")
    args = parser.parse_args()

    vault = args.vault.resolve()
    run([sys.executable, "scripts/wiki_lint.py", str(vault), "--fail-on", "p1"])
    status_output = run([sys.executable, "scripts/wiki_status.py", str(vault)])
    try:
        status_output.encode("gbk")
    except UnicodeEncodeError as exc:
        raise SystemExit(f"status eval output is not Windows GBK stdout-safe: {exc}") from exc
    for expected in ["Pipeline Status", "Agent Prompt Templates", "Common Runtime Commands", "Safe Write Flow"]:
        if expected not in status_output:
            raise SystemExit(f"status eval output missing {expected!r}")
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
        graph_vault = Path(tmp) / "graph-vault"
        shutil.copytree(vault, graph_vault)
        run([sys.executable, "scripts/wiki_graph_export.py", str(graph_vault), "--format", "json"])
        graph_path = graph_vault / ".graph" / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        node_types = {node.get("type") for node in graph.get("nodes", [])}
        if not {"source", "concept", "claim", "metric", "qa-report"}.issubset(node_types):
            raise SystemExit("graph eval missing expected source/concept/claim/QA nodes")
        if not graph.get("evidence_paths"):
            raise SystemExit("graph eval did not produce evidence paths")
        run(
            [
                sys.executable,
                "scripts/wiki_graph_export.py",
                str(graph_vault),
                "--format",
                "obsidian-canvas",
                "--output",
                "canvas/wiki-graph.canvas",
            ]
        )
        run([sys.executable, "scripts/wiki_lint.py", str(graph_vault), "--graph", "--fail-on", "p1"])

    with tempfile.TemporaryDirectory() as tmp:
        check_individual_pipeline_stages(vault, tmp)

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

        queue_vault = Path(tmp) / "queue-vault"
        shutil.copytree(vault, queue_vault)
        run([sys.executable, "scripts/wiki_queue.py", str(queue_vault), "plan", "--cadence", "now"])
        queue_path = queue_vault / "_state" / "growth-queue.jsonl"
        rows = load_jsonl(queue_path)
        due_at = {
            "discover": "2000-01-01T00:00:00",
            "grow": "2000-01-01T00:05:00",
            "science-review": "2000-01-01T00:10:00",
            "concept-revision": "2000-01-01T00:15:00",
            "lint": "2000-01-01T00:20:00",
        }
        for row in rows:
            row["due_at"] = due_at[str(row["action"])]
        write_jsonl(queue_path, rows)
        dry_run = run([sys.executable, "scripts/wiki_queue.py", str(queue_vault), "run-due", "--dry-run"])
        actions = [line.split(": ", 1)[1] for line in dry_run.splitlines() if line.startswith("run ")]
        if actions != ["discover", "grow", "science-review", "lint"]:
            raise SystemExit(f"queue dry-run order is not due-time order: {actions}")

        test_vault = Path(tmp) / "vault"
        run([sys.executable, "scripts/wiki_init.py", str(test_vault), "--repo-root", str(ROOT)])
        run([sys.executable, "scripts/wiki_lint.py", str(test_vault), "--fail-on", "p1"])

        dashboard_vault = Path(tmp) / "dashboard-vault"
        run(
            [
                sys.executable,
                "scripts/wiki_init.py",
                str(dashboard_vault),
                "--repo-root",
                str(ROOT),
                "--obsidian",
                "--obsidian-skip-downloads",
            ]
        )
        if not (dashboard_vault / "_dashboard.md").exists():
            raise SystemExit("status eval did not create an Obsidian dashboard during wiki_init --obsidian")
        dashboard = (dashboard_vault / "_dashboard.md").read_text(encoding="utf-8")
        if "Agent Prompt Templates" not in dashboard or "Safe Write Flow" not in dashboard:
            raise SystemExit("status eval dashboard missing agent prompt or writeback guidance")
        overwrite = subprocess.run(
            [sys.executable, "scripts/wiki_status.py", str(dashboard_vault), "--write-dashboard"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if overwrite.returncode == 0:
            raise SystemExit("status eval allowed dashboard overwrite without --force")

        missing_review_queue_vault = Path(tmp) / "missing-review-queue-vault"
        shutil.copytree(vault, missing_review_queue_vault)
        (missing_review_queue_vault / "_state" / "science-review-queue.jsonl").unlink()
        lint_result = subprocess.run(
            [sys.executable, "scripts/wiki_lint.py", str(missing_review_queue_vault), "--fail-on", "p1"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if lint_result.returncode == 0 or "_state/science-review-queue.jsonl" not in lint_result.stdout:
            print(lint_result.stdout)
            raise SystemExit("lint eval did not fail on missing science review queue")

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

        missing_anchor_vault = Path(tmp) / "missing-anchor-vault"
        shutil.copytree(vault, missing_anchor_vault)
        write_jsonl(
            missing_anchor_vault / "claims" / "claims.jsonl",
            [
                {
                    "claim_id": "claim-missing-anchor",
                    "source_id": "LLM-0001",
                    "claim_type": "metric",
                    "predicate": "WMT 2014 EN-DE BLEU, base",
                    "object": "27.3",
                    "value": 27.3,
                    "unit": "",
                    "baseline": "prior systems",
                    "normalized_value": 27.3,
                    "evidence": "sources/LLM-0001.md#Missing Anchor",
                    "concepts": ["attention-mechanisms"],
                }
            ],
        )
        qa_output = run(
            [
                sys.executable,
                "scripts/wiki_semantic_qa.py",
                str(missing_anchor_vault),
                "--format",
                "json",
                "--fail-on",
                "none",
            ]
        )
        issues = json.loads(qa_output)["issues"]
        if not any("heading anchor does not exist" in item["message"] for item in issues):
            raise SystemExit("semantic QA eval did not flag a missing heading anchor")

        unsupported_metric_vault = Path(tmp) / "unsupported-metric-vault"
        shutil.copytree(vault, unsupported_metric_vault)
        write_jsonl(
            unsupported_metric_vault / "claims" / "claims.jsonl",
            [
                {
                    "claim_id": "claim-unsupported-metric",
                    "source_id": "LLM-0001",
                    "claim_type": "metric",
                    "predicate": "WMT 2014 EN-DE BLEU, base",
                    "object": "99.9",
                    "value": 99.9,
                    "unit": "",
                    "baseline": "prior systems",
                    "normalized_value": 99.9,
                    "evidence": "sources/LLM-0001.md#L31",
                    "concepts": ["attention-mechanisms"],
                }
            ],
        )
        qa_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_semantic_qa.py",
                str(unsupported_metric_vault),
                "--format",
                "json",
                "--fail-on",
                "p1",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if qa_result.returncode == 0:
            raise SystemExit("semantic QA eval did not fail on an unsupported metric claim")
        qa_issues = json.loads(qa_result.stdout)["issues"]
        if not any(item["priority"] == "P1" for item in qa_issues):
            raise SystemExit("semantic QA eval did not flag unsupported metric as P1")

        review_vault = Path(tmp) / "review-vault"
        (review_vault / "claims").mkdir(parents=True)
        missing_protocol_claim = {
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
        write_jsonl(review_vault / "claims" / "claims.jsonl", [missing_protocol_claim])
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

        concept_vault = Path(tmp) / "concept-vault"
        (concept_vault / "claims").mkdir(parents=True)
        (concept_vault / "concepts").mkdir(parents=True)
        (concept_vault / "concepts" / "evals.md").write_text("# Evals\n\nHand authored intro.\n", encoding="utf-8")
        concept_claim = dict(missing_protocol_claim)
        concept_claim["concepts"] = ["evals"]
        write_jsonl(concept_vault / "claims" / "claims.jsonl", [concept_claim])
        run([sys.executable, "scripts/wiki_concept_revision.py", str(concept_vault), "--apply"])
        concept_text = (concept_vault / "concepts" / "evals.md").read_text(encoding="utf-8")
        if "Accuracy: 92%" in concept_text or "Held for review in this concept: 1" not in concept_text:
            raise SystemExit("concept revision eval did not hold missing-protocol claim for review")

        contradiction_vault = Path(tmp) / "contradiction-vault"
        (contradiction_vault / "claims").mkdir(parents=True)
        write_jsonl(
            contradiction_vault / "claims" / "claims.jsonl",
            [
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
            ],
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

        queue_symlink_vault = Path(tmp) / "queue-symlink-vault"
        shutil.copytree(vault, queue_symlink_vault)
        outside_queue = Path(tmp) / "outside-queue.jsonl"
        outside_queue.write_text("", encoding="utf-8")
        if replace_with_symlink(queue_symlink_vault / "_state" / "growth-queue.jsonl", outside_queue):
            queue_result = subprocess.run(
                [sys.executable, "scripts/wiki_queue.py", str(queue_symlink_vault), "plan", "--cadence", "now"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if queue_result.returncode == 0 or outside_queue.read_text(encoding="utf-8"):
                print(queue_result.stdout)
                raise SystemExit("queue eval allowed growth queue symlink escape")

        science_queue_symlink_vault = Path(tmp) / "science-queue-symlink-vault"
        shutil.copytree(vault, science_queue_symlink_vault)
        run([sys.executable, "scripts/wiki_claims.py", str(science_queue_symlink_vault)])
        outside_science_queue = Path(tmp) / "outside-science-queue.jsonl"
        outside_science_queue.write_text("", encoding="utf-8")
        if replace_with_symlink(science_queue_symlink_vault / "_state" / "science-review-queue.jsonl", outside_science_queue):
            science_result = subprocess.run(
                [sys.executable, "scripts/wiki_science_review.py", str(science_queue_symlink_vault), "--queue"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if science_result.returncode == 0 or outside_science_queue.read_text(encoding="utf-8"):
                print(science_result.stdout)
                raise SystemExit("science review eval allowed queue symlink escape")

        status_action_symlink_vault = Path(tmp) / "status-action-symlink-vault"
        shutil.copytree(vault, status_action_symlink_vault)
        outside_action_state = Path(tmp) / "outside-action-state.jsonl"
        outside_action_state.write_text("", encoding="utf-8")
        action_state_path = status_action_symlink_vault / "_state" / "action-state.jsonl"
        if action_state_path.exists():
            action_state_path.unlink()
        action_state_path.write_text("", encoding="utf-8")
        if replace_with_symlink(action_state_path, outside_action_state):
            status_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/wiki_status.py",
                    str(status_action_symlink_vault),
                    "--resolve-action",
                    "act-demo",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if status_result.returncode == 0 or outside_action_state.read_text(encoding="utf-8"):
                print(status_result.stdout)
                raise SystemExit("status eval allowed action-state symlink escape")

        status_actions_symlink_vault = Path(tmp) / "status-actions-symlink-vault"
        shutil.copytree(vault, status_actions_symlink_vault)
        outside_actions = Path(tmp) / "outside-actions.jsonl"
        outside_actions.write_text("", encoding="utf-8")
        actions_path = status_actions_symlink_vault / "_state" / "actions.jsonl"
        if not actions_path.exists():
            actions_path.write_text("", encoding="utf-8")
        if replace_with_symlink(actions_path, outside_actions):
            status_result = subprocess.run(
                [
                    sys.executable,
                    "scripts/wiki_status.py",
                    str(status_actions_symlink_vault),
                    "--actions",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if status_result.returncode == 0 or outside_actions.read_text(encoding="utf-8"):
                print(status_result.stdout)
                raise SystemExit("status eval allowed actions symlink escape")

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
        registry_rows = load_jsonl(corpus_vault / "_state" / "source-registry.jsonl")
        row = next((item for item in registry_rows if item.get("source_id") == "LLM-0001"), None)
        if row is None:
            raise SystemExit("grow eval did not keep a stable source registry row after corpus ingest")
        import hashlib
        raw_hash = hashlib.sha256((raw_dir / "2501.00001.pdf").read_bytes()).hexdigest()
        artifact_hash = hashlib.sha256((parsed_dir / "combined.md").read_bytes()).hexdigest()
        if row.get("raw_path") != "raw/2501.00001.pdf" or row.get("raw_hash") != raw_hash:
            raise SystemExit("grow eval source registry did not preserve original raw evidence identity")
        if row.get("artifact_path") != "raw/2501.00001_markdown/combined.md" or row.get("artifact_hash") != artifact_hash:
            raise SystemExit("grow eval source registry did not record parsed artifact identity")
        if row.get("status") != "published" or not (corpus_vault / "sources" / "LLM-0001.md").exists():
            raise SystemExit("grow eval did not publish the corpus source page")

    # --- Dashboard Action Model Tests (Issue #73) ---
    with tempfile.TemporaryDirectory() as td:
        q_vault = Path(td) / "action-vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", q_vault)

        # Test: --actions generates JSON with open_actions
        actions_out = run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--actions"])
        actions_data = json.loads(actions_out)
        if "open_actions" not in actions_data:
            raise SystemExit("dashboard actions: missing open_actions key")
        if not isinstance(actions_data["open_actions"], list):
            raise SystemExit("dashboard actions: open_actions is not a list")
        if actions_data["total_actions"] < 1:
            raise SystemExit("dashboard actions: expected at least 1 action from minimal-vault")

        # Test: actions.jsonl is written and consistent
        actions_jsonl = load_jsonl(q_vault / "_state" / "actions.jsonl")
        if len(actions_jsonl) != actions_data["total_actions"]:
            raise SystemExit("dashboard actions: actions.jsonl count mismatch")

        # Test: each action has required fields
        required_action_fields = {"action_id", "kind", "severity", "title", "body",
                                  "reason", "status", "primary_object_type", "primary_object_id"}
        for action in actions_jsonl:
            missing = required_action_fields - set(action)
            if missing:
                raise SystemExit(f"dashboard actions: action missing fields {missing}")

        # Test: --write-dashboard produces markdown with Action Panel (while actions are open)
        run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--write-dashboard", "--force"])
        dashboard_text = (q_vault / "_dashboard.md").read_text(encoding="utf-8")
        if "## Action Panel" not in dashboard_text:
            raise SystemExit("dashboard actions: Action Panel section missing from dashboard")
        if "What should I do next" not in dashboard_text:
            raise SystemExit("dashboard actions: Action Panel guidance text missing")

        # Test: resolve action and verify it disappears from open list
        first_action_id = actions_data["open_actions"][0]["action_id"]
        run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--resolve-action", first_action_id])
        state_rows = load_jsonl(q_vault / "_state" / "action-state.jsonl")
        resolved_ids = {str(r.get("action_id")) for r in state_rows if r.get("status") == "resolved"}
        if first_action_id not in resolved_ids:
            raise SystemExit("dashboard actions: resolve did not persist")

        # Re-generate actions, resolved should not appear
        actions_out2 = run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--actions"])
        actions_data2 = json.loads(actions_out2)
        open_ids = {a["action_id"] for a in actions_data2["open_actions"]}
        if first_action_id in open_ids:
            raise SystemExit("dashboard actions: resolved action still showing as open")

        # Test: ignore action
        if len(actions_data2["open_actions"]) > 0:
            ignore_id = actions_data2["open_actions"][0]["action_id"]
            run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--ignore-action", ignore_id])
            actions_out3 = run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--actions"])
            actions_data3 = json.loads(actions_out3)
            open_ids3 = {a["action_id"] for a in actions_data3["open_actions"]}
            if ignore_id in open_ids3:
                raise SystemExit("dashboard actions: ignored action still showing as open")

        # Test: source_updated action appears when source is recently updated
        import datetime as dt
        today_str = dt.date.today().isoformat()
        source_path = q_vault / "sources" / "LLM-0001.md"
        source_text = source_path.read_text(encoding="utf-8")
        source_text = source_text.replace("updated: 2026-05-01", f"updated: {today_str}")
        source_path.write_text(source_text, encoding="utf-8")
        actions_out4 = run([sys.executable, "scripts/wiki_status.py", str(q_vault), "--actions"])
        actions_data4 = json.loads(actions_out4)
        kinds = {a["kind"] for a in actions_data4["open_actions"]}
        if "source_updated" not in kinds:
            raise SystemExit("dashboard actions: source_updated action not generated for recently updated source")

    # --- Claim Ledger Tests (Issue #69) ---
    with tempfile.TemporaryDirectory() as td:
        q_vault = Path(td) / "claim-ledger-vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", q_vault)

        run([sys.executable, "scripts/wiki_claims.py", str(q_vault)])

        claims_path = q_vault / "claims" / "claims.jsonl"
        claims = load_jsonl(claims_path)
        if not claims:
            raise SystemExit("claim ledger: no claims extracted")

        required_fields = {
            "claim_id", "source_uuid", "source_id", "chunk_id",
            "claim_text", "normalized_claim", "evidence_quote",
            "evidence_hash", "anchor", "verdict", "created_at", "updated_at",
        }
        for claim in claims:
            missing = required_fields - set(claim)
            if missing:
                raise SystemExit(f"claim ledger: claim {claim.get('claim_id')} missing fields: {missing}")

        import hashlib
        for claim in claims:
            eq = str(claim.get("evidence_quote", ""))
            if len(eq) > 300:
                raise SystemExit(f"claim ledger: evidence_quote too long ({len(eq)} chars)")
            eh = str(claim.get("evidence_hash", ""))
            if eq and eh:
                expected = hashlib.sha256(eq.encode("utf-8")).hexdigest()[:16]
                if eh != expected:
                    raise SystemExit(f"claim ledger: evidence_hash mismatch for {claim.get('claim_id')}")

        run([sys.executable, "scripts/wiki_normalize_metrics.py", str(q_vault), "--in-place"])
        run([sys.executable, "scripts/wiki_semantic_qa.py", str(q_vault), "--assign-verdicts", "--in-place"])
        claims_after = load_jsonl(claims_path)
        supported = [c for c in claims_after if c.get("verdict") == "supported"]
        if not supported:
            raise SystemExit("claim ledger: no claims marked as supported after verdict assignment")

        claims_after[0]["verdict"] = "contradicted"
        write_jsonl(claims_path, claims_after)
        run([sys.executable, "scripts/wiki_concept_revision.py", str(q_vault), "--apply"])
        concept_path = q_vault / "concepts" / "attention-mechanisms.md"
        concept_text = concept_path.read_text(encoding="utf-8")
        contradicted_id = str(claims_after[0]["claim_id"])
        if contradicted_id in concept_text:
            raise SystemExit("claim ledger: contradicted claim appeared in concept synthesis")

        claims_after[0]["verdict"] = "supported"
        claims_after[0]["evidence_hash"] = "bad_hash_value"
        write_jsonl(claims_path, claims_after)
        lint_result = subprocess.run(
            [sys.executable, "scripts/wiki_lint.py", str(q_vault), "--fail-on", "p1"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if lint_result.returncode == 0:
            raise SystemExit("claim ledger: lint should fail on evidence_hash mismatch")

        eq = str(claims_after[0].get("evidence_quote", ""))
        claims_after[0]["evidence_hash"] = hashlib.sha256(eq.encode("utf-8")).hexdigest()[:16]
        write_jsonl(claims_path, claims_after)

        from wiki_claims import mark_stale_claims
        marked = mark_stale_claims(claims_path, {"LLM-0001"})
        if marked == 0:
            raise SystemExit("claim ledger: mark_stale_claims should mark claims")
        claims_stale = load_jsonl(claims_path)
        stale_claims = [c for c in claims_stale if c.get("verdict") == "stale"]
        if not stale_claims:
            raise SystemExit("claim ledger: no stale claims after mark_stale_claims")

    print("runtime eval passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
