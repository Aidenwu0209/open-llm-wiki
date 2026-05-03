#!/usr/bin/env python3
"""Repository quality checks for open-llm-wiki."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
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


def check_setup_script() -> None:
    text = read(ROOT / "setup.sh")
    if ".claude/skills" not in text:
        fail("setup.sh must default to Claude Code skill directory")
    if "OPEN_LLM_WIKI_SKILL_DIR" not in text:
        fail("setup.sh must allow overriding skill directory")
    if not re.search(r"trap\s+cleanup\s+EXIT", text):
        fail("setup.sh must clean temp directory with trap")


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


def main() -> None:
    check_skills()
    check_docs()
    check_minimal_vault()
    check_setup_script()
    run_runtime_checks()
    check_safety_boundaries()
    print("quality checks passed")


if __name__ == "__main__":
    main()
