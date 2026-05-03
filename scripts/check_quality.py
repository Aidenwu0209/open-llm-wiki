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


def symlink_dir(target: Path, link: Path) -> bool:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        return False
    return True


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
        "scripts/wiki_semantic_qa.py",
        "scripts/wiki_search.py",
        "scripts/wiki_writeback.py",
        "scripts/wiki_eval.py",
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


def check_setup_script() -> None:
    text = read(ROOT / "setup.sh")
    if ".claude/skills" not in text:
        fail("setup.sh must default to Claude Code skill directory")
    if "OPEN_LLM_WIKI_SKILL_DIR" not in text:
        fail("setup.sh must allow overriding skill directory")
    if not re.search(r"trap\s+cleanup\s+EXIT", text):
        fail("setup.sh must clean temp directory with trap")


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


def run_runtime_checks() -> None:
    commands = [
        [sys.executable, "scripts/wiki_lint.py", "examples/minimal-vault", "--fail-on", "p1"],
        [sys.executable, "scripts/wiki_search.py", "examples/minimal-vault", "attention transformer", "--limit", "2"],
        [sys.executable, "scripts/wiki_claims.py", "--help"],
        [sys.executable, "scripts/wiki_concept_revision.py", "--help"],
        [sys.executable, "scripts/wiki_contradictions.py", "--help"],
        [sys.executable, "scripts/wiki_discover_sources.py", "--help"],
        [sys.executable, "scripts/wiki_grow.py", "--help"],
        [sys.executable, "scripts/wiki_ingest_corpus.py", "--help"],
        [sys.executable, "scripts/wiki_normalize_metrics.py", "--help"],
        [sys.executable, "scripts/wiki_queue.py", "--help"],
        [sys.executable, "scripts/wiki_science_review.py", "--help"],
        [sys.executable, "scripts/wiki_semantic_qa.py", "--help"],
        [sys.executable, "scripts/pdf_corpus_report.py", "--help"],
        [sys.executable, "scripts/pdf_corpus_to_markdown.py", "--help"],
        [sys.executable, "scripts/pdf_to_markdown.py", "--help"],
        [sys.executable, "scripts/wiki_eval.py"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            print(result.stdout)
            fail(f"runtime check failed: {' '.join(command)}")


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
        if "must stay inside the vault" not in result.stdout:
            print(result.stdout)
            fail("normalization boundary failure did not explain the vault constraint")

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

        symlink_claims_vault = Path(tmp) / "symlink-claims-vault"
        shutil.copytree(vault, symlink_claims_vault)
        outside_claims_dir = Path(tmp) / "outside-claims-dir"
        outside_claims_dir.mkdir()
        shutil.rmtree(symlink_claims_vault / "claims")
        if symlink_dir(outside_claims_dir, symlink_claims_vault / "claims"):
            result = subprocess.run(
                [sys.executable, "scripts/wiki_claims.py", str(symlink_claims_vault)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if result.returncode == 0:
                print(result.stdout)
                fail("claim extraction accepted a symlinked claims/ directory outside the vault")
            if "under claims/" not in result.stdout:
                print(result.stdout)
                fail("claim symlink boundary failure did not explain the claims/ constraint")
            if (outside_claims_dir / "claims.jsonl").exists() or (outside_claims_dir / "claim-report.md").exists():
                fail("claim extraction wrote outputs through a symlinked claims/ directory")

        symlink_revision_vault = Path(tmp) / "symlink-revision-vault"
        shutil.copytree(vault, symlink_revision_vault)
        outside_concepts_dir = Path(tmp) / "outside-concepts-dir"
        shutil.move(str(symlink_revision_vault / "concepts"), outside_concepts_dir)
        outside_concept = outside_concepts_dir / "attention-mechanisms.md"
        original_concept = outside_concept.read_text(encoding="utf-8")
        if symlink_dir(outside_concepts_dir, symlink_revision_vault / "concepts"):
            result = subprocess.run(
                [sys.executable, "scripts/wiki_concept_revision.py", str(symlink_revision_vault), "--apply"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if result.returncode == 0:
                print(result.stdout)
                fail("concept revision accepted a symlinked concepts/ directory outside the vault")
            if "under concepts/" not in result.stdout or "Traceback" in result.stdout:
                print(result.stdout)
                fail("concept revision symlink failure did not cleanly explain the concepts/ constraint")
            if outside_concept.read_text(encoding="utf-8") != original_concept:
                fail("concept revision modified a page through a symlinked concepts/ directory")


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
            (vault / "raw" / f"{name}.pdf").write_bytes(b"%PDF-1.4 fake")
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


def main() -> None:
    check_skills()
    check_docs()
    check_minimal_vault()
    check_claim_extraction()
    check_setup_script()
    check_pdf_to_markdown_help()
    run_runtime_checks()
    check_pdf_to_markdown_http_errors()
    check_safety_boundaries()
    check_pdf_corpus_report_short_outputs()
    check_pdf_corpus_report_parser_warnings()
    check_source_discovery_arxiv_filename()
    check_corpus_ingest_resume_continues()
    print("quality checks passed")


if __name__ == "__main__":
    main()
