#!/usr/bin/env python3
"""Generate an Obsidian-friendly status dashboard for an open-llm-wiki vault."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, json_dump, parse_frontmatter, read_text, rel, write_text

try:
    from wiki_lint import lint as wiki_lint
except ImportError:  # pragma: no cover - only used when copied scripts are incomplete.
    wiki_lint = None


PROMPT_TEMPLATES = [
    "ingest-one-source",
    "query-wiki",
    "propose-writeback",
    "run-lint",
    "science-review",
    "concept-revision",
    "graph-export",
]
PROTECTED_OUTPUT_DIRS = {"raw", "sources", "drafts", "concepts", "claims", "qa-reports", "_state"}
STALE_WORDS = ("latest", "current", "state of the art", "sota", "now")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def count_children(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.iterdir() if not item.name.startswith("."))


def markdown_files(path: Path, pattern: str = "*.md") -> list[Path]:
    if not path.exists():
        return []
    return sorted(path.glob(pattern))


def parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def page_title(path: Path) -> str:
    try:
        frontmatter, body = parse_frontmatter(path)
    except OSError:
        return path.stem
    if frontmatter.get("title"):
        return frontmatter["title"]
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def recent_pages(vault: Path, folder: str, limit: int) -> list[dict[str, str]]:
    paths = markdown_files(vault / folder)
    paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    pages = []
    for path in paths[:limit]:
        pages.append({"path": rel(path, vault), "title": page_title(path)})
    return pages


def recent_reports(vault: Path, limit: int) -> list[dict[str, str]]:
    paths = markdown_files(vault / "qa-reports")
    paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    reports = []
    for path in paths[:limit]:
        reports.append({"path": rel(path, vault), "title": path.stem})
    return reports


def stale_concepts(vault: Path) -> list[dict[str, str]]:
    today = date.today()
    stale: list[dict[str, str]] = []
    for path in markdown_files(vault / "concepts"):
        frontmatter, body = parse_frontmatter(path)
        updated = parse_date(frontmatter.get("updated", ""))
        if not updated or (today - updated).days <= 90:
            continue
        if any(word in body.lower() for word in STALE_WORDS):
            stale.append({"path": rel(path, vault), "title": page_title(path)})
    return stale


def lint_summary(vault: Path) -> dict[str, Any]:
    if wiki_lint is None:
        return {"available": False, "total": 0, "priorities": {}}
    findings = wiki_lint(vault, obsidian=(vault / ".obsidian").exists())
    priorities = Counter(item.priority for item in findings)
    return {
        "available": True,
        "total": len(findings),
        "priorities": dict(sorted(priorities.items())),
    }


def build_status(vault: Path, limit: int = 8) -> dict[str, Any]:
    vault = vault.resolve()
    claims = load_jsonl(vault / "claims" / "claims.jsonl")
    science_queue = load_jsonl(vault / "_state" / "science-review-queue.jsonl")
    growth_queue = load_jsonl(vault / "_state" / "growth-queue.jsonl")
    growth_status = Counter(str(row.get("status", "unknown")) for row in growth_queue)
    growth_actions = Counter(str(row.get("action", "unknown")) for row in growth_queue)
    contradiction_reports = markdown_files(vault / "qa-reports", "*contradiction*.md")

    prompt_templates = []
    for template in PROMPT_TEMPLATES:
        path = vault / "templates" / "agent-prompts" / f"{template}.md"
        prompt_templates.append(
            {
                "id": template,
                "path": rel(path, vault) if path.exists() else f"templates/agent-prompts/{template}.md",
                "exists": path.exists(),
            }
        )

    return {
        "vault": str(vault),
        "counts": {
            "raw_inbox": count_children(vault / "raw" / "inbox"),
            "draft_sources": len(markdown_files(vault / "drafts")),
            "stable_sources": len(markdown_files(vault / "sources", "LLM-*.md")),
            "claims": len(claims),
            "claims_needing_review": sum(1 for row in claims if bool(row.get("needs_review"))),
            "science_review_queue": len(science_queue),
            "qa_reports": len(markdown_files(vault / "qa-reports")),
            "contradiction_reports": len(contradiction_reports),
            "concepts": len(markdown_files(vault / "concepts")),
            "growth_queue": len(growth_queue),
            "growth_queue_pending": growth_status.get("pending", 0),
            "stale_concepts": len(stale_concepts(vault)),
        },
        "growth_queue": {
            "by_status": dict(sorted(growth_status.items())),
            "by_action": dict(sorted(growth_actions.items())),
        },
        "recent_sources": recent_pages(vault, "sources", limit),
        "recent_drafts": recent_pages(vault, "drafts", limit),
        "recent_concepts": recent_pages(vault, "concepts", limit),
        "recent_reports": recent_reports(vault, limit),
        "prompt_templates": prompt_templates,
        "lint": lint_summary(vault),
    }


def plural(value: int, singular: str, plural_value: str | None = None) -> str:
    return singular if value == 1 else (plural_value or singular + "s")


def link(relpath: str, label: str | None = None) -> str:
    target = relpath.removesuffix(".md")
    return f"[[{target}|{label or Path(relpath).stem}]]"


def list_links(items: list[dict[str, str]], empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {link(item['path'], item['title'])}" for item in items)


def render_status(status: dict[str, Any]) -> str:
    counts = status["counts"]
    lint = status["lint"]
    if lint["available"]:
        priority_counts = lint["priorities"]
        lint_result = (
            f"{lint['total']} findings "
            f"(P0: {priority_counts.get('P0', 0)}, P1: {priority_counts.get('P1', 0)}, "
            f"P2: {priority_counts.get('P2', 0)}, P3: {priority_counts.get('P3', 0)})"
        )
    else:
        lint_result = "not available from copied runtime scripts"

    template_rows = []
    for template in status["prompt_templates"]:
        state = "available" if template["exists"] else "missing"
        template_rows.append(f"| `{template['id']}` | {link(template['path'], template['id'])} | {state} |")

    growth_status = ", ".join(f"{key}: {value}" for key, value in status["growth_queue"]["by_status"].items()) or "none"
    growth_actions = ", ".join(f"{key}: {value}" for key, value in status["growth_queue"]["by_action"].items()) or "none"

    return (
        "# LLM Wiki Dashboard\n\n"
        "> Generated by `wiki_status.py`. Re-run it after ingest, QA, review, grow, or writeback work.\n\n"
        "## Pipeline Status\n\n"
        "| Area | Current State | Next Action |\n"
        "| --- | ---: | --- |\n"
        f"| Raw inbox | {counts['raw_inbox']} {plural(counts['raw_inbox'], 'item')} | Ingest or move accepted evidence into `raw/` |\n"
        f"| Draft source pages | {counts['draft_sources']} | Run QA before promoting drafts |\n"
        f"| Stable source pages | {counts['stable_sources']} | Use as citable evidence in concepts |\n"
        f"| Claims | {counts['claims']} total / {counts['claims_needing_review']} needing review | Run science review before treating review-required claims as trusted |\n"
        f"| Science review queue | {counts['science_review_queue']} {plural(counts['science_review_queue'], 'item')} | Review manually; do not auto-approve |\n"
        f"| QA reports | {counts['qa_reports']} | Check the latest report before writeback |\n"
        f"| Contradiction reports | {counts['contradiction_reports']} | Resolve candidates before synthesis |\n"
        f"| Concepts | {counts['concepts']} | Keep every material statement cited |\n"
        f"| Growth queue | {counts['growth_queue']} total / {counts['growth_queue_pending']} pending | Run due tasks only when expected |\n"
        f"| Stale concepts | {counts['stale_concepts']} | Refresh pages with time-sensitive wording |\n"
        f"| Last lint result | {lint_result} | Run `wiki_lint.py --obsidian --fail-on p1` before PRs or writeback |\n\n"
        "## Review Queue\n\n"
        f"- Claims needing review: **{counts['claims_needing_review']}**\n"
        f"- Science review queue items: **{counts['science_review_queue']}**\n"
        f"- Growth queue by status: {growth_status}\n"
        f"- Growth queue by action: {growth_actions}\n\n"
        "## Recent Sources\n\n"
        f"{list_links(status['recent_sources'], 'No stable source pages yet.')}\n\n"
        "## Recent Drafts\n\n"
        f"{list_links(status['recent_drafts'], 'No draft source pages yet.')}\n\n"
        "## Recent Concepts\n\n"
        f"{list_links(status['recent_concepts'], 'No concept pages yet.')}\n\n"
        "## Recent Reports\n\n"
        f"{list_links(status['recent_reports'], 'No QA or review reports yet.')}\n\n"
        "## Agent Prompt Templates\n\n"
        "| Template | Link | Status |\n"
        "| --- | --- | --- |\n"
        + "\n".join(template_rows)
        + "\n\n"
        "## Common Runtime Commands\n\n"
        "```bash\n"
        "python .open-llm-wiki/scripts/wiki_status.py .\n"
        "python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force\n"
        "python .open-llm-wiki/scripts/wiki_ingest_corpus.py .\n"
        "python .open-llm-wiki/scripts/wiki_claims.py .\n"
        "python .open-llm-wiki/scripts/wiki_science_review.py . --write-report --queue\n"
        "python .open-llm-wiki/scripts/wiki_semantic_qa.py . --write-report --fail-on p1\n"
        "python .open-llm-wiki/scripts/wiki_contradictions.py . --write-report\n"
        "python .open-llm-wiki/scripts/wiki_queue.py . list\n"
        "python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1\n"
        "```\n\n"
        "## Safe Write Flow\n\n"
        "1. Query the wiki and cite source, claim, or concept evidence.\n"
        "2. Separate evidence, inference, hypothesis, and forecast.\n"
        "3. Generate a writeback proposal with `wiki_writeback.py`; do not write silently.\n"
        "4. Show the target page, proposed content, evidence links, risks, and required human checks.\n"
        "5. Apply only after explicit approval, then run lint and log the write.\n\n"
        "## Optional Dataview Snippets\n\n"
        "```dataview\n"
        "TABLE title, updated, status\n"
        "FROM \"sources\" OR \"drafts\"\n"
        "SORT updated DESC\n"
        "```\n\n"
        "```dataview\n"
        "TABLE title, updated\n"
        "FROM \"concepts\"\n"
        "SORT updated DESC\n"
        "```\n"
    )


def resolve_dashboard_output(vault: Path, output: Path) -> Path:
    target = output if output.is_absolute() else vault / output
    target = ensure_within(target, vault, "dashboard output must stay inside the vault")
    try:
        parts = target.relative_to(vault).parts
    except ValueError as exc:
        raise SystemExit("dashboard output must stay inside the vault") from exc
    if not parts:
        raise SystemExit("dashboard output must be a Markdown file inside the vault")
    if target.suffix.lower() != ".md":
        raise SystemExit("dashboard output must be a Markdown file")
    if parts[0] in PROTECTED_OUTPUT_DIRS:
        raise SystemExit("dashboard output must not rewrite raw, source, draft, concept, claim, report, or state files")
    return target


def write_dashboard(vault: Path, output: Path, text: str, force: bool) -> Path:
    target = resolve_dashboard_output(vault, output)
    if target.exists() and not force:
        raise SystemExit(f"refusing to overwrite existing dashboard without --force: {rel(target, vault)}")
    write_text(target, text)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a vault and optionally write an Obsidian dashboard.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--limit", type=int, default=8, help="Maximum recent sources, concepts, drafts, and reports to list.")
    parser.add_argument("--write-dashboard", action="store_true", help="Write the rendered Markdown into the vault.")
    parser.add_argument("--output", type=Path, default=Path("_dashboard.md"), help="Dashboard path relative to the vault.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing dashboard/status page.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    status = build_status(vault, limit=args.limit)
    if args.format == "json":
        rendered = json_dump(status)
    else:
        rendered = render_status(status)

    if args.write_dashboard:
        if args.format != "markdown":
            raise SystemExit("--write-dashboard requires --format markdown")
        target = write_dashboard(vault, args.output, rendered, args.force)
        print(f"dashboard written to {target}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
