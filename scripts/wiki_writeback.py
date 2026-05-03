#!/usr/bin/env python3
"""Create or apply reviewable query-writeback patches."""

from __future__ import annotations

import argparse
import difflib
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, read_text, rel, write_text


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose or apply a query writeback.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--target", required=True, help="Target concept page relative to the vault.")
    parser.add_argument("--query", required=True, help="Original user query.")
    parser.add_argument("--body", help="Markdown body to append.")
    parser.add_argument("--body-file", type=Path, help="File containing markdown body to append.")
    parser.add_argument("--apply", action="store_true", help="Apply the writeback. Default prints a diff only.")
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

    if not args.apply:
        print(diff)
        print("\n# Proposed log entry")
        print(f"[{timestamp}] query-writeback | {relative} | agent | query: {args.query!r}")
        return 0

    write_text(target, after)
    log_path = vault / "log.md"
    log_before = read_text(log_path) if log_path.exists() else "# Wiki Log\n"
    log_entry = f"[{timestamp}] query-writeback | {relative} | agent | query: {args.query!r}\n"
    write_text(log_path, log_before.rstrip() + "\n" + log_entry)
    print(f"applied writeback to {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
