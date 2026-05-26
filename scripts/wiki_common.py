#!/usr/bin/env python3
"""Shared helpers for open-llm-wiki runtime scripts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SOURCE_ID_RE = re.compile(r"\bLLM-\d{4}\b")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
LOG_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] [a-z-]+ \| .+ \| .+ \| .+$")


@dataclass
class Finding:
    priority: str
    path: str
    message: str
    fix: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "priority": self.priority,
            "path": self.path,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class Page:
    path: Path
    relpath: str
    frontmatter: dict[str, str]
    body: str
    links: set[str] = field(default_factory=set)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def ensure_within(path: Path, root: Path, message: str) -> Path:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise SystemExit(message) from exc
    return resolved_path


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = read_text(path)
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    close_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if close_index is None:
        return {}, text
    block = "".join(lines[1:close_index])
    body = "".join(lines[close_index + 1 :])
    fields: dict[str, str] = {}
    current_key = ""
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("-"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key:
            fields[key] = value
            current_key = key
        elif current_key:
            fields[current_key] += " " + value
    return fields, body


def load_pages(vault: Path, folders: Iterable[str] = ("sources", "drafts", "concepts")) -> list[Page]:
    pages: list[Page] = []
    for folder in folders:
        root = vault / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            frontmatter, body = parse_frontmatter(path)
            links = {link.strip() for link in WIKILINK_RE.findall(body)}
            pages.append(Page(path=path, relpath=rel(path, vault), frontmatter=frontmatter, body=body, links=links))
    return pages


def source_id_from_path(path: Path) -> str | None:
    match = SOURCE_ID_RE.search(path.name)
    return match.group(0) if match else None


def existing_targets(vault: Path) -> set[str]:
    targets: set[str] = set()
    for path in (vault / "sources").glob("LLM-*.md"):
        source_id = source_id_from_path(path)
        if source_id:
            targets.add(source_id)
    for path in (vault / "concepts").glob("*.md"):
        targets.add(path.stem)
    return targets


def score_text(query_terms: list[str], text: str) -> int:
    haystack = text.lower()
    score = 0
    for term in query_terms:
        if not term:
            continue
        count = haystack.count(term)
        score += count * (4 if " " in term else 1)
    return score


def markdown_findings(findings: list[Finding]) -> str:
    if not findings:
        return "- none"
    return "\n".join(
        f"- [{item.priority}] `{item.path}`: {item.message}"
        + (f" Fix: {item.fix}" if item.fix else "")
        for item in findings
    )


def json_dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
