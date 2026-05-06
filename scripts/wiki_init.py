#!/usr/bin/env python3
"""Initialize an open-llm-wiki vault and optional Claude Code skills."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from wiki_common import write_text


DIRS = ["raw", "sources", "concepts", "drafts", "qa-reports", "claims", "templates", "_state", "log-archive"]
OBSIDIAN_GRAPH_SEARCH = "-path:raw -path:templates -path:qa-reports -path:_state -path:claims -path:drafts -path:log-archive"
OBSIDIAN_GRAPH_SETTINGS = {
    "collapse-filter": False,
    "search": OBSIDIAN_GRAPH_SEARCH,
    "showTags": False,
    "showAttachments": False,
    "hideUnresolved": True,
    "showOrphans": True,
    "collapse-color-groups": True,
    "colorGroups": [],
    "collapse-display": True,
    "showArrow": False,
    "textFadeMultiplier": 0,
    "nodeSizeMultiplier": 1,
    "lineSizeMultiplier": 1,
    "collapse-forces": True,
    "centerStrength": 0.518713248970312,
    "repelStrength": 10,
    "linkStrength": 1,
    "linkDistance": 250,
    "scale": 1,
    "close": False,
}
RUNTIME_SCRIPTS = [
    "pdf_corpus_report.py",
    "pdf_corpus_to_markdown.py",
    "pdf_to_markdown.py",
    "wiki_claims.py",
    "wiki_concept_revision.py",
    "wiki_contradictions.py",
    "wiki_discover_sources.py",
    "wiki_grow.py",
    "wiki_ingest_corpus.py",
    "wiki_normalize_metrics.py",
    "wiki_queue.py",
    "wiki_common.py",
    "wiki_lint.py",
    "wiki_obsidian_setup.py",
    "wiki_science_review.py",
    "wiki_semantic_qa.py",
    "wiki_search.py",
    "wiki_writeback.py",
]
RUNTIME_RESOURCE_DIRS = ["obsidian"]


def copy_file(src: Path, dst: Path, force: bool) -> None:
    if dst.exists() and not force:
        print(f"keeping existing file: {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_file(dst: Path, text: str, force: bool) -> None:
    if dst.exists() and not force:
        print(f"keeping existing file: {dst}")
        return
    write_text(dst, text)


def copy_tree_contents(src: Path, dst: Path, force: bool) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists() and force:
                shutil.rmtree(target)
            if not target.exists():
                shutil.copytree(item, target)
        else:
            copy_file(item, target, force)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize an open-llm-wiki vault.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skill-dir", type=Path)
    parser.add_argument("--install-skills", action="store_true")
    parser.add_argument(
        "--obsidian",
        action="store_true",
        help="Install the optional Obsidian experience layer after initializing the vault.",
    )
    parser.add_argument(
        "--obsidian-profile",
        choices=["minimal", "research", "full"],
        default="minimal",
        help="Obsidian plugin/theme profile to install when --obsidian is set.",
    )
    parser.add_argument(
        "--obsidian-skip-downloads",
        action="store_true",
        help="Configure Obsidian without downloading community plugins or themes.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    vault = args.vault.resolve()
    for item in DIRS:
        (vault / item).mkdir(parents=True, exist_ok=True)

    copy_file(repo / "SCHEMA.md", vault / "SCHEMA.md", args.force)
    copy_tree_contents(repo / "templates", vault / "templates", args.force)
    write_file(vault / ".obsidian" / "graph.json", json.dumps(OBSIDIAN_GRAPH_SETTINGS, indent=2) + "\n", args.force)

    write_file(vault / "_state" / "id-counter.md", "# ID Counter\nnext: 1\n", args.force)
    write_file(vault / "_state" / "growth-queue.jsonl", "", args.force)
    write_file(vault / "_state" / "science-review-queue.jsonl", "", args.force)
    write_file(vault / "_state" / "source-registry.jsonl", "", args.force)
    write_file(vault / "claims" / "claims.jsonl", "", args.force)
    write_file(
        vault / "index.md",
        "# LLM Wiki Index\n\n"
        "## Pipeline Status\n"
        "This index is populated as the pipeline creates source and concept pages.\n\n"
        "| Stage | Current State | Next Action |\n"
        "| --- | --- | --- |\n"
        "| Raw evidence | Add PDFs or parsed Markdown under `raw/` | Convert PDFs or inspect `raw/*_markdown/combined.md` |\n"
        "| Sources | No source pages have been generated yet | Run corpus ingest to create `sources/LLM-NNNN.md` |\n"
        "| Claims and review | No claims or review queue have been generated yet | Run claim extraction and review gates after sources exist |\n\n"
        "## Sources\n| ID | Title | Tags |\n| --- | --- | --- |\n\n"
        "## Concepts\n| Concept | Key Question | Sources |\n| --- | --- | --- |\n",
        args.force,
    )
    write_file(vault / "log.md", "# Wiki Log\n", args.force)
    write_file(
        vault / "README.md",
        "# My LLM Wiki\n\n"
        "A personal or team research wiki powered by open-llm-wiki.\n\n"
        "Start by dropping a source into `raw/` and asking Claude Code to ingest it.\n",
        args.force,
    )

    runtime_dir = vault / ".open-llm-wiki" / "scripts"
    for script in RUNTIME_SCRIPTS:
        copy_file(repo / "scripts" / script, runtime_dir / script, args.force)
    for resource_dir in RUNTIME_RESOURCE_DIRS:
        copy_tree_contents(repo / resource_dir, vault / ".open-llm-wiki" / resource_dir, args.force)

    if args.obsidian:
        from wiki_obsidian_setup import setup_obsidian

        actions = setup_obsidian(
            vault,
            repo / "obsidian",
            profile=args.obsidian_profile,
            skip_downloads=args.obsidian_skip_downloads,
            force=args.force,
        )
        print(f"obsidian profile {args.obsidian_profile} configured with {len(actions)} actions")

    if args.install_skills:
        if not args.skill_dir:
            raise SystemExit("--install-skills requires --skill-dir")
        copy_tree_contents(repo / "skills", args.skill_dir, args.force)
        print(f"skills installed to {args.skill_dir}")

    print(f"vault initialized at {vault}")
    print(f"runtime scripts copied to {runtime_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
