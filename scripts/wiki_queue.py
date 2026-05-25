#!/usr/bin/env python3
"""Plan and run a durable growth queue for open-llm-wiki vaults."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from wiki_common import ensure_within, json_dump, read_text, write_text


VALID_ACTIONS = {"discover", "grow", "science-review", "concept-revision", "lint"}
CADENCE_DAYS = {"now": 0, "daily": 1, "weekly": 7, "monthly": 30}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_queue(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def save_queue(path: Path, rows: list[dict[str, object]]) -> None:
    write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def task_id(action: str, target: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in f"{action}-{target}")[:80].strip("-")
    return safe or action


def enqueue(rows: list[dict[str, object]], action: str, target: str, due_at: str, reason: str, priority: int) -> bool:
    if action not in VALID_ACTIONS:
        raise SystemExit(f"unknown queue action: {action}")
    ident = task_id(action, target)
    for row in rows:
        if row.get("task_id") == ident and row.get("status") == "running":
            return False
        if row.get("task_id") == ident and row.get("status") == "pending":
            changed = (
                row.get("due_at") != due_at
                or row.get("reason") != reason
                or row.get("priority") != priority
            )
            row.update({"due_at": due_at, "reason": reason, "priority": priority, "updated_at": now_iso()})
            return changed
    rows.append(
        {
            "task_id": ident,
            "action": action,
            "target": target,
            "status": "pending",
            "priority": priority,
            "created_at": now_iso(),
            "due_at": due_at,
            "attempts": 0,
            "max_attempts": 3,
            "reason": reason,
        }
    )
    return True


def due_after(base: datetime, minutes: int) -> str:
    return (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def plan_defaults(vault: Path, rows: list[dict[str, object]], cadence: str) -> int:
    if cadence not in CADENCE_DAYS:
        raise SystemExit(f"unknown queue cadence: {cadence}")
    base = datetime.now() + timedelta(days=CADENCE_DAYS[cadence])
    added = 0
    added += enqueue(rows, "discover", ".", due_after(base, 0), f"{cadence} source discovery and duplicate refresh", 20)
    if list((vault / "sources").glob("LLM-*.md")):
        added += enqueue(rows, "grow", ".", due_after(base, 5), f"{cadence} semantic self-growth loop", 10)
        added += enqueue(rows, "science-review", ".", due_after(base, 10), f"{cadence} second-pass scientific review", 30)
        source_count = len(list((vault / "sources").glob("LLM-*.md")))
        if source_count >= 10:
            added += enqueue(rows, "concept-revision", ".", due_after(base, 15), f"{cadence} concept revision after source growth", 40)
    added += enqueue(rows, "lint", ".", due_after(base, 20), f"{cadence} post-growth validation", 50)
    return added


def run_action(vault: Path, action: str) -> None:
    scripts = Path(__file__).resolve().parent
    if action == "discover":
        command = [sys.executable, str(scripts / "wiki_discover_sources.py"), str(vault)]
    elif action == "grow":
        command = [sys.executable, str(scripts / "wiki_grow.py"), str(vault), "--apply-concept-revision", "--skip-queue"]
    elif action == "science-review":
        command = [sys.executable, str(scripts / "wiki_science_review.py"), str(vault), "--write-report", "--queue"]
    elif action == "concept-revision":
        command = [sys.executable, str(scripts / "wiki_concept_revision.py"), str(vault), "--apply"]
    elif action == "lint":
        command = [sys.executable, str(scripts / "wiki_lint.py"), str(vault), "--fail-on", "p1"]
    else:
        raise SystemExit(f"unknown action: {action}")
    result = subprocess.run(command, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def sorted_queue(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(rows, key=lambda item: (item.get("status"), item.get("priority"), item.get("due_at")))


def queue_json(queue_path: Path, rows: list[dict[str, object]]) -> dict[str, object]:
    due_now = datetime.now().isoformat()
    by_status = Counter(str(row.get("status", "unknown")) for row in rows)
    by_action = Counter(str(row.get("action", "unknown")) for row in rows)
    due_pending = [
        row
        for row in rows
        if row.get("status") == "pending" and str(row.get("due_at", "")) <= due_now
    ]
    pending = [row for row in rows if row.get("status") == "pending"]
    next_pending = sorted(pending, key=lambda item: (item.get("due_at", ""), item.get("priority", 50)))[:5]
    return {
        "queue": queue_path.as_posix(),
        "total": len(rows),
        "summary": {
            "by_status": dict(sorted(by_status.items())),
            "by_action": dict(sorted(by_action.items())),
            "due_pending": len(due_pending),
        },
        "next_pending": next_pending,
        "tasks": sorted_queue(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the open-llm-wiki growth queue.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("command", choices=["init", "plan", "enqueue", "list", "run-due"])
    parser.add_argument("--action", choices=sorted(VALID_ACTIONS))
    parser.add_argument("--target", default=".")
    parser.add_argument("--due-at", default=now_iso())
    parser.add_argument("--reason", default="manual queue item")
    parser.add_argument("--priority", type=int, default=50)
    parser.add_argument("--cadence", choices=sorted(CADENCE_DAYS), default="now", help="Default queue plan cadence.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format for list.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    state_dir = ensure_within(vault / "_state", vault, "_state must stay inside the vault")
    queue_path = ensure_within(state_dir / "growth-queue.jsonl", state_dir, "growth queue must stay inside _state")
    rows = load_queue(queue_path)
    if args.command == "init":
        save_queue(queue_path, rows)
        print(f"queue: {queue_path}")
        return 0
    if args.command == "plan":
        added = plan_defaults(vault, rows, args.cadence)
        save_queue(queue_path, rows)
        print(f"planned: {added}")
        print(f"cadence: {args.cadence}")
        print(f"queue: {queue_path}")
        return 0
    if args.command == "enqueue":
        if not args.action:
            raise SystemExit("--action is required for enqueue")
        added = enqueue(rows, args.action, args.target, args.due_at, args.reason, args.priority)
        save_queue(queue_path, rows)
        print("enqueued" if added else "already queued")
        return 0
    if args.command == "list":
        if args.format == "json":
            print(json_dump(queue_json(queue_path, rows)))
            return 0
        for row in sorted_queue(rows):
            print(f"{row.get('status')} {row.get('due_at')} p{row.get('priority')} {row.get('action')} {row.get('target')} {row.get('task_id')}")
        return 0
    if args.command == "run-due":
        due_now = datetime.now().isoformat()
        for row in sorted(rows, key=lambda item: (item.get("due_at", ""), item.get("priority", 50))):
            if row.get("status") != "pending" or str(row.get("due_at", "")) > due_now:
                continue
            print(f"run {row['task_id']}: {row['action']}")
            if args.dry_run:
                continue
            row["status"] = "running"
            row["attempts"] = int(row.get("attempts", 0)) + 1
            save_queue(queue_path, rows)
            try:
                run_action(vault, str(row["action"]))
                row["status"] = "done"
                row["completed_at"] = now_iso()
            except SystemExit as exc:
                row["status"] = "failed"
                row["last_error"] = str(exc)
            save_queue(queue_path, rows)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
