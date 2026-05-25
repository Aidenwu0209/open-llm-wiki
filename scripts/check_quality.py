#!/usr/bin/env python3
"""Repository quality checks for open-llm-wiki."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SKILL_FIELDS = {
    "allowed-tools",
    "compatibility",
    "description",
    "license",
    "metadata",
    "name",
}
BANNED_TOKENS = [
    chr(0xFFFD),
    chr(0x922B),
    chr(0x9225),
    chr(0x922E),
    chr(0x9241),
    chr(0x9242),
    chr(0x9983),
    chr(0x628E),
    chr(0x6522),
    chr(0x64B1),
    chr(0x9428),
]


def fail(message: str) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(1)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = read(path)
    if not text.startswith("---\n"):
        fail(f"{path.relative_to(ROOT)} missing YAML frontmatter")
    try:
        _, block, _ = text.split("---\n", 2)
    except ValueError:
        fail(f"{path.relative_to(ROOT)} has malformed YAML frontmatter")

    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith(" ") or line.startswith("-"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def check_skills() -> None:
    skills_dir = ROOT / "skills"
    expected = {"wiki-ingest", "query-writeback", "wiki-lint"}
    actual = {p.name for p in skills_dir.iterdir() if p.is_dir()}
    if actual != expected:
        fail(f"unexpected skill folders: {sorted(actual)}")

    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            fail(f"{skill_dir.name} missing SKILL.md")
        fields = parse_frontmatter(skill_file)
        missing = {"name", "description"} - set(fields)
        if missing:
            fail(f"{skill_file.relative_to(ROOT)} missing fields: {sorted(missing)}")
        unexpected = set(fields) - ALLOWED_SKILL_FIELDS
        if unexpected:
            fail(f"{skill_file.relative_to(ROOT)} has unsupported fields: {sorted(unexpected)}")
        name = fields["name"].strip('"')
        if name != skill_dir.name:
            fail(f"{skill_file.relative_to(ROOT)} name {name!r} does not match folder")
        if len(fields["description"]) < 80:
            fail(f"{skill_file.relative_to(ROOT)} description is too short to trigger safely")


def check_docs() -> None:
    required = [
        "README.md",
        "README.zh.md",
        "QUICKSTART.md",
        "SCHEMA.md",
        "AGENTS.md",
        "AGENTS_SNIPPET.md",
        "EXAMPLES.md",
        "SHOWCASE.md",
        "PHILOSOPHY.md",
        "pyproject.toml",
        "setup.sh",
        "uv.lock",
        "scripts/wiki_claims.py",
        "scripts/wiki_concept_revision.py",
        "scripts/wiki_contradictions.py",
        "scripts/wiki_discover_sources.py",
        "scripts/wiki_graph_export.py",
        "scripts/wiki_grow.py",
        "scripts/wiki_ingest_corpus.py",
        "scripts/wiki_normalize_metrics.py",
        "scripts/wiki_queue.py",
        "scripts/wiki_science_review.py",
        "scripts/pdf_corpus_report.py",
        "scripts/pdf_corpus_to_markdown.py",
        "scripts/pdf_to_markdown.py",
        "scripts/wiki_common.py",
        "scripts/wiki_init.py",
        "scripts/wiki_lint.py",
        "scripts/wiki_obsidian_setup.py",
        "scripts/wiki_semantic_qa.py",
        "scripts/wiki_search.py",
        "scripts/wiki_source_registry.py",
        "scripts/wiki_ingest_plan.py",
        "scripts/wiki_status.py",
        "scripts/wiki_writeback.py",
        "scripts/wiki_eval.py",
        "obsidian/app.json",
        "obsidian/appearance.json",
        "obsidian/hotkeys.json",
        "obsidian/plugin-manifest.json",
        "obsidian/sortspec.md",
        "graph/graph.schema.json",
        "templates/agent-prompts/ingest-one-source.md",
        "templates/agent-prompts/query-wiki.md",
        "templates/agent-prompts/propose-writeback.md",
        "templates/agent-prompts/run-lint.md",
        "templates/agent-prompts/science-review.md",
        "templates/agent-prompts/concept-revision.md",
        "templates/agent-prompts/graph-export.md",
    ]
    for item in required:
        if not (ROOT / item).exists():
            fail(f"missing required file: {item}")

    if (ROOT / "todo.md").exists():
        fail("todo.md should not be published as stale project guidance")

    for path in ROOT.rglob("*"):
        if path.is_dir() or ".git" in path.parts or ".venv" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".py", ".sh", ".yml", ".yaml", ".svg"}:
            continue
        text = read(path)
        for token in BANNED_TOKENS:
            if token in text:
                fail(f"{path.relative_to(ROOT)} contains mojibake token {token!r}")


def check_minimal_vault() -> None:
    vault = ROOT / "examples" / "minimal-vault"
    required = [
        "SCHEMA.md",
        "index.md",
        "log.md",
        "_state/id-counter.md",
        "_state/growth-queue.jsonl",
        "_state/source-registry.jsonl",
        "claims/claims.jsonl",
        "sources/LLM-0001.md",
        "concepts/attention-mechanisms.md",
        "SCHEMA.md",
        "qa-reports/LLM-0001.md",
        "qa-reports/LLM-0001-contradiction.md",
    ]
    for item in required:
        if not (vault / item).exists():
            fail(f"minimal vault missing {item}")

    source_fields = parse_frontmatter(vault / "sources" / "LLM-0001.md")
    if source_fields.get("status") != "stable":
        fail("minimal vault source must be stable")

    qa = read(vault / "qa-reports" / "LLM-0001.md")
    if "verdict: PASS" not in qa:
        fail("minimal vault QA report must pass")

    index = read(vault / "index.md")
    for link in ("[[LLM-0001]]", "[[attention-mechanisms]]"):
        if link not in index:
            fail(f"minimal vault index missing {link}")


def check_vault_init_obsidian_graph_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("vault initialization failed while checking Obsidian graph defaults")
        graph = vault / ".obsidian" / "graph.json"
        if not graph.exists():
            print(result.stdout)
            fail("initialized vault missing .obsidian/graph.json")
        try:
            settings = json.loads(read(graph))
        except json.JSONDecodeError as exc:
            print(read(graph))
            fail(f".obsidian/graph.json is not valid JSON: {exc}")
        search = str(settings.get("search", ""))
        for token in ["-path:raw", "-path:templates", "-path:qa-reports", "-path:_state", "-path:claims"]:
            if token not in search:
                print(search)
                fail(f"Obsidian graph filter missing {token}")
        if settings.get("hideUnresolved") is not True:
            fail("Obsidian graph defaults must hide unresolved placeholder nodes")
        for folder in ["raw", "templates", "qa-reports", "_state", "claims"]:
            if not (vault / folder).is_dir():
                fail(f"vault initialization removed required directory: {folder}")


def check_obsidian_setup_layer() -> None:
    for item in ["app.json", "appearance.json", "hotkeys.json", "plugin-manifest.json"]:
        try:
            json.loads(read(ROOT / "obsidian" / item))
        except json.JSONDecodeError as exc:
            fail(f"obsidian/{item} is not valid JSON: {exc}")

    with tempfile.TemporaryDirectory() as tmp:
        dry_vault = Path(tmp) / "dry-vault"
        dry_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_obsidian_setup.py",
                str(dry_vault),
                "--dry-run",
                "--skip-downloads",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if dry_result.returncode != 0:
            print(dry_result.stdout)
            fail("Obsidian setup dry-run failed")
        if dry_vault.exists():
            print(dry_result.stdout)
            fail("Obsidian setup dry-run wrote files")

        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_init.py",
                str(vault),
                "--repo-root",
                str(ROOT),
                "--obsidian",
                "--obsidian-skip-downloads",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("wiki_init.py --obsidian failed")

        app = json.loads(read(vault / ".obsidian" / "app.json"))
        if app.get("communityPluginsEnabled") is not True:
            fail("Obsidian app.json did not enable community plugins")
        plugins = json.loads(read(vault / ".obsidian" / "community-plugins.json"))
        for plugin_id in ["dataview", "omnisearch", "custom-sort", "obsidian42-strange-new-worlds", "homepage"]:
            if plugin_id not in plugins:
                fail(f"minimal Obsidian profile did not enable {plugin_id}")
        if len(plugins) != len(set(plugins)):
            fail("Obsidian community plugin list contains duplicates")
        for item in ["raw/inbox", "sortspec.md", ".obsidian/.gitignore", ".open-llm-wiki/obsidian/plugin-manifest.json"]:
            if not (vault / item).exists():
                fail(f"Obsidian setup missing {item}")
        for item in [
            "_dashboard.md",
            "AGENTS.md",
            "CLAUDE.md",
            ".open-llm-wiki/scripts/wiki_status.py",
            "templates/agent-prompts/ingest-one-source.md",
            "templates/agent-prompts/propose-writeback.md",
        ]:
            if not (vault / item).exists():
                fail(f"Obsidian init missing {item}")
        dashboard = read(vault / "_dashboard.md")
        for text in ["Pipeline Status", "Review Queue", "Agent Prompt Templates", "Common Runtime Commands", "Safe Write Flow"]:
            if text not in dashboard:
                print(dashboard)
                fail(f"Obsidian dashboard missing {text!r}")
        homepage_data = vault / ".obsidian" / "plugins" / "homepage" / "data.json"
        if homepage_data.exists():
            homepage = json.loads(read(homepage_data))
            if homepage.get("homepage") != "_dashboard":
                fail("Obsidian homepage default must point to _dashboard")

        lint_result = subprocess.run(
            [sys.executable, "scripts/wiki_lint.py", str(vault), "--obsidian", "--fail-on", "p1"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if lint_result.returncode != 0:
            print(lint_result.stdout)
            fail("wiki_lint.py --obsidian produced P0/P1 findings for an initialized vault")

        appearance_path = vault / ".obsidian" / "appearance.json"
        appearance = json.loads(read(appearance_path))
        appearance["cssTheme"] = "User Theme"
        appearance_path.write_text(json.dumps(appearance) + "\n", encoding="utf-8")
        rerun = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_obsidian_setup.py",
                str(vault),
                "--skip-downloads",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if rerun.returncode != 0:
            print(rerun.stdout)
            fail("Obsidian setup rerun failed")
        rerun_appearance = json.loads(read(appearance_path))
        if rerun_appearance.get("cssTheme") != "User Theme":
            fail("Obsidian setup overwrote an existing user theme")
        rerun_plugins = json.loads(read(vault / ".obsidian" / "community-plugins.json"))
        if len(rerun_plugins) != len(set(rerun_plugins)):
            fail("Obsidian setup rerun duplicated plugin ids")

def check_graph_export_layer() -> None:
    try:
        json.loads(read(ROOT / "graph" / "graph.schema.json"))
    except json.JSONDecodeError as exc:
        fail(f"graph/graph.schema.json is not valid JSON: {exc}")

    with tempfile.TemporaryDirectory() as tmp:
        initialized = Path(tmp) / "initialized-vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(initialized), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("fresh vault initialization failed while checking graph runtime copy")
        for item in [".open-llm-wiki/scripts/wiki_graph_export.py", ".open-llm-wiki/graph/graph.schema.json"]:
            if not (initialized / item).exists():
                fail(f"fresh vault did not copy graph runtime resource: {item}")

        vault = Path(tmp) / "minimal-vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", vault)
        result = subprocess.run(
            [sys.executable, "scripts/wiki_graph_export.py", str(vault), "--format", "json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("graph JSON export failed")
        graph_path = vault / ".graph" / "graph.json"
        schema_path = vault / ".graph" / "graph.schema.json"
        report_path = vault / ".graph" / "graph-report.md"
        for path in [graph_path, schema_path, report_path]:
            if not path.exists():
                print(result.stdout)
                fail(f"graph export missing {path.relative_to(vault)}")
        graph = json.loads(read(graph_path))
        node_types = {node.get("type") for node in graph.get("nodes", [])}
        for node_type in ["source", "concept", "claim", "metric", "qa-report", "contradiction"]:
            if node_type not in node_types:
                print(json.dumps(graph.get("nodes", []), indent=2)[:3000])
                fail(f"graph export missing {node_type} node")
        edge_types = {edge.get("type") for edge in graph.get("edges", [])}
        for edge_type in ["cites", "supports", "reviewed-by", "derived-from", "needs-review"]:
            if edge_type not in edge_types:
                print(json.dumps(graph.get("edges", []), indent=2)[:3000])
                fail(f"graph export missing {edge_type} edge")
        if not graph.get("evidence_paths"):
            fail("graph export did not produce concept -> claim -> source evidence paths")

        focus_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_graph_export.py",
                str(vault),
                "--format",
                "json",
                "--focus",
                "concepts/attention-mechanisms.md",
                "--depth",
                "1",
                "--output",
                ".graph/focus-attention.json",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if focus_result.returncode != 0:
            print(focus_result.stdout)
            fail("focused graph export failed")
        focus_graph = json.loads(read(vault / ".graph" / "focus-attention.json"))
        if focus_graph.get("focus", {}).get("node_id") != "concept:attention-mechanisms":
            print(json.dumps(focus_graph.get("focus"), indent=2))
            fail("focused graph export did not resolve the concept page")

        canvas_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_graph_export.py",
                str(vault),
                "--format",
                "obsidian-canvas",
                "--output",
                "canvas/wiki-graph.canvas",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if canvas_result.returncode != 0:
            print(canvas_result.stdout)
            fail("Obsidian Canvas graph export failed")
        canvas = json.loads(read(vault / "canvas" / "wiki-graph.canvas"))
        if not canvas.get("nodes") or not canvas.get("edges"):
            fail("Obsidian Canvas export did not contain nodes and edges")

        lint_result = subprocess.run(
            [sys.executable, "scripts/wiki_lint.py", str(vault), "--graph", "--fail-on", "p1"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if lint_result.returncode != 0:
            print(lint_result.stdout)
            fail("wiki_lint.py --graph produced P0/P1 findings for the minimal vault")

        outside = Path(tmp) / "outside.json"
        unsafe = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_graph_export.py",
                str(vault),
                "--format",
                "json",
                "--output",
                str(outside),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if unsafe.returncode == 0:
            fail("graph export accepted an output path outside the vault")
        if "graph output must stay inside the vault" not in unsafe.stdout:
            print(unsafe.stdout)
            fail("graph export outside-vault failure did not explain the boundary")


def check_status_dashboard_layer() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_init.py",
                str(vault),
                "--repo-root",
                str(ROOT),
                "--obsidian",
                "--obsidian-skip-downloads",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("status dashboard test vault initialization failed")

        status_result = subprocess.run(
            [sys.executable, "scripts/wiki_status.py", str(vault)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if status_result.returncode != 0:
            print(status_result.stdout)
            fail("wiki_status.py failed on an initialized vault")
        try:
            status_result.stdout.encode("gbk")
        except UnicodeEncodeError as exc:
            print(status_result.stdout)
            fail(f"wiki_status.py default output is not Windows GBK stdout-safe: {exc}")
        for text in ["Raw inbox", "Draft source pages", "Science review queue", "Agent Prompt Templates"]:
            if text not in status_result.stdout:
                print(status_result.stdout)
                fail(f"wiki_status.py output missing {text!r}")

        existing = subprocess.run(
            [sys.executable, "scripts/wiki_status.py", str(vault), "--write-dashboard"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if existing.returncode == 0:
            print(existing.stdout)
            fail("wiki_status.py overwrote an existing dashboard without --force")
        if "without --force" not in existing.stdout:
            print(existing.stdout)
            fail("wiki_status.py dashboard overwrite refusal did not explain --force")

        forced = subprocess.run(
            [sys.executable, "scripts/wiki_status.py", str(vault), "--write-dashboard", "--force"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if forced.returncode != 0:
            print(forced.stdout)
            fail("wiki_status.py --write-dashboard --force failed")

        outside = Path(tmp) / "outside.md"
        expect_command_failure(
            [sys.executable, "scripts/wiki_status.py", str(vault), "--write-dashboard", "--output", str(outside)],
            "dashboard output must stay inside the vault",
            "wiki_status.py accepted dashboard output outside the vault",
        )
        expect_command_failure(
            [sys.executable, "scripts/wiki_status.py", str(vault), "--write-dashboard", "--output", "sources/status.md"],
            "dashboard output must not rewrite raw, source, draft, concept, claim, report, or state files",
            "wiki_status.py accepted a dashboard output under sources/",
        )


def check_claim_extraction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "minimal-vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", vault)
        result = subprocess.run(
            [sys.executable, "scripts/wiki_claims.py", str(vault), "--format", "json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("claim extraction failed on minimal vault")

        rows = [json.loads(line) for line in read(vault / "claims" / "claims.jsonl").splitlines() if line.strip()]
        if not rows:
            fail("claim extraction produced no claims")
        for row in rows:
            if row.get("claim_type") != "metric":
                continue
            evidence = str(row.get("evidence", ""))
            if not evidence.startswith("sources/LLM-0001.md#Key Data"):
                fail("metric claim evidence must point back to a source page anchor")


def check_semantic_qa_qualitative_metric_placeholder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "minimal-vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", vault)
        claim = {
            "claim_id": "claim-qualitative-placeholder",
            "source_id": "LLM-0001",
            "claim_type": "metric",
            "subject": "Attention Test",
            "predicate": "Reported claim",
            "object": "qualitative claim",
            "value": None,
            "unit": "",
            "baseline": "as stated in source",
            "evidence": "sources/LLM-0001.md#L1",
            "concepts": ["attention-mechanisms"],
            "confidence": 0.82,
            "needs_review": False,
            "metric_key": "qualitative",
            "normalized_value": None,
            "normalized_unit": "",
            "unit_family": "numeric",
            "baseline_key": "",
            "protocol_key": "",
            "normalization_warnings": ["missing_normalized_value", "baseline_not_normalized"],
        }
        (vault / "claims" / "claims.jsonl").write_text(json.dumps(claim) + "\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "scripts/wiki_semantic_qa.py", str(vault), "--fail-on", "p1"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("semantic QA rejected a qualitative metric placeholder as a numeric metric")
        if "metric value is not visible on anchored line" in result.stdout:
            print(result.stdout)
            fail("semantic QA still emitted a numeric visibility issue for a qualitative placeholder")


def check_setup_script() -> None:
    text = read(ROOT / "setup.sh")
    if ".claude/skills" not in text:
        fail("setup.sh must default to Claude Code skill directory")
    if "OPEN_LLM_WIKI_SKILL_DIR" not in text:
        fail("setup.sh must allow overriding skill directory")
    if not re.search(r"trap\s+cleanup\s+EXIT", text):
        fail("setup.sh must clean temp directory with trap")


def find_setup_python() -> str:
    for name in ["python3", "python", sys.executable]:
        path = shutil.which(name) if name != sys.executable else name
        if not path:
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return path
    fail("setup runtime smoke test requires a working python3 or python")


def check_setup_python_probe() -> None:
    original_path = os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if os.name == "nt":
            failing = tmp_path / "python3.cmd"
            working = tmp_path / "python.cmd"
            failing.write_text("@exit /b 49\n", encoding="utf-8")
            working.write_text(f'@"{sys.executable}" %*\n', encoding="utf-8")
        else:
            failing = tmp_path / "python3"
            working = tmp_path / "python"
            failing.write_text("#!/usr/bin/env sh\nexit 49\n", encoding="utf-8")
            working.write_text(f'#!/usr/bin/env sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
            failing.chmod(0o755)
            working.chmod(0o755)

        try:
            os.environ["PATH"] = str(tmp_path)
            selected = Path(find_setup_python()).resolve()
        finally:
            os.environ["PATH"] = original_path

        if selected == failing.resolve():
            fail("setup python probe selected an unusable python3 candidate")


def check_setup_runtime() -> None:
    python_bin = find_setup_python()
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        result = subprocess.run(
            [
                python_bin,
                "scripts/wiki_init.py",
                str(vault),
                "--repo-root",
                str(ROOT),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("setup runtime smoke test failed")
        index = read(vault / "index.md")
        required = ["Pipeline Status", "raw/*_markdown/combined.md", "No source pages", "No claims"]
        missing = [item for item in required if item not in index]
        if missing:
            print(index)
            fail(f"initialized vault index missing pipeline state guidance: {missing}")


def check_ingest_corpus_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/wiki_ingest_corpus.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print(result.stdout)
        fail("wiki_ingest_corpus.py --help failed")
    required = [
        "raw/*_markdown/combined.md",
        "draft source pages",
        "QA report generation",
        "sources/LLM-NNNN.md",
        "contradiction",
        "concept pages",
        "index.md",
        "log.md",
        "Resume behavior:",
        "--resume",
        "--concepts-file",
    ]
    missing = [item for item in required if item not in result.stdout]
    if missing:
        print(result.stdout)
        fail(f"wiki_ingest_corpus.py --help missing expected guidance: {missing}")


def check_ingest_corpus_boundary_usage() -> None:
    text = read(ROOT / "scripts" / "wiki_ingest_corpus.py")
    if "ensure_within" not in text:
        fail("wiki_ingest_corpus.py must use ensure_within for vault write boundaries")


def check_pdf_to_markdown_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/pdf_to_markdown.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print(result.stdout)
        fail("pdf_to_markdown.py --help failed")
    required = [
        "API settings:",
        "OPEN_LLM_WIKI_LAYOUT_TOKEN",
        "AI_STUDIO_LAYOUT_TOKEN",
        "OPEN_LLM_WIKI_LAYOUT_API_URL",
        "Output behavior:",
        "doc_*.md",
        "combined Markdown",
        "manifest.json",
        "--dry-run",
    ]
    missing = [item for item in required if item not in result.stdout]
    if missing:
        print(result.stdout)
        fail(f"pdf_to_markdown.py --help missing expected guidance: {missing}")

    corpus_help = subprocess.run(
        [sys.executable, "scripts/pdf_corpus_to_markdown.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if corpus_help.returncode != 0:
        print(corpus_help.stdout)
        fail("pdf_corpus_to_markdown.py --help failed")
    corpus_required = [
        "--parser",
        "auto",
        "local-text",
        "layout-api",
        "Parser backend.",
    ]
    corpus_missing = [item for item in corpus_required if item not in corpus_help.stdout]
    if corpus_missing:
        print(corpus_help.stdout)
        fail(f"pdf_corpus_to_markdown.py --help missing expected parser guidance: {corpus_missing}")


def run_runtime_checks() -> None:
    commands = [
        [sys.executable, "scripts/wiki_lint.py", "examples/minimal-vault", "--fail-on", "p1"],
        [sys.executable, "scripts/wiki_search.py", "examples/minimal-vault", "attention transformer", "--limit", "2"],
        [sys.executable, "scripts/wiki_claims.py", "--help"],
        [sys.executable, "scripts/wiki_concept_revision.py", "--help"],
        [sys.executable, "scripts/wiki_contradictions.py", "--help"],
        [sys.executable, "scripts/wiki_discover_sources.py", "--help"],
        [sys.executable, "scripts/wiki_graph_export.py", "--help"],
        [sys.executable, "scripts/wiki_grow.py", "--help"],
        [sys.executable, "scripts/wiki_ingest_corpus.py", "--help"],
        [sys.executable, "scripts/wiki_normalize_metrics.py", "--help"],
        [sys.executable, "scripts/wiki_queue.py", "--help"],
        [sys.executable, "scripts/wiki_science_review.py", "--help"],
        [sys.executable, "scripts/wiki_semantic_qa.py", "--help"],
        [sys.executable, "scripts/pdf_corpus_report.py", "--help"],
        [sys.executable, "scripts/pdf_corpus_to_markdown.py", "--help"],
        [sys.executable, "scripts/pdf_to_markdown.py", "--help"],
        [sys.executable, "scripts/wiki_obsidian_setup.py", "--help"],
        [sys.executable, "scripts/wiki_eval.py"],
        [sys.executable, "scripts/wiki_status.py", "--help"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            print(result.stdout)
            fail(f"runtime check failed: {' '.join(command)}")

    semantic_help = subprocess.run(
        [sys.executable, "scripts/wiki_semantic_qa.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if "p1 fails on P0/P1" not in semantic_help.stdout:
        fail("semantic QA help must document fail-on severity thresholds")

    science_help = subprocess.run(
        [sys.executable, "scripts/wiki_science_review.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if "Write qa-reports/science-review" not in science_help.stdout:
        fail("science review help must document report mode")

    contradiction_help = subprocess.run(
        [sys.executable, "scripts/wiki_contradictions.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if "Relative numeric spread threshold" not in contradiction_help.stdout:
        fail("contradiction help must document candidate detection behavior")
    if "Write qa-reports/claim-contradictions" not in contradiction_help.stdout:
        fail("contradiction help must document report mode")
    if "Exit non-zero when numeric contradiction candidates" not in contradiction_help.stdout:
        fail("contradiction help must document fail-on-candidate behavior")

    concept_help = subprocess.run(
        [sys.executable, "scripts/wiki_concept_revision.py", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if "preview mode" not in concept_help.stdout or "without writing" not in concept_help.stdout:
        fail("concept revision help must document preview mode")
    if "Write updated concept pages and log entries" not in concept_help.stdout:
        fail("concept revision help must document apply mode")


def check_pdf_to_markdown_http_errors() -> None:
    class FailingHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")

        def log_message(self, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), FailingHandler)
    server.timeout = 10
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.pdf"
            output_dir = root / "out"
            input_path.write_bytes(b"%PDF-1.4 fake")
            env = os.environ.copy()
            env["OPEN_LLM_WIKI_LAYOUT_TOKEN"] = "fake"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/pdf_to_markdown.py",
                    str(input_path),
                    "--output",
                    str(output_dir),
                    "--api-url",
                    f"http://127.0.0.1:{server.server_address[1]}/layout",
                    "--retries",
                    "0",
                    "--timeout",
                    "5",
                    "--no-download-images",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if result.returncode == 0:
                print(result.stdout)
                fail("pdf_to_markdown.py accepted a failing layout API response")
            if "layout API request failed:" not in result.stdout or "Traceback" in result.stdout:
                print(result.stdout)
                fail("pdf_to_markdown.py did not print a clear HTTP failure")
            if (output_dir / "combined.md").exists() or (output_dir / "manifest.json").exists():
                fail("pdf_to_markdown.py wrote success outputs after a failing layout API response")
    finally:
        thread.join(timeout=5)
        server.server_close()


def expect_command_failure(command: list[str], expected: str, message: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode == 0:
        print(result.stdout)
        fail(message)
    if expected not in result.stdout:
        print(result.stdout)
        fail(f"{message}; missing expected text {expected!r}")
    return result.stdout


def check_pdf_corpus_to_markdown_progress_log() -> None:
    class SlowSuccessHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            time.sleep(2)
            body = {
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "# Slow Test\n\nConverted.", "images": {}}, "outputImages": {}}
                    ]
                }
            }
            data = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), SlowSuccessHandler)
    server.timeout = 10
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "pdfs"
            output_root = root / "raw"
            input_dir.mkdir()
            (input_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
            log_path = root / "progress.tsv"
            env = os.environ.copy()
            env["OPEN_LLM_WIKI_LAYOUT_TOKEN"] = "fake"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "scripts/pdf_corpus_to_markdown.py",
                    str(input_dir),
                    "--output-root",
                    str(output_root),
                    "--parser",
                    "layout-api",
                    "--api-url",
                    f"http://127.0.0.1:{server.server_address[1]}/layout",
                    "--retries",
                    "0",
                    "--timeout",
                    "10",
                    "--no-download-images",
                    "--log",
                    str(log_path),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            deadline = time.time() + 1.0
            during = ""
            while time.time() < deadline:
                if log_path.exists():
                    during = log_path.read_text(encoding="utf-8")
                    if "\tSTART\t" in during:
                        break
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            output, _ = proc.communicate(timeout=20)
            final = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            if "\tSTART\t" not in during:
                print(output)
                print(final)
                fail("corpus converter did not write an in-flight START progress row")
            if proc.returncode != 0:
                print(output)
                fail("corpus converter progress test failed")
            if "\tOK\t" not in final:
                print(final)
                fail("corpus converter did not preserve the final OK audit row")
    finally:
        thread.join(timeout=5)
        server.server_close()


def check_pdf_corpus_to_markdown_local_parser_dry_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        input_dir = root / "pdfs"
        output_root = root / "raw"
        input_dir.mkdir()
        (input_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/pdf_corpus_to_markdown.py",
                str(input_dir),
                "--output-root",
                str(output_root),
                "--parser",
                "local-text",
                "--dry-run",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("corpus converter rejected local-text parser dry-run")
        if "[parser=local-text]" not in result.stdout:
            print(result.stdout)
            fail("corpus converter dry-run did not show local parser plan")
        if output_root.exists():
            fail("corpus converter local parser dry-run wrote output files")


def check_writeback_semantic_qa_gate() -> None:
    vault = ROOT / "examples" / "minimal-vault"
    with tempfile.TemporaryDirectory() as tmp:
        writeback_vault = Path(tmp) / "writeback-qa-vault"
        shutil.copytree(vault, writeback_vault)
        (writeback_vault / "qa-reports" / "semantic-qa-2026-05-04.md").write_text(
            "\n".join(
                [
                    "# Semantic QA Report",
                    "- date: 2026-05-04",
                    f"- vault: {writeback_vault}",
                    "- claims: 1",
                    "- p0: 0",
                    "- p1: 1",
                    "- p2: 0",
                    "- verdict: FAIL",
                    "",
                    "## Findings",
                    "- [P1] LLM-0001: metric value is not visible on anchored line",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        command = [
            sys.executable,
            "scripts/wiki_writeback.py",
            str(writeback_vault),
            "--target",
            "concepts/attention-mechanisms.md",
            "--query",
            "summarize attention",
            "--body",
            "Attention evidence should be reviewed before autonomous writeback. [[LLM-0001]]",
        ]
        proposal = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proposal.returncode != 0:
            print(proposal.stdout)
            fail("writeback proposal rejected a vault with failing semantic QA")
        if "WARNING: latest semantic QA report is not clean" not in proposal.stdout or "p1=1" not in proposal.stdout:
            print(proposal.stdout)
            fail("writeback proposal did not warn about failing semantic QA")
        expect_command_failure(
            command + ["--apply"],
            "writeback not applied",
            "writeback applied despite failing semantic QA",
        )
        allowed = subprocess.run(
            command + ["--apply", "--allow-failing-qa"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if allowed.returncode != 0:
            print(allowed.stdout)
            fail("writeback explicit failing-QA override was rejected")
        if "applied writeback" not in allowed.stdout:
            print(allowed.stdout)
            fail("writeback explicit failing-QA override did not apply the writeback")


def check_safety_boundaries() -> None:
    vault = ROOT / "examples" / "minimal-vault"
    with tempfile.TemporaryDirectory() as tmp:
        outside = Path(tmp) / "outside.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_normalize_metrics.py",
                str(vault),
                "--output",
                str(outside),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("normalization accepted an output path outside the vault")
        if "under claims/" not in result.stdout:
            print(result.stdout)
            fail("normalization boundary failure did not explain the claims/ constraint")

        outside_claims = Path(tmp) / "outside-claims.jsonl"
        outside_claims.write_text(read(vault / "claims" / "claims.jsonl"), encoding="utf-8")
        original_claims = read(outside_claims)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_normalize_metrics.py",
                str(vault),
                "--claims",
                str(outside_claims),
                "--in-place",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("normalization accepted an in-place claims path outside the vault")
        if "must stay inside the vault" not in result.stdout:
            print(result.stdout)
            fail("normalization in-place boundary failure did not explain the vault constraint")
        if read(outside_claims) != original_claims:
            fail("normalization modified an in-place claims path outside the vault")

        normalize_vault = Path(tmp) / "normalize-vault"
        shutil.copytree(vault, normalize_vault)
        raw_target = normalize_vault / "raw" / "evil.md"
        raw_target.write_text("# Raw evidence placeholder\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "scripts/wiki_claims.py", str(normalize_vault)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("failed to prepare claims for normalization boundary check")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_normalize_metrics.py",
                str(normalize_vault),
                "--output",
                str(raw_target),
                "--report",
                str(normalize_vault / "claims" / "metric-normalization-report.md"),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("normalization accepted an output path outside claims/")
        if "under claims/" not in result.stdout:
            print(result.stdout)
            fail("normalization output boundary failure did not explain the claims/ constraint")
        if "claim_id" in raw_target.read_text(encoding="utf-8"):
            fail("normalization modified raw evidence through an unsafe output path")

        writeback_vault = Path(tmp) / "writeback-vault"
        shutil.copytree(vault, writeback_vault)
        unsafe_writeback = writeback_vault / "raw" / "concepts" / "unsafe.md"
        unsafe_writeback.parent.mkdir(parents=True, exist_ok=True)
        unsafe_writeback.write_text("# Raw evidence placeholder\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_writeback.py",
                str(writeback_vault),
                "--target",
                "raw/concepts/unsafe.md",
                "--query",
                "unsafe writeback",
                "--body",
                "This should not be written. [[LLM-0001]]",
                "--apply",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("writeback accepted a target outside top-level concepts/")
        if "under concepts/" not in result.stdout:
            print(result.stdout)
            fail("writeback boundary failure did not explain the concepts/ constraint")

        revision_vault = Path(tmp) / "revision-vault"
        shutil.copytree(vault, revision_vault)
        raw_revision_target = revision_vault / "raw" / "evil.md"
        raw_revision_target.write_text("# Raw evidence placeholder\n", encoding="utf-8")
        (revision_vault / "claims" / "claims.jsonl").write_text(
            (
                '{"claim_id":"claim-unsafe","source_id":"LLM-0001",'
                '"claim_type":"contribution",'
                '"object":"unsafe concept id should not rewrite raw",'
                '"evidence":"sources/LLM-0001.md#L1",'
                '"concepts":["../raw/evil"],"needs_review":false}\n'
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "scripts/wiki_concept_revision.py", str(revision_vault), "--apply"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("concept revision accepted a target outside concepts/")
        if "under concepts/" not in result.stdout:
            print(result.stdout)
            fail("concept revision boundary failure did not explain the concepts/ constraint")
        if "Semantic Claim Matrix" in raw_revision_target.read_text(encoding="utf-8"):
            fail("concept revision modified raw evidence through an unsafe concept id")

        claims_vault = Path(tmp) / "claims-vault"
        shutil.copytree(vault, claims_vault)
        raw_claims_target = claims_vault / "raw" / "evil.md"
        raw_claims_target.write_text("# Raw evidence placeholder\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_claims.py",
                str(claims_vault),
                "--output",
                str(raw_claims_target),
                "--report",
                str(claims_vault / "claims" / "claim-report.md"),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("claim extraction accepted an output path outside claims/")
        if "under claims/" not in result.stdout:
            print(result.stdout)
            fail("claim output boundary failure did not explain the claims/ constraint")
        if "claim_id" in raw_claims_target.read_text(encoding="utf-8"):
            fail("claim extraction modified raw evidence through an unsafe output path")

        semantic_vault = Path(tmp) / "semantic-vault"
        shutil.copytree(vault, semantic_vault)
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_semantic_qa.py",
                str(semantic_vault),
                "--write-report",
                "--report",
                str(Path(tmp) / "semantic-outside.md"),
            ],
            "semantic QA report must stay inside the vault",
            "semantic QA accepted a report path outside the vault",
        )

        science_vault = Path(tmp) / "science-vault"
        shutil.copytree(vault, science_vault)
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_science_review.py",
                str(science_vault),
                "--write-report",
                "--report",
                str(Path(tmp) / "science-outside.md"),
            ],
            "science review report must stay inside the vault",
            "science review accepted a report path outside the vault",
        )

        contradiction_vault = Path(tmp) / "contradiction-vault"
        shutil.copytree(vault, contradiction_vault)
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_contradictions.py",
                str(contradiction_vault),
                "--write-report",
                "--report",
                str(Path(tmp) / "contradictions-outside.md"),
            ],
            "contradiction report must stay inside the vault",
            "contradiction scan accepted a report path outside the vault",
        )

        discovery_vault = Path(tmp) / "discovery-vault"
        shutil.copytree(vault, discovery_vault)
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_discover_sources.py",
                str(discovery_vault),
                "--registry",
                str(Path(tmp) / "registry-outside.jsonl"),
            ],
            "discovery outputs must stay inside the vault",
            "source discovery accepted a registry path outside the vault",
        )
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_discover_sources.py",
                str(discovery_vault),
                "--report",
                str(Path(tmp) / "discovery-outside.md"),
            ],
            "discovery outputs must stay inside the vault",
            "source discovery accepted a report path outside the vault",
        )

        writeback_outside_vault = Path(tmp) / "writeback-outside-vault"
        shutil.copytree(vault, writeback_outside_vault)
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_writeback.py",
                str(writeback_outside_vault),
                "--target",
                "../outside.md",
                "--query",
                "unsafe writeback",
                "--body",
                "This should not be written. [[LLM-0001]]",
                "--apply",
            ],
            "target must stay inside the vault",
            "writeback accepted a target outside the vault",
        )
        expect_command_failure(
            [
                sys.executable,
                "scripts/wiki_writeback.py",
                str(writeback_outside_vault),
                "--target",
                "sources/LLM-0001.md",
                "--query",
                "unsafe writeback",
                "--body",
                "This should not be written. [[LLM-0001]]",
                "--apply",
            ],
            "writeback target must be under concepts/",
            "writeback accepted a non-concepts target",
        )


def check_pdf_corpus_report_short_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = Path(tmp) / "raw"
        output_dir = raw_dir / "paper_markdown"
        output_dir.mkdir(parents=True)
        (raw_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        (output_dir / "combined.md").write_text("tiny\n", encoding="utf-8")
        (output_dir / "manifest.json").write_text('{"attempts": 1}\n', encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/pdf_corpus_report.py",
                str(raw_dir),
                "--fail-on-short",
                "--min-combined-bytes",
                "100",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            print(result.stdout)
            fail("corpus report accepted a suspiciously short combined Markdown output")
        if "short_files: 1" not in result.stdout:
            print(result.stdout)
            fail("corpus report did not identify the short combined Markdown output")
        alias_result = subprocess.run(
            [
                sys.executable,
                "scripts/pdf_corpus_report.py",
                str(raw_dir),
                "--fail-on-suspicious",
                "--min-bytes",
                "100",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if alias_result.returncode == 0:
            print(alias_result.stdout)
            fail("corpus report accepted a short output through --fail-on-suspicious")
        if "short_files: 1" not in alias_result.stdout:
            print(alias_result.stdout)
            fail("corpus report --min-bytes alias did not identify the short combined Markdown output")


def check_pdf_corpus_report_parser_warnings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = Path(tmp) / "raw"
        output_dir = raw_dir / "paper_markdown"
        output_dir.mkdir(parents=True)
        (raw_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        (output_dir / "combined.md").write_text("converted markdown\n", encoding="utf-8")
        (output_dir / "manifest.json").write_text(
            '{"attempts": 1, "warnings": ["parser warning: table dropped"]}\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "scripts/pdf_corpus_report.py",
                str(raw_dir),
                "--fail-on-parser-warnings",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            print(result.stdout)
            fail("corpus report accepted parser warnings")
        if "parser_warnings: 1" not in result.stdout:
            print(result.stdout)
            fail("corpus report did not identify parser warnings")


def check_pdf_corpus_report_nested_raw_layout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = Path(tmp) / "raw"
        pdf_dir = raw_dir / "deepseek_paper"
        output_dir = raw_dir / "paper_markdown"
        pdf_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        (pdf_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        (output_dir / "combined.md").write_text("converted markdown\n", encoding="utf-8")
        (output_dir / "manifest.json").write_text('{"attempts": 1}\n', encoding="utf-8")
        for report_dir in [raw_dir, pdf_dir]:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/pdf_corpus_report.py",
                    str(report_dir),
                    "--expect-count",
                    "1",
                    "--fail-on-missing",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if result.returncode != 0:
                print(result.stdout)
                fail("corpus report rejected a nested raw evidence layout")
            if "pdfs: 1" not in result.stdout or "combined_files: 1" not in result.stdout:
                print(result.stdout)
                fail("corpus report did not count nested PDFs and sibling Markdown outputs")


def check_source_discovery_arxiv_filename() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("source discovery test vault initialization failed")
        (vault / "raw" / "DeepSeek_Test_2401.00001.pdf").write_bytes(b"%PDF-1.4 fake")
        result = subprocess.run(
            [sys.executable, "scripts/wiki_discover_sources.py", str(vault), "--format", "json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            fail("source discovery arxiv filename test failed")
        registry = (vault / "_state" / "source-registry.jsonl").read_text(encoding="utf-8")
        if '"arxiv": "2401.00001"' not in registry:
            print(registry)
            fail("source discovery did not extract arXiv ID from filename")


def check_corpus_ingest_fresh_vault() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("fresh vault initialization failed")
        markdown_dir = vault / "raw" / "DeepSeek_Test_2401.00001_markdown"
        markdown_dir.mkdir(parents=True)
        (vault / "raw" / "DeepSeek_Test_2401.00001.pdf").write_bytes(b"%PDF-1.4 fake")
        (markdown_dir / "combined.md").write_text(
            "# DeepSeek Test Model\n\n"
            "Abstract\n"
            "DeepSeek Test Model uses 2B parameters and 1.5B training tokens for code and math benchmarks. "
            "HumanEval score is 75% against a 60% baseline and MATH score is 62% across 500 samples.\n\n"
            "1 Introduction\n"
            "The model has 2B parameters and uses 1.5B tokens during training for code and math benchmarks.\n",
            encoding="utf-8",
        )
        ingest_result = subprocess.run(
            [sys.executable, "scripts/wiki_ingest_corpus.py", str(vault), "--today", "2026-05-03"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if ingest_result.returncode != 0:
            print(ingest_result.stdout)
            fail("fresh vault corpus ingest failed")
        if not (vault / "sources" / "LLM-0001.md").exists():
            print(ingest_result.stdout)
            fail("fresh vault corpus ingest did not create sources/LLM-0001.md")


def check_corpus_ingest_generic_concepts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("generic concept vault initialization failed")
        concepts_file = Path(tmp) / "concepts.json"
        concepts_file.write_text(
            json.dumps(
                {
                    "sequence-transduction": [
                        "Sequence Transduction",
                        "How models map input sequences into output sequences.",
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        markdown_dir = vault / "raw" / "Attention_Is_All_You_Need_1706.03762_markdown"
        markdown_dir.mkdir(parents=True)
        (vault / "raw" / "Attention_Is_All_You_Need_1706.03762.pdf").write_bytes(b"%PDF-1.4 fake")
        (markdown_dir / "combined.md").write_text(
            "# Attention Is All You Need\n\n"
            "Abstract\n"
            "The Transformer relies on multi-head self-attention for sequence transduction and language modeling. "
            "It reports a WMT 2014 EN-DE BLEU score of 27.3 for the base model against recurrent and convolutional baselines.\n\n"
            "1 Introduction\n"
            "Self-attention connects all tokens directly and removes recurrent sequence computation.\n",
            encoding="utf-8",
        )
        ingest_result = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_ingest_corpus.py",
                str(vault),
                "--today",
                "2026-05-03",
                "--concepts-file",
                str(concepts_file),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if ingest_result.returncode != 0:
            print(ingest_result.stdout)
            fail("generic corpus ingest failed")
        source_text = read(vault / "sources" / "LLM-0001.md")
        if "deepseek-family" in source_text:
            print(source_text)
            fail("generic corpus ingest incorrectly fell back to the DeepSeek concept")
        for concept in ["attention-mechanisms", "transformer-architectures", "sequence-transduction"]:
            if not (vault / "concepts" / f"{concept}.md").exists():
                print(ingest_result.stdout)
                fail(f"generic corpus ingest did not create expected concept: {concept}")


def check_corpus_ingest_metric_noise_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("metric noise vault initialization failed")
        markdown_dir = vault / "raw" / "DeepSeek_Metric_Noise_2401.00001_markdown"
        markdown_dir.mkdir(parents=True)
        (vault / "raw" / "DeepSeek_Metric_Noise_2401.00001.pdf").write_bytes(b"%PDF-1.4 fake")
        (markdown_dir / "combined.md").write_text(
            "# DeepSeek Metric Noise Test\n\n"
            "Abstract\n"
            "The model has 16B parameters and activates 2.4B parameters for each token while "
            "supporting a 128K token context for long-context evaluation.\n\n"
            "1 Introduction\n"
            "Math datasets include GSM8K and MATH, but this line intentionally reports no score or metric value.\n"
            "H. Xin and collaborators released a related arXiv preprint in 2024b with no model metric on this line.\n"
            "The recurrence uses $2k - 1$ terms in the derivation without reporting a benchmark result.\n"
            "The context length is 128K tokens for long-context evaluation.\n",
            encoding="utf-8",
        )
        ingest_result = subprocess.run(
            [sys.executable, "scripts/wiki_ingest_corpus.py", str(vault), "--today", "2026-05-03"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if ingest_result.returncode != 0:
            print(ingest_result.stdout)
            fail("metric noise corpus ingest failed")
        source_text = read(vault / "sources" / "LLM-0001.md")
        try:
            key_data = source_text.split("## Key Data", 1)[1].split("## Timeline Position", 1)[0]
        except IndexError:
            print(source_text)
            fail("metric noise source page missing Key Data section")
        for expected in ["16B", "2.4B", "128K"]:
            if expected not in key_data:
                print(source_text)
                fail(f"metric noise filter dropped valid metric value: {expected}")
        for noisy in ["GSM8K", "2024b", "2k - 1"]:
            if noisy in key_data:
                print(source_text)
                fail(f"metric noise filter kept low-signal metric fragment: {noisy}")


def check_corpus_ingest_resume_continues() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("resume test vault initialization failed")
        for name in ["DeepSeek_A_2401.00001", "DeepSeek_B_2402.00002"]:
            markdown_dir = vault / "raw" / f"{name}_markdown"
            markdown_dir.mkdir(parents=True)
            (vault / "raw" / f"{name}.pdf").write_bytes(f"%PDF-1.4 fake {name}\n".encode("utf-8"))
            (markdown_dir / "combined.md").write_text(
                f"# {name}\n\n"
                "Abstract\n"
                f"{name} uses 2B parameters and 1.5B training tokens for code and math benchmarks. "
                "HumanEval score is 75% against a 60% baseline and MATH score is 62% across 500 samples.\n",
                encoding="utf-8",
            )
        first = subprocess.run(
            [
                sys.executable,
                "scripts/wiki_ingest_corpus.py",
                str(vault),
                "--today",
                "2026-05-03",
                "--force-empty",
                "--limit",
                "1",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if first.returncode != 0:
            print(first.stdout)
            fail("initial partial corpus ingest failed")
        resumed = subprocess.run(
            [sys.executable, "scripts/wiki_ingest_corpus.py", str(vault), "--today", "2026-05-03", "--resume"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if resumed.returncode != 0:
            print(resumed.stdout)
            fail("resume corpus ingest failed")
        if not (vault / "sources" / "LLM-0002.md").exists():
            print(resumed.stdout)
            fail("resume corpus ingest did not continue to LLM-0002")
        lint = subprocess.run(
            [sys.executable, "scripts/wiki_lint.py", str(vault), "--fail-on", "p1"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if lint.returncode != 0:
            print(lint.stdout)
            fail("resumed corpus vault failed p1 lint")


def check_dashboard_action_model() -> None:
    """Verify dashboard action model generation, persistence, and resolve/ignore."""
    import datetime as dt
    vault = ROOT / "examples" / "minimal-vault"

    # Test: --actions generates valid JSON
    result = subprocess.run(
        [sys.executable, "scripts/wiki_status.py", str(vault), "--actions"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        print(result.stdout)
        fail("dashboard actions: --actions failed")
    data = json.loads(result.stdout)
    if "open_actions" not in data:
        fail("dashboard actions: missing open_actions")
    if not isinstance(data["open_actions"], list):
        fail("dashboard actions: open_actions not a list")

    # Test: _state/actions.jsonl exists and matches
    actions_jsonl = vault / "_state" / "actions.jsonl"
    if not actions_jsonl.exists():
        fail("dashboard actions: actions.jsonl not created")
    rows = [json.loads(l) for l in read(actions_jsonl).splitlines() if l.strip()]
    if len(rows) != data["total_actions"]:
        fail("dashboard actions: actions.jsonl count mismatch")

    # Test: required fields
    required = {"action_id", "kind", "severity", "title", "body", "reason",
                "status", "primary_object_type", "primary_object_id"}
    for row in rows:
        missing = required - set(row)
        if missing:
            fail(f"dashboard actions: row missing fields {sorted(missing)}")

    # Test: --write-dashboard produces Action Panel
    result2 = subprocess.run(
        [sys.executable, "scripts/wiki_status.py", str(vault), "--write-dashboard", "--force"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if result2.returncode != 0:
        print(result2.stdout)
        fail("dashboard actions: --write-dashboard failed")
    dashboard = read(vault / "_dashboard.md")
    if "## Action Panel" not in dashboard:
        fail("dashboard actions: Action Panel missing from dashboard")
    if "What should I do next" not in dashboard:
        fail("dashboard actions: guidance text missing")

    print("dashboard action model: OK")


def check_claim_ledger_schema() -> None:
    """Verify claim ledger row schema compliance."""
    import hashlib
    vault = ROOT / "examples" / "minimal-vault"
    claims_path = vault / "claims" / "claims.jsonl"
    if not claims_path.exists():
        fail("claim ledger: claims.jsonl not found in minimal-vault")

    required_fields = {
        "claim_id", "source_uuid", "source_id", "chunk_id", "claim_text",
        "normalized_claim", "evidence_quote", "evidence_hash", "anchor",
        "verdict", "created_at", "updated_at",
    }

    for i, line in enumerate(read(claims_path).splitlines(), 1):
        if not line.strip():
            continue
        claim = json.loads(line)
        missing = required_fields - set(claim)
        if missing:
            fail(f"claim ledger row {i}: missing fields {sorted(missing)}")
        eq = str(claim.get("evidence_quote", ""))
        if len(eq) > 300:
            fail(f"claim ledger row {i}: evidence_quote exceeds 300 chars")
        eh = str(claim.get("evidence_hash", ""))
        if eq and eh:
            expected = hashlib.sha256(eq.encode("utf-8")).hexdigest()[:16]
            if eh != expected:
                fail(f"claim ledger row {i}: evidence_hash mismatch")
    print("claim ledger schema: OK")


def check_claim_ledger_verdict_synthesis() -> None:
    """Verify contradicted claims don't enter stable concept synthesis."""
    import hashlib
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", vault)

        run_cwd([sys.executable, "scripts/wiki_claims.py", str(vault)], ROOT)
        run_cwd([sys.executable, "scripts/wiki_normalize_metrics.py", str(vault), "--in-place"], ROOT)
        run_cwd([sys.executable, "scripts/wiki_semantic_qa.py", str(vault), "--assign-verdicts", "--in-place"], ROOT)

        claims_path = vault / "claims" / "claims.jsonl"
        claims = [json.loads(l) for l in read(claims_path).splitlines() if l.strip()]

        # Mark first claim contradicted
        claims[0]["verdict"] = "contradicted"
        write_jsonl(claims_path, claims)

        run_cwd([sys.executable, "scripts/wiki_concept_revision.py", str(vault), "--apply"], ROOT)

        concept_path = vault / "concepts" / "attention-mechanisms.md"
        if concept_path.exists():
            concept_text = read(concept_path)
            cid = str(claims[0]["claim_id"])
            if cid in concept_text:
                fail("claim ledger: contradicted claim appeared in concept synthesis")

        # Verify lint catches evidence_hash mismatch
        claims[0]["verdict"] = "supported"
        claims[0]["evidence_hash"] = "bad_hash"
        write_jsonl(claims_path, claims)

        result = subprocess.run(
            [sys.executable, "scripts/wiki_lint.py", str(vault), "--fail-on", "p1"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            fail("claim ledger: lint should fail on evidence_hash mismatch")

    print("claim ledger verdict synthesis: OK")


def check_claim_ledger_stale_hook() -> None:
    """Verify stale source marks related claims stale."""
    with tempfile.TemporaryDirectory() as td:
        vault = Path(td) / "vault"
        shutil.copytree(ROOT / "examples" / "minimal-vault", vault)

        run_cwd([sys.executable, "scripts/wiki_claims.py", str(vault)], ROOT)

        claims_path = vault / "claims" / "claims.jsonl"
        sys.path.insert(0, str(ROOT / "scripts"))
        from wiki_claims import mark_stale_claims
        marked = mark_stale_claims(claims_path, {"LLM-0001"})
        if marked == 0:
            fail("claim ledger: mark_stale_claims marked 0 claims")

        claims = [json.loads(l) for l in read(claims_path).splitlines() if l.strip()]
        stale = [c for c in claims if c.get("verdict") == "stale"]
        if not stale:
            fail("claim ledger: no stale claims after mark_stale_claims")
        # Stale claims should have updated_at changed
        for c in stale:
            if not c.get("updated_at"):
                fail("claim ledger: stale claim missing updated_at")

    print("claim ledger stale hook: OK")


def check_ingest_plan_raw_source_stale_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        init_result = subprocess.run(
            [sys.executable, "scripts/wiki_init.py", str(vault), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if init_result.returncode != 0:
            print(init_result.stdout)
            fail("ingest plan stale contract vault initialization failed")
        raw_pdf = vault / "raw" / "paper_a.pdf"
        markdown_dir = vault / "raw" / "paper_a_markdown"
        markdown_dir.mkdir(parents=True)
        raw_pdf.write_bytes(b"%PDF-1.4 paper a v1\n")
        (markdown_dir / "combined.md").write_text(
            "# Paper A\n\n"
            "Abstract\n"
            "Paper A reports 7B parameters and HumanEval 75% against a 60% baseline. "
            "The source is long enough to generate a stable source page for stale-plan testing.\n",
            encoding="utf-8",
        )
        ingest = subprocess.run(
            [sys.executable, "scripts/wiki_ingest_corpus.py", str(vault), "--today", "2026-05-03"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if ingest.returncode != 0:
            print(ingest.stdout)
            fail("ingest plan stale contract initial ingest failed")
        write_plan = subprocess.run(
            [sys.executable, "scripts/wiki_ingest_plan.py", str(vault), "--write"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if write_plan.returncode != 0:
            print(write_plan.stdout)
            fail("ingest plan stale contract write failed")
        raw_pdf.write_bytes(b"%PDF-1.4 paper a v2 changed raw evidence\n")
        plan_result = subprocess.run(
            [sys.executable, "scripts/wiki_ingest_plan.py", str(vault), "--format", "json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if plan_result.returncode != 0:
            print(plan_result.stdout)
            fail("ingest plan stale contract plan failed")
        plan = json.loads(plan_result.stdout)
        item = plan["items"][0]
        if item.get("source_path") != "raw/paper_a.pdf":
            print(json.dumps(item, indent=2, sort_keys=True))
            fail("ingest plan source_path does not point to original raw evidence")
        if item.get("artifact_path") != "raw/paper_a_markdown/combined.md":
            print(json.dumps(item, indent=2, sort_keys=True))
            fail("ingest plan artifact_path does not point to combined artifact")
        if item.get("state") != "stale" or item.get("freshness_verdict") != "stale":
            print(json.dumps(item, indent=2, sort_keys=True))
            fail("ingest plan did not mark changed raw PDF as stale")
        if item.get("recommended_action") == "skip":
            print(json.dumps(item, indent=2, sort_keys=True))
            fail("ingest plan recommended skip for changed raw PDF")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def run_cwd(cmd: list[str], cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit(result.returncode)
    return result.stdout


def main() -> None:
    check_skills()
    check_docs()
    check_minimal_vault()
    check_vault_init_obsidian_graph_filter()
    check_obsidian_setup_layer()
    check_graph_export_layer()
    check_status_dashboard_layer()
    check_claim_extraction()
    check_semantic_qa_qualitative_metric_placeholder()
    check_setup_script()
    check_setup_python_probe()
    check_setup_runtime()
    check_ingest_corpus_help()
    check_ingest_corpus_boundary_usage()
    check_pdf_to_markdown_help()
    run_runtime_checks()
    check_pdf_to_markdown_http_errors()
    check_pdf_corpus_to_markdown_local_parser_dry_run()
    check_pdf_corpus_to_markdown_progress_log()
    check_writeback_semantic_qa_gate()
    check_safety_boundaries()
    check_pdf_corpus_report_short_outputs()
    check_pdf_corpus_report_parser_warnings()
    check_pdf_corpus_report_nested_raw_layout()
    check_source_discovery_arxiv_filename()
    check_corpus_ingest_fresh_vault()
    check_corpus_ingest_generic_concepts()
    check_corpus_ingest_metric_noise_filter()
    check_corpus_ingest_resume_continues()
    check_dashboard_action_model()
    check_claim_ledger_schema()
    check_claim_ledger_verdict_synthesis()
    check_claim_ledger_stale_hook()
    check_ingest_plan_raw_source_stale_contract()
    print("quality checks passed")


if __name__ == "__main__":
    main()
