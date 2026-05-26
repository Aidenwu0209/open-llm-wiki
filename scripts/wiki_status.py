#!/usr/bin/env python3
"""Generate an Obsidian-friendly status dashboard for an open-llm-wiki vault."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from wiki_common import ensure_within, json_dump, parse_frontmatter, read_text, rel, write_text
from wiki_raw_support import is_auxiliary_raw_source_path

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
IGNORED_RAW_DIRS = frozenset({"__MACOSX"})

ACTION_KINDS = frozenset({
    "parse_required", "artifact_stale", "ingest_failed", "published_duplicate",
    "qa_failed", "claims_need_review", "contradiction_review", "unsupported_claim",
    "concept_stale", "source_updated", "impact_review", "runtime_missing",
    "schema_invalid", "lint_error", "obsidian_profile_missing",
})
ACTION_STATUSES = frozenset({"open", "resolved", "ignored"})


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    write_text(path, text)


def state_output_path(vault: Path, filename: str, message: str) -> Path:
    state_dir = ensure_within(vault / "_state", vault, "_state must stay inside the vault")
    return ensure_within(state_dir / filename, state_dir, message)


def count_children(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.iterdir() if not item.name.startswith("."))


def is_raw_evidence_file(raw_dir: Path, path: Path) -> bool:
    if not path.is_file() or path.name.startswith(".") or is_auxiliary_raw_source_path(path):
        return False
    try:
        parts = path.relative_to(raw_dir).parts
    except ValueError:
        return False
    parent_parts = parts[:-1]
    return not any(part.startswith(".") or part.endswith("_markdown") or part in IGNORED_RAW_DIRS for part in parent_parts)


def raw_evidence_files(vault: Path) -> list[Path]:
    raw_dir = vault / "raw"
    if not raw_dir.exists():
        return []
    return sorted(path for path in raw_dir.rglob("*") if is_raw_evidence_file(raw_dir, path))


def pending_raw_evidence_files(vault: Path) -> list[Path]:
    items = raw_evidence_files(vault)
    registry_rows = load_jsonl(vault / "_state" / "source-registry.jsonl")
    if not registry_rows:
        return items
    pending_paths = {
        str(row.get("raw_path") or row.get("path") or "")
        for row in registry_rows
        if str(row.get("status", "")) not in {"published", "archived"}
    }
    if not pending_paths:
        return []
    return [path for path in items if rel(path, vault) in pending_paths]


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
        return {"available": False, "total": 0, "findings": [], "priorities": {}}
    findings = wiki_lint(vault, obsidian=(vault / ".obsidian").exists())
    priorities = Counter(item.priority for item in findings)
    return {
        "available": True,
        "total": len(findings),
        "findings": [item.as_dict() for item in findings],
        "priorities": dict(sorted(priorities.items())),
    }


def action_fingerprint(action: dict[str, Any]) -> str:
    parts = f"{action.get('kind')}|{action.get('primary_object_type', '')}|{action.get('primary_object_id', '')}|{action.get('reason', '')}"
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def make_action(
    kind: str,
    severity: str,
    title: str,
    body: str,
    reason: str,
    primary_object_type: str,
    primary_object_id: str,
    affected_objects: list[str] | None = None,
    recommended_action: str = "",
    command: str = "",
    links: list[str] | None = None,
) -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    action = {
        "kind": kind,
        "severity": severity,
        "title": title,
        "body": body,
        "reason": reason,
        "status": "open",
        "primary_object_type": primary_object_type,
        "primary_object_id": primary_object_id,
        "affected_objects": affected_objects or [],
        "recommended_action": recommended_action,
        "command": command,
        "links": links or [],
        "created_at": now,
        "updated_at": now,
    }
    action["action_id"] = f"act-{action_fingerprint(action)}"
    return action


def generate_actions(vault: Path) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    vault = vault.resolve()
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Raw inbox items
    inbox = vault / "raw" / "inbox"
    if inbox.exists():
        inbox_items = [p for p in inbox.iterdir() if not p.name.startswith(".")]
        if inbox_items:
            actions.append(make_action(
                kind="parse_required",
                severity="medium",
                title=f"Parse {len(inbox_items)} inbox item(s)",
                body=f"{len(inbox_items)} unprocessed file(s) in raw/inbox waiting to be parsed and ingested.",
                reason="Unprocessed raw material blocks the pipeline.",
                primary_object_type="directory",
                primary_object_id="raw/inbox",
                affected_objects=[p.name for p in inbox_items[:8]],
                recommended_action="Run the ingest pipeline to parse and draft source pages.",
                command="python .open-llm-wiki/scripts/wiki_ingest_corpus.py .",
            ))

    pending_raw_items = [
        path for path in pending_raw_evidence_files(vault)
        if not rel(path, vault).startswith("raw/inbox/")
    ]
    if pending_raw_items:
        actions.append(make_action(
            kind="parse_required",
            severity="medium",
            title=f"Process {len(pending_raw_items)} raw evidence item(s)",
            body=(
                f"{len(pending_raw_items)} raw evidence file(s) outside raw/inbox are registered "
                "or discoverable but not published as source pages yet."
            ),
            reason="Raw evidence should be parsed and ingested before users treat the wiki as complete.",
            primary_object_type="directory",
            primary_object_id="raw/",
            affected_objects=[rel(p, vault) for p in pending_raw_items],
            recommended_action="Convert raw evidence to parsed Markdown/source pages, then run corpus ingest.",
        ))

    # Draft sources needing QA
    drafts = markdown_files(vault / "drafts")
    if drafts:
        actions.append(make_action(
            kind="qa_failed",
            severity="high",
            title=f"Run QA on {len(drafts)} draft(s)",
            body=f"{len(drafts)} draft source page(s) need independent QA before publishing.",
            reason="Drafts cannot be promoted without passing QA.",
            primary_object_type="directory",
            primary_object_id="drafts/",
            affected_objects=[rel(p, vault) for p in drafts[:8]],
            recommended_action="Run semantic QA on each draft, then promote passing drafts.",
            command="python .open-llm-wiki/scripts/wiki_semantic_qa.py . --write-report --fail-on p1",
        ))

    # Claims needing review
    claims = load_jsonl(vault / "claims" / "claims.jsonl")
    needs_review = [c for c in claims if bool(c.get("needs_review"))]
    if needs_review:
        actions.append(make_action(
            kind="claims_need_review",
            severity="high",
            title=f"Review {len(needs_review)} claim(s)",
            body=f"{len(needs_review)} claim(s) flagged for scientific review (missing protocol, baseline, or normalization warnings).",
            reason="Review-required claims should not be used in concept synthesis.",
            primary_object_type="claims",
            primary_object_id="claims/claims.jsonl",
            affected_objects=[str(c.get("claim_id", "")) for c in needs_review[:8]],
            recommended_action="Run science review and approve or flag claims.",
            command="python .open-llm-wiki/scripts/wiki_science_review.py . --queue --write-report",
        ))

    # Contradiction candidates
    contradiction_reports = markdown_files(vault / "qa-reports", "*contradiction*.md")
    if contradiction_reports:
        actions.append(make_action(
            kind="contradiction_review",
            severity="high",
            title=f"Review {len(contradiction_reports)} contradiction report(s)",
            body=f"{len(contradiction_reports)} contradiction report(s) exist. Resolve candidates before synthesis.",
            reason="Unresolved contradictions may produce incorrect concept synthesis.",
            primary_object_type="reports",
            primary_object_id="qa-reports/",
            affected_objects=[rel(p, vault) for p in contradiction_reports[:8]],
            recommended_action="Review contradiction reports and confirm or dismiss candidates.",
            command="python .open-llm-wiki/scripts/wiki_contradictions.py . --write-report",
        ))

    # Stale concepts
    stale = stale_concepts(vault)
    if stale:
        actions.append(make_action(
            kind="concept_stale",
            severity="medium",
            title=f"Refresh {len(stale)} stale concept(s)",
            body=f"{len(stale)} concept page(s) have time-sensitive wording older than 90 days.",
            reason="Stale time-sensitive wording may mislead readers.",
            primary_object_type="concepts",
            primary_object_id="concepts/",
            affected_objects=[s["path"] for s in stale[:8]],
            recommended_action="Review and update stale concept pages.",
            command="python .open-llm-wiki/scripts/wiki_concept_revision.py . --apply",
        ))

    # Unsupported claims in concept pages
    verdict_excluded = {"contradicted", "retracted", "stale"}
    unsupported = [c for c in claims if str(c.get("verdict", "")) in verdict_excluded]
    if unsupported:
        actions.append(make_action(
            kind="unsupported_claim",
            severity="high",
            title=f"Handle {len(unsupported)} excluded claim(s)",
            body=f"{len(unsupported)} claim(s) have verdict contradicted/retracted/stale and must not appear in concept synthesis.",
            reason="Excluded claims compromise concept accuracy.",
            primary_object_type="claims",
            primary_object_id="claims/claims.jsonl",
            affected_objects=[str(c.get("claim_id", "")) for c in unsupported[:8]],
            recommended_action="Re-derive affected concept pages after resolving excluded claims.",
            command="python .open-llm-wiki/scripts/wiki_concept_revision.py . --apply",
        ))

    # Source updates triggering concept revision
    today = date.today()
    for path in markdown_files(vault / "sources"):
        frontmatter, _ = parse_frontmatter(path)
        updated = parse_date(frontmatter.get("updated", ""))
        if updated and (today - updated).days <= 7:
            source_id = frontmatter.get("id", path.stem)
            actions.append(make_action(
                kind="source_updated",
                severity="medium",
                title=f"Source {source_id} updated recently",
                body=f"Source [[{source_id}]] was updated on {updated.isoformat()}. Related concepts may need revision.",
                reason="Updated sources may invalidate concept synthesis.",
                primary_object_type="source",
                primary_object_id=source_id,
                recommended_action="Re-extract claims and revise related concept pages.",
                command=f"python .open-llm-wiki/scripts/wiki_claims.py . && python .open-llm-wiki/scripts/wiki_concept_revision.py . --apply",
                links=[f"[[{source_id}]]"],
            ))

    # Lint errors -> action items
    lint_info = lint_summary(vault)
    if lint_info["available"]:
        p0_count = lint_info["priorities"].get("P0", 0)
        p1_count = lint_info["priorities"].get("P1", 0)
        if p0_count > 0 or p1_count > 0:
            affected = []
            for f in lint_info["findings"]:
                if f.get("priority") in ("P0", "P1"):
                    affected.append(f"{f.get('path', '')}: {f.get('message', '')}"[:120])
            actions.append(make_action(
                kind="lint_error",
                severity="critical" if p0_count > 0 else "high",
                title=f"Fix {p0_count + p1_count} lint error(s)",
                body=f"Lint found {p0_count} P0 and {p1_count} P1 issues that must be resolved before writeback.",
                reason="Lint errors indicate data integrity problems.",
                primary_object_type="vault",
                primary_object_id=str(vault),
                affected_objects=affected[:8],
                recommended_action="Fix lint errors before proceeding with any writeback or synthesis.",
                command="python .open-llm-wiki/scripts/wiki_lint.py . --fail-on p1",
            ))

    # Runtime missing check
    runtime_dir = vault / ".open-llm-wiki" / "scripts"
    if not runtime_dir.exists():
        actions.append(make_action(
            kind="runtime_missing",
            severity="medium",
            title="Runtime scripts not installed",
            body="The .open-llm-wiki/scripts/ directory is missing. Runtime commands will not work from the vault.",
            reason="Without runtime scripts, vault operations cannot be triggered from Obsidian.",
            primary_object_type="directory",
            primary_object_id=".open-llm-wiki/scripts/",
            recommended_action="Run setup to install runtime scripts.",
            command="python scripts/wiki_init.py .",
        ))

    # Obsidian profile check
    if (vault / ".obsidian").exists() and not (vault / ".obsidian" / "app.json").exists():
        actions.append(make_action(
            kind="obsidian_profile_missing",
            severity="low",
            title="Obsidian app.json missing",
            body="The .obsidian directory exists but app.json is missing. Community plugins may be disabled.",
            reason="Obsidian integration is incomplete.",
            primary_object_type="file",
            primary_object_id=".obsidian/app.json",
            recommended_action="Run Obsidian setup or re-enable community plugins.",
            command="python .open-llm-wiki/scripts/wiki_obsidian_setup.py . --profile minimal --skip-downloads",
        ))

    return actions


def load_action_state(vault: Path) -> dict[str, str]:
    state_path = state_output_path(
        vault,
        "action-state.jsonl",
        "action state must stay inside _state",
    )
    if not state_path.exists():
        return {}
    state: dict[str, str] = {}
    for row in load_jsonl(state_path):
        aid = str(row.get("action_id", ""))
        status = str(row.get("status", ""))
        if aid and status in ACTION_STATUSES:
            state[aid] = status
    return state


def save_action_state(vault: Path, state: dict[str, str]) -> None:
    state_path = state_output_path(
        vault,
        "action-state.jsonl",
        "action state must stay inside _state",
    )
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    rows = []
    for aid, status in sorted(state.items()):
        rows.append({"action_id": aid, "status": status, "updated_at": now})
    write_jsonl(state_path, rows)


def filter_open_actions(actions: list[dict[str, Any]], state: dict[str, str]) -> list[dict[str, Any]]:
    open_actions: list[dict[str, Any]] = []
    for action in actions:
        aid = str(action.get("action_id", ""))
        if state.get(aid) in ("resolved", "ignored"):
            action["status"] = state[aid]
        else:
            action["status"] = "open"
            open_actions.append(action)
    return open_actions


def resolve_action(vault: Path, action_id: str, new_status: str) -> bool:
    state = load_action_state(vault)
    state[action_id] = new_status
    save_action_state(vault, state)
    return True


def save_actions_jsonl(vault: Path, actions: list[dict[str, Any]]) -> None:
    actions_path = state_output_path(
        vault,
        "actions.jsonl",
        "actions output must stay inside _state",
    )
    write_jsonl(actions_path, actions)


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

    actions = generate_actions(vault)
    action_state = load_action_state(vault)
    open_actions = filter_open_actions(actions, action_state)

    return {
        "vault": str(vault),
        "counts": {
            "raw_inbox": count_children(vault / "raw" / "inbox"),
            "raw_evidence": len(raw_evidence_files(vault)),
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
        "actions": actions,
        "open_actions": open_actions,
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


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_LABEL = {"critical": "[critical]", "high": "[high]", "medium": "[medium]", "low": "[low]"}


def render_action_card(action: dict[str, Any]) -> str:
    severity = str(action.get("severity", "medium"))
    label = SEVERITY_LABEL.get(severity, "[medium]")
    title = str(action.get("title", "Untitled action"))
    kind = str(action.get("kind", ""))
    body = str(action.get("body", ""))
    reason = str(action.get("reason", ""))
    command = str(action.get("command", ""))
    recommended = str(action.get("recommended_action", ""))
    affected = action.get("affected_objects", [])
    links_list = action.get("links", [])
    action_id = str(action.get("action_id", ""))

    lines = [
        f"### {label} {title}",
        f"> **Kind:** `{kind}` | **Severity:** {severity} | **ID:** `{action_id}`",
        "",
        body,
        "",
        f"**Reason:** {reason}",
    ]
    if affected:
        affected_str = ", ".join(f"`{a}`" for a in affected[:5])
        if len(affected) > 5:
            affected_str += f", ... (+{len(affected) - 5} more)"
        lines.append(f"**Affected:** {affected_str}")
    if recommended:
        lines.append(f"**Recommended:** {recommended}")
    if command:
        lines.append(f"**Command:** `{command}`")
    if links_list:
        lines.append("**Links:** " + " ".join(str(l) for l in links_list))
    lines.append("")
    return "\n".join(lines)


def render_status(status: dict[str, Any]) -> str:
    counts = status["counts"]
    lint_info = status["lint"]
    if lint_info["available"]:
        priority_counts = lint_info["priorities"]
        lint_result = (
            f"{lint_info['total']} findings "
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

    # Action panel
    open_actions = status.get("open_actions", [])
    open_actions_sorted = sorted(open_actions, key=lambda a: (SEVERITY_ORDER.get(str(a.get("severity", "medium")), 2), str(a.get("kind", ""))))

    action_panel = ""
    if open_actions_sorted:
        action_cards = [render_action_card(a) for a in open_actions_sorted[:12]]
        action_panel = (
            "## Action Panel\n\n"
            "> **What should I do next?** Address these items in priority order.\n\n"
            + "\n---\n\n".join(action_cards)
            + "\n"
        )
    else:
        action_panel = (
            "## Action Panel\n\n"
            "> **No pending actions.** The vault is in good shape.\n\n"
        )

    return (
        "# LLM Wiki Dashboard\n\n"
        "> Generated by `wiki_status.py`. Re-run it after ingest, QA, review, grow, or writeback work.\n\n"
        f"{action_panel}\n"
        "## Pipeline Status\n\n"
        "| Area | Current State | Next Action |\n"
        "| --- | ---: | --- |\n"
        f"| Raw inbox | {counts['raw_inbox']} inbox / {counts['raw_evidence']} raw evidence | Ingest or move accepted evidence into `raw/` |\n"
        f"| Draft source pages | {counts['draft_sources']} | Run QA before promoting drafts |\n"
        f"| Stable source pages | {counts['stable_sources']} | Use as citable evidence in concepts |\n"
        f"| Claims | {counts['claims']} total / {counts['claims_needing_review']} needing review | Run science review before treating review-required claims as trusted |\n"
        f"| Science review queue | {counts['science_review_queue']} {plural(counts['science_review_queue'], 'item')} | Review manually; do not auto-approve |\n"
        f"| QA reports | {counts['qa_reports']} | Check the latest report before writeback |\n"
        f"| Contradiction reports | {counts['contradiction_reports']} | Resolve candidates before synthesis |\n"
        f"| Concepts | {counts['concepts']} | Keep every material statement cited |\n"
        f"| Growth queue | {counts['growth_queue']} total / {counts['growth_queue_pending']} pending | Run due tasks only when expected |\n"
        f"| Stale concepts | {counts['stale_concepts']} | Refresh pages with time-sensitive wording |\n"
        f"| Last lint result | {lint_result} | Run `wiki_lint.py --obsidian --fail-on p1` before PRs or writeback |\n"
        f"| Open actions | **{len(open_actions_sorted)}** | See Action Panel above |\n\n"
        "## Review Queue\n\n"
        f"- Claims needing review: **{counts['claims_needing_review']}**\n"
        f"- Science review queue items: **{counts['science_review_queue']}**\n"
        f"- Growth queue by status: {growth_status}\n"
        f"- Growth queue by action: {growth_actions}\n"
        f"- Open actions: **{len(open_actions_sorted)}** - see Action Panel above\n\n"
        "## Recent Sources\n\n"
        f"{list_links(status['recent_sources'], 'No stable source pages yet.')}\n\n"
        "## Recent Concepts\n\n"
        f"{list_links(status['recent_concepts'], 'No concept pages yet.')}\n\n"
        "## Agent Prompt Templates\n\n"
        "| Template | Link | Status |\n"
        "| --- | --- | --- |\n"
        + "\n".join(template_rows)
        + "\n\n"
        "## Common Runtime Commands\n\n"
        "```bash\n"
        "python .open-llm-wiki/scripts/wiki_status.py .\n"
        "python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force\n"
        "python .open-llm-wiki/scripts/wiki_status.py . --actions\n"
        "python .open-llm-wiki/scripts/wiki_status.py . --resolve-action <action_id>\n"
        "python .open-llm-wiki/scripts/wiki_status.py . --ignore-action <action_id>\n"
        "python .open-llm-wiki/scripts/wiki_ingest_corpus.py .\n"
        "python .open-llm-wiki/scripts/wiki_claims.py .\n"
        "python .open-llm-wiki/scripts/wiki_science_review.py . --write-report --queue\n"
        "python .open-llm-wiki/scripts/wiki_semantic_qa.py . --write-report --fail-on p1\n"
        "python .open-llm-wiki/scripts/wiki_contradictions.py . --write-report\n"
        "python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1\n"
        "```\n\n"
        "## Safe Write Flow\n\n"
        "1. Query the wiki and cite source, claim, or concept evidence.\n"
        "2. Separate evidence, inference, hypothesis, and forecast.\n"
        "3. Generate a writeback proposal with `wiki_writeback.py`; do not write silently.\n"
        "4. Show the target page, proposed content, evidence links, risks, and required human checks.\n"
        "5. Apply only after explicit approval, then run lint and log the write.\n"
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
    parser.add_argument("--actions", action="store_true", help="Generate action items and output as JSON.")
    parser.add_argument("--resolve-action", type=str, help="Mark an action as resolved by action_id.")
    parser.add_argument("--ignore-action", type=str, help="Mark an action as ignored by action_id.")
    args = parser.parse_args()

    vault = args.vault.resolve()

    if args.resolve_action:
        resolve_action(vault, args.resolve_action, "resolved")
        print(f"action {args.resolve_action} resolved")
        return 0

    if args.ignore_action:
        resolve_action(vault, args.ignore_action, "ignored")
        print(f"action {args.ignore_action} ignored")
        return 0

    status = build_status(vault, limit=args.limit)

    # Save actions.jsonl
    save_actions_jsonl(vault, status["actions"])

    if args.actions:
        print(json_dump({"open_actions": status["open_actions"], "total_actions": len(status["actions"])}))
        return 0

    if args.format == "json":
        print(json_dump(status))
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
