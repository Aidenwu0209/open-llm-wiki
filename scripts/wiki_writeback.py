#!/usr/bin/env python3
"""Create or apply reviewable query-writeback patches."""

from __future__ import annotations

import argparse
import difflib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, read_text, rel, write_text


@dataclass(frozen=True)
class SemanticQaStatus:
    report: Path | None
    p0: int = 0
    p1: int = 0
    verdict: str = ""

    @property
    def blocks_writeback(self) -> bool:
        return self.p0 > 0 or self.p1 > 0 or self.verdict.upper() == "FAIL"


def append_section(original: str, query: str, body: str, timestamp: str) -> str:
    section = (
        "\n\n## Query-Derived Note: "
        + timestamp[:10]
        + "\n\n"
        + f"- query: {query}\n"
        + "- query-derived: "
        + timestamp[:10]
        + "\n\n"
        + body.strip()
        + "\n"
    )
    return original.rstrip() + section


def make_diff(path: Path, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path.as_posix()}",
            tofile=f"b/{path.as_posix()}",
        )
    )


def proposal_text(relative: str, query: str, diff: str, log_entry: str, warning: str, timestamp: str) -> str:
    sections = [
        "# Query Writeback Proposal",
        "",
        f"- generated_at: {timestamp}",
        f"- target: {relative}",
        f"- query: {query}",
        "- writeback_applied: false",
        "- approval_required: true",
    ]
    if warning:
        sections.extend(["", "## Semantic QA Warning", "", warning])
    sections.extend(
        [
            "",
            "## Proposed Diff",
            "",
            "```diff",
            diff.rstrip(),
            "```",
            "",
            "## Proposed Log Entry",
            "",
            "```text",
            log_entry.rstrip(),
            "```",
            "",
        ]
    )
    return "\n".join(sections)


def resolve_proposal_output(vault: Path, output: Path) -> Path:
    path = output if output.is_absolute() else vault / output
    resolved = ensure_within(path, vault, "proposal output must stay inside the vault")
    ensure_within(resolved, vault / "reviews" / "query-writeback", "proposal output must be under reviews/query-writeback/")
    return resolved


def latest_semantic_qa_status(vault: Path) -> SemanticQaStatus:
    reports = sorted((vault / "qa-reports").glob("semantic-qa-*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return SemanticQaStatus(report=None)
    report = reports[0]
    text = read_text(report)

    def count(name: str) -> int:
        match = re.search(rf"^- {name}: (\d+)\s*$", text, re.MULTILINE)
        return int(match.group(1)) if match else 0

    verdict_match = re.search(r"^- verdict: ([A-Za-z_]+)\s*$", text, re.MULTILINE)
    verdict = verdict_match.group(1) if verdict_match else ""
    return SemanticQaStatus(report=report, p0=count("p0"), p1=count("p1"), verdict=verdict)


def semantic_qa_warning(status: SemanticQaStatus, vault: Path) -> str:
    report = rel(status.report, vault) if status.report else "N/A"
    return (
        "WARNING: latest semantic QA report is not clean "
        f"({report}; p0={status.p0}, p1={status.p1}, verdict={status.verdict or 'unknown'}). "
        "Resolve semantic QA before applying writeback, or pass --allow-failing-qa to explicitly override."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose or apply a query writeback.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--target", required=True, help="Target concept page relative to the vault.")
    parser.add_argument("--query", required=True, help="Original user query.")
    parser.add_argument("--body", help="Markdown body to append.")
    parser.add_argument("--body-file", type=Path, help="File containing markdown body to append.")
    parser.add_argument(
        "--proposal-output",
        type=Path,
        help="Optional markdown proposal artifact path under reviews/query-writeback/. Default prints the diff only.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the writeback. Default prints a diff only.")
    parser.add_argument(
        "--allow-failing-qa",
        action="store_true",
        help="Allow --apply even when the latest semantic QA report has P0/P1 failures.",
    )
    args = parser.parse_args()

    vault = args.vault.resolve()
    target = ensure_within(vault / args.target, vault, "target must stay inside the vault")
    ensure_within(target, vault / "concepts", "writeback target must be under concepts/")
    if not target.exists():
        raise SystemExit(f"target does not exist: {target}")

    if args.body_file:
        body = read_text(args.body_file)
    elif args.body:
        body = args.body
    else:
        raise SystemExit("provide --body or --body-file")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    before = read_text(target)
    after = append_section(before, args.query, body, timestamp)
    relative = rel(target, vault)
    diff = make_diff(Path(relative), before, after)
    semantic_status = latest_semantic_qa_status(vault)
    warning = semantic_qa_warning(semantic_status, vault) if semantic_status.blocks_writeback else ""
    log_entry = f"[{timestamp}] query-writeback | {relative} | agent | query: {args.query!r}"

    if args.proposal_output:
        proposal_path = resolve_proposal_output(vault, args.proposal_output)
        write_text(proposal_path, proposal_text(relative, args.query, diff, log_entry, warning, timestamp))
        print(f"wrote writeback proposal to {rel(proposal_path, vault)}")

    if not args.apply:
        if warning:
            print(warning)
            print()
        print(diff)
        print("\n# Proposed log entry")
        print(log_entry)
        return 0

    if warning and not args.allow_failing_qa:
        raise SystemExit(f"{warning}\nwriteback not applied")
    if warning:
        print(warning)

    write_text(target, after)
    log_path = vault / "log.md"
    log_before = read_text(log_path) if log_path.exists() else "# Wiki Log\n"
    write_text(log_path, log_before.rstrip() + "\n" + log_entry + "\n")
    print(f"applied writeback to {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
