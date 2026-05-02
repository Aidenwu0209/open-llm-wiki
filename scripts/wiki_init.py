#!/usr/bin/env python3
"""Initialize an open-llm-wiki vault and optional Claude Code skills."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from wiki_common import write_text


DIRS = ["raw", "sources", "concepts", "drafts", "qa-reports", "templates", "_state", "log-archive"]
RUNTIME_SCRIPTS = [
    "pdf_to_markdown.py",
    "wiki_common.py",
    "wiki_lint.py",
    "wiki_search.py",
    "wiki_writeback.py",
]


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
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    vault = args.vault.resolve()
    for item in DIRS:
        (vault / item).mkdir(parents=True, exist_ok=True)

    copy_file(repo / "SCHEMA.md", vault / "SCHEMA.md", args.force)
    copy_tree_contents(repo / "templates", vault / "templates", args.force)

    write_file(vault / "_state" / "id-counter.md", "# ID Counter\nnext: 1\n", args.force)
    write_file(
        vault / "index.md",
        "# LLM Wiki Index\n\n"
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
