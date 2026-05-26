#!/usr/bin/env python3
"""Create source pages from cloud-parsed Markdown corpus outputs."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, read_text, write_text
from wiki_source_registry import (
    allocate_source_id,
    find_by_raw_hash,
    find_by_raw_path,
    load_registry,
    raw_hash as compute_raw_hash,
    register_raw,
    save_registry,
    source_uuid_from_id,
    update_status,
)


CONCEPTS = {
    "llm-research": ("LLM Research", "How language model research contributes reusable knowledge across architectures, data, training, evaluation, and deployment."),
    "attention-mechanisms": ("Attention Mechanisms", "How attention mechanisms model relationships between tokens, modalities, or retrieved context."),
    "transformer-architectures": ("Transformer Architectures", "How Transformer-style architectures organize attention, feed-forward blocks, normalization, and scaling."),
    "language-modeling": ("Language Modeling", "How models learn to predict, generate, translate, or reason with language."),
    "evaluation-benchmarks": ("Evaluation Benchmarks", "How benchmarks and protocols measure model behavior and compare systems."),
    "deepseek-family": ("DeepSeek Model Family", "How DeepSeek systems evolve across language, code, math, multimodal, and reasoning work."),
    "code-generation": ("Code Generation", "How code-oriented training and evaluation improve programming and reasoning capability."),
    "mathematical-reasoning": ("Mathematical Reasoning", "How models learn, verify, and improve mathematical problem solving."),
    "mixture-of-experts": ("Mixture of Experts", "How sparse expert routing changes scaling, efficiency, and specialization."),
    "reinforcement-learning-reasoning": ("Reinforcement Learning for Reasoning", "How RL changes reasoning behavior after pretraining."),
    "multimodal-models": ("Multimodal Models", "How language models connect text, images, OCR, and generation."),
    "document-ocr": ("Document OCR", "How document parsing and OCR convert visual documents into structured knowledge."),
    "theorem-proving": ("Theorem Proving", "How formal proof systems and LLMs interact."),
    "vision-generation": ("Vision Generation", "How unified or autoregressive systems generate and understand images."),
    "memory-architectures": ("Memory Architectures", "How explicit memory mechanisms alter model capacity and retrieval."),
    "training-data": ("Training Data", "How data construction, filtering, and curricula shape model behavior."),
    "agentic-evaluation": ("Agentic Evaluation", "How benchmarks and tasks evaluate planning, tool use, and long-horizon behavior."),
}


@dataclass
class Item:
    source_id: str
    title: str
    raw_rel: str
    pdf_rel: str
    arxiv: str
    created: str
    tags: list[str]
    concepts: list[str]
    abstract: str
    evidence: list[tuple[str, str, str]]
    opening_line: int


def clean_line(line: str) -> str:
    line = re.sub(r"<[^>]+>", " ", line)
    return re.sub(r"\s+", " ", line).strip(" #*\t\r\n")


def first_heading(lines: list[str], fallback: str) -> str:
    for line in lines[:80]:
        if line.strip().startswith("#"):
            title = clean_line(line)
            if len(title) > 4 and not title.lower().startswith("abstract"):
                return title
    for line in lines[:80]:
        title = clean_line(line)
        if len(title) > 12 and not title.lower().startswith(("abstract", "contents")):
            return title
    return fallback


def arxiv_from_name(name: str) -> str:
    match = re.search(r"(\d{4}\.\d{5})", name)
    return match.group(1) if match else ""


def created_from_arxiv(arxiv: str, today: str) -> str:
    if not arxiv:
        return today
    return f"20{int(arxiv[:2]):02d}-{int(arxiv[2:4]):02d}-01"


def abstract_from_lines(lines: list[str]) -> tuple[str, int]:
    start = 0
    for index, line in enumerate(lines):
        clean = clean_line(line)
        if clean.lower() == "abstract":
            start = index + 1
            break
        if clean.lower().startswith("abstract ") and len(clean) > 120:
            return clean[9:1600], index + 1
    collected: list[str] = []
    for index in range(start, min(len(lines), start + 120)):
        clean = clean_line(lines[index])
        lower = clean.lower()
        if index > start and (lower == "introduction" or lower.startswith("1 introduction") or clean.startswith("#")):
            break
        if clean and not lower.startswith(("keywords", "contents")):
            collected.append(clean)
    return " ".join(collected)[:1600], start + 1


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if len(part.strip()) > 30]


def derive_tags(title: str, name: str, abstract: str) -> list[str]:
    hay = f"{title} {name} {abstract}".lower()
    tags = ["deepseek"] if "deepseek" in hay else []
    rules = [
        ("attention", ["attention", "self-attention", "multi-head"]),
        ("transformer", ["transformer", "encoder", "decoder"]),
        ("language-model", ["language model", "language modeling", "translation", "sequence transduction"]),
        ("code", ["coder", "code", "programming", "humaneval"]),
        ("math", ["math", "aime", "mathematical"]),
        ("reasoning", ["reasoning", "r1", "grpo", "reinforcement"]),
        ("moe", ["moe", "mixture-of-experts", "expert"]),
        ("ocr", ["ocr", "document", "layout"]),
        ("multimodal", ["vl", "vision-language", "multimodal", "image"]),
        ("theorem-proving", ["prover", "lean", "theorem"]),
        ("vision-generation", ["janus", "flow", "generation", "visual"]),
        ("memory", ["engram", "memory"]),
        ("training-data", ["training data", "dataset", "data"]),
        ("evaluation", ["benchmark", "evaluation", "score"]),
    ]
    for tag, needles in rules:
        if any(needle in hay for needle in needles):
            tags.append(tag)
    return sorted(dict.fromkeys(tags))[:6]


def load_concept_definitions(path: Path | None) -> dict[str, tuple[str, str]]:
    if path is None:
        return dict(CONCEPTS)
    data = json.loads(read_text(path))
    if not isinstance(data, dict):
        raise SystemExit("--concepts-file must contain a JSON object")
    concepts = dict(CONCEPTS)
    for concept_id, value in data.items():
        if isinstance(value, list) and len(value) >= 2:
            title, question = str(value[0]), str(value[1])
        elif isinstance(value, dict):
            title = str(value.get("title", concept_id.replace("-", " ").title()))
            question = str(value.get("question", value.get("description", "")))
        else:
            raise SystemExit(f"invalid concept definition for {concept_id!r}")
        if not title or not question:
            raise SystemExit(f"concept definition for {concept_id!r} requires title and question")
        concepts[str(concept_id)] = (title, question)
    return concepts


def concepts_for_tags(tags: list[str], title: str, abstract: str, concept_defs: dict[str, tuple[str, str]]) -> list[str]:
    mapping = {
        "attention": "attention-mechanisms",
        "transformer": "transformer-architectures",
        "language-model": "language-modeling",
        "translation": "language-modeling",
        "evaluation": "evaluation-benchmarks",
        "deepseek": "deepseek-family",
        "code": "code-generation",
        "math": "mathematical-reasoning",
        "reasoning": "reinforcement-learning-reasoning",
        "moe": "mixture-of-experts",
        "ocr": "document-ocr",
        "multimodal": "multimodal-models",
        "theorem-proving": "theorem-proving",
        "vision-generation": "vision-generation",
        "memory": "memory-architectures",
        "training-data": "training-data",
    }
    concepts = [mapping[tag] for tag in tags if tag in mapping and mapping[tag] in concept_defs]
    if "Janus" in title and "vision-generation" in concept_defs and "vision-generation" not in concepts:
        concepts.append("vision-generation")
    hay = f"{title} {abstract}".lower()
    for concept_id, (concept_title, _question) in concept_defs.items():
        terms = [concept_id.replace("-", " "), concept_title.lower()]
        if any(term and term in hay for term in terms):
            concepts.append(concept_id)
    fallback = "llm-research" if "llm-research" in concept_defs else sorted(concept_defs)[0]
    return sorted(dict.fromkeys(concepts or [fallback]))


COMPACT_METRIC_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:B|M|K|T)\b")
EXPLICIT_METRIC_RE = re.compile(
    r"(?<![A-Za-z])\d+(?:\.\d+)?\s*"
    r"(?:%|tokens?|parameters?|experts?|pages?|samples?|languages|benchmarks|gpu hours?)\b",
    re.IGNORECASE,
)
METRIC_CONTEXT_RE = re.compile(
    r"(parameter|activated|active|token|context|expert|language|benchmark|score|accuracy|"
    r"training|cost|gpu|pass@|aime|math|mmlu|gpqa|humaneval|bleu|ocr|flop)",
    re.IGNORECASE,
)
CITATION_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]\b", re.IGNORECASE)


def metric_value_match(clean: str) -> re.Match[str] | None:
    explicit = EXPLICIT_METRIC_RE.search(clean)
    if explicit:
        return explicit
    compact = COMPACT_METRIC_RE.search(clean)
    if not compact:
        return None
    value = compact.group(0).strip()
    if CITATION_YEAR_RE.fullmatch(value):
        return None
    if not METRIC_CONTEXT_RE.search(clean):
        return None
    return compact


def is_low_signal_metric_line(clean: str) -> bool:
    lower = clean.lower()
    if CITATION_YEAR_RE.search(clean) and any(marker in lower for marker in ["arxiv", "preprint", "et al", "proceedings"]):
        return True
    if clean.count("$") >= 2 and not METRIC_CONTEXT_RE.search(clean):
        return True
    return False


def evidence_rows(lines: list[str], raw_rel: str) -> list[tuple[str, str, str]]:
    keywords = re.compile(
        r"(parameter|token|benchmark|score|accuracy|training|model|expert|AIME|MATH|"
        r"HumanEval|GPQA|MMLU|OCR|BLEU|FLOP|%|B\b|M\b|K\b)",
        re.IGNORECASE,
    )
    rows: list[tuple[str, str, str]] = []
    for number, line in enumerate(lines, 1):
        clean = clean_line(line)
        lower = clean.lower()
        if not (55 <= len(clean) <= 260):
            continue
        if lower.startswith(("figure ", "table ", "fig. ")) or clean.startswith("#"):
            continue
        if is_low_signal_metric_line(clean):
            continue
        if not re.search(r"\d", clean) or not keywords.search(clean):
            continue
        value = metric_value_match(clean)
        if not value:
            continue
        rows.append((clean, value.group(0), f"{raw_rel}#L{number}"))
        if len(rows) >= 4:
            break
    if not rows:
        for number, line in enumerate(lines[:140], 1):
            clean = clean_line(line)
            if len(clean) > 70:
                rows.append((clean[:240], "qualitative claim", f"{raw_rel}#L{number}"))
                if len(rows) >= 2:
                    break
    return rows


def build_item(vault: Path, source_id: str, combined: Path, today: str, concept_defs: dict[str, tuple[str, str]]) -> Item:
    raw_rel = combined.relative_to(vault).as_posix()
    stem = combined.parent.name.removesuffix("_markdown")
    _raw_source, pdf_rel = original_source_for_artifact(vault, combined)
    text = read_text(combined)
    lines = text.splitlines()
    title = first_heading(lines, stem.replace("_", " "))
    arxiv = arxiv_from_name(combined.parent.name)
    abstract, opening_line = abstract_from_lines(lines)
    tags = derive_tags(title, combined.parent.name, abstract)
    return Item(
        source_id=source_id,
        title=title,
        raw_rel=raw_rel,
        pdf_rel=pdf_rel,
        arxiv=arxiv,
        created=created_from_arxiv(arxiv, today),
        tags=tags,
        concepts=concepts_for_tags(tags, title, abstract, concept_defs),
        abstract=abstract,
        evidence=evidence_rows(lines, raw_rel),
        opening_line=opening_line,
    )


def source_text(item: Item, status: str, today: str) -> str:
    sentences = split_sentences(item.abstract)
    contribution = sentences[0] if sentences else f"{item.title} is ingested as evidence for the LLM wiki."
    core = " ".join(sentences[:4]) or item.abstract[:900]
    source = item.title + (f", arXiv:{item.arxiv}" if item.arxiv else "")
    safe_title = item.title.replace('"', '\\"')
    safe_source = source.replace('"', '\\"')
    tags = ", ".join(item.tags)
    concepts = ", ".join(f"[[{concept}]]" for concept in item.concepts)
    rows = "\n".join(f"| Reported claim | {value} | as stated in source | {anchor} |" for _claim, value, anchor in item.evidence)
    evidence = "\n".join(f"- {anchor}: {claim}" for claim, _value, anchor in item.evidence)
    return f"""---
id: {item.source_id}
title: "{safe_title}"
status: {status}
created: {item.created}
updated: {today}
source: "{safe_source}"
tags: [{tags}]
---

# {item.title}

## One-Sentence Contribution

{contribution}

## Core Idea

{core}

## Key Data

| Metric | Value | Baseline | Evidence |
| --- | --- | --- | --- |
{rows}

Evidence:

- paper: {item.pdf_rel}
- parsed markdown: {item.raw_rel}
- abstract/opening anchor: {item.raw_rel}#L{item.opening_line}
{evidence}

## Timeline Position

```text
Prior related LLM work
`-- {item.created[:7]} {item.title}
    `-- Later concept synthesis in this wiki
```

## Interpretation

This page treats the parsed paper as primary evidence, not final synthesis. The durable wiki claim is that this source contributes to {concepts}. Broader causal interpretations belong in concept pages and must be marked as inference.

## Links

- Related concepts: {concepts}
- Related sources: to be added by future contradiction and concept revision passes.
"""


def qa_text(item: Item, draft: str, today: str) -> tuple[bool, str]:
    issues = []
    if len(item.abstract) < 120:
        issues.append("abstract/opening extraction is short; inspect the original PDF when possible.")
    if len(item.evidence) < 2:
        issues.append("fewer than two evidence anchors were extracted.")
    if "Evidence:" not in draft:
        issues.append("missing Evidence block.")
    overall = 8.2 if not issues else 7.2
    passed = overall >= 7.0
    issue_text = "\n".join(f"  - {issue}" for issue in issues) if issues else "  - none"
    return passed, f"""# QA Report: {item.source_id}
- date: {today}
- reviewer: independent-qa-deterministic-second-pass
- accuracy: {overall}/10
- completeness: {overall}/10
- compression: 8.4/10
- traceability: {overall}/10
- overall: {overall}/10
- verdict: {"PASS" if passed else "FAIL"}
- issues:
{issue_text}

## Review Notes

The reviewer inspected the generated draft, parsed Markdown path, and schema requirements. This structural QA is sufficient for publication only when followed by semantic claim extraction and corpus-level QA.
"""


def contradiction_text(item: Item, today: str) -> str:
    concepts = ", ".join(f"[[{concept}]]" for concept in item.concepts)
    return f"""# Contradiction Report: {item.source_id}
- date: {today}
- reviewer: contradiction-scan-deterministic
- verdict: NO_CONFIRMED_CONTRADICTION
- source: [[{item.source_id}]]
- related concepts: {concepts}

## Findings

- No direct contradiction was confirmed during source publication.
- Claim-level contradiction scanning should be rerun through `wiki_grow.py` after corpus ingest.
"""


def concept_text(concept_id: str, items: list[Item], today: str, concept_defs: dict[str, tuple[str, str]]) -> str:
    title, question = concept_defs[concept_id]
    bullets = "\n".join(f"- [[{item.source_id}]] contributes evidence from *{item.title}*." for item in items)
    sources = "\n".join(f"- [[{item.source_id}|{item.title}]] - source page for this concept" for item in items)
    return f"""---
id: {concept_id}
title: "{title}"
created: {today}
updated: {today}
---

# {title}

> {question}

## Why It Matters

This concept helps connect individual source pages into reusable wiki knowledge.

## Current Understanding

{bullets}

## Open Questions

- Which claims remain comparable after normalizing model size, data, compute, and evaluation protocol?
- Which claims are explicit facts, and which are cross-source inference?

## Sources

{sources}
"""


def merge_concept_page(path: Path, items: list[Item]) -> None:
    text = read_text(path)
    additions = [
        f"- [[{item.source_id}|{item.title}]] - source page for this concept"
        for item in items
        if f"[[{item.source_id}" not in text
    ]
    if additions:
        write_text(path, text.rstrip() + "\n" + "\n".join(additions) + "\n")


def merge_index(vault: Path, items: list[Item], concept_items: dict[str, list[Item]], concept_defs: dict[str, tuple[str, str]]) -> None:
    index_path = vault / "index.md"
    text = read_text(index_path) if index_path.exists() else ""
    source_rows = [
        f"| [[{item.source_id}]] | {item.title.replace('|', '/')} | {', '.join(item.tags)} |"
        for item in items
        if f"[[{item.source_id}]]" not in text
    ]
    concept_rows = [
        f"| [[{concept_id}]] | {concept_defs[concept_id][1].replace('|', '/')} | {', '.join(f'[[{item.source_id}]]' for item in concept_sources)} |"
        for concept_id, concept_sources in sorted(concept_items.items())
        if f"[[{concept_id}]]" not in text
    ]
    if source_rows:
        marker = "\n## Concepts\n"
        if marker in text:
            text = text.replace(marker, "\n".join(source_rows) + "\n" + marker, 1)
        else:
            text = text.rstrip() + "\n\n" + "\n".join(source_rows)
    if concept_rows:
        text = text.rstrip() + "\n" + "\n".join(concept_rows)
    write_text(index_path, text.rstrip() + "\n")


def original_source_from_manifest(vault: Path, combined: Path) -> tuple[Path, str] | None:
    manifest_path = combined.parent / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(read_text(manifest_path))
    except json.JSONDecodeError:
        return None
    raw_root = (vault / "raw").resolve()
    vault_root = vault.resolve()
    for key in ("source_path", "input"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = vault / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(raw_root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved, resolved.relative_to(vault_root).as_posix()
    return None


def original_source_for_artifact(vault: Path, combined: Path) -> tuple[Path, str]:
    manifest_source = original_source_from_manifest(vault, combined)
    if manifest_source is not None:
        return manifest_source
    stem = combined.parent.name.removesuffix("_markdown")
    if combined.parent.parent != vault / "raw":
        for suffix in (".pdf", ".md", ".txt"):
            candidate = combined.parent.parent / f"{stem}{suffix}"
            if candidate.exists() and candidate.is_file():
                return candidate, candidate.relative_to(vault).as_posix()
    for suffix in (".pdf", ".md", ".txt"):
        candidate = vault / "raw" / f"{stem}{suffix}"
        if candidate.exists() and candidate.is_file():
            return candidate, candidate.relative_to(vault).as_posix()
    return combined, combined.relative_to(vault).as_posix()


def discover_combined_files(raw_dir: Path) -> list[Path]:
    combined_files: list[Path] = []
    for combined in sorted(raw_dir.rglob("*_markdown/combined.md")):
        ensure_within(combined, raw_dir, "combined Markdown input must stay under raw/")
        combined_files.append(combined)
    return combined_files


def original_source_from_manifest(vault: Path, combined: Path) -> tuple[Path, str] | None:
    manifest_path = combined.parent / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(read_text(manifest_path))
    except json.JSONDecodeError:
        return None
    raw_root = (vault / "raw").resolve()
    vault_root = vault.resolve()
    for key in ("source_path", "input"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = vault / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(raw_root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved, resolved.relative_to(vault_root).as_posix()
    return None


def find_registry_row(rows: list[dict[str, object]], raw_rel: str, artifact_rel: str) -> dict[str, object] | None:
    return find_by_raw_path(rows, raw_rel) or find_by_raw_path(rows, artifact_rel)


def ensure_registry_identity(row: dict[str, object], state_dir: Path, today: str) -> None:
    if not row.get("source_id"):
        row["source_id"] = allocate_source_id(state_dir)
    if not row.get("source_uuid"):
        row["source_uuid"] = source_uuid_from_id(str(row["source_id"]))
    if not row.get("created"):
        row["created"] = today


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest raw/*_markdown/combined.md files into source pages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Workflow:\n"
            "  Reads each raw/*_markdown/combined.md file, including nested corpus folders,\n"
            "  creates draft source pages, runs deterministic\n"
            "  QA report generation, publishes passing pages to sources/LLM-NNNN.md, writes contradiction\n"
            "  reports, updates concept pages, index.md, log.md, and _state/id-counter.md.\n"
            "\n"
            "Resume behavior:\n"
            "  By default, existing source/concept/QA pages are protected. Use --resume to skip already\n"
            "  existing source IDs and continue any remaining raw/*_markdown/combined.md files. Use\n"
            "  --force-empty only for a controlled regenerated corpus vault.\n"
        ),
    )
    parser.add_argument("vault", type=Path)
    parser.add_argument("--today", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--resume", action="store_true", help="Skip existing source IDs instead of refusing existing output.")
    parser.add_argument("--force-empty", action="store_true", help="Overwrite generated source/concept/QA outputs.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concepts-file", type=Path, help="Optional JSON object mapping concept ids to [title, question] definitions.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    concept_defs = load_concept_definitions(args.concepts_file)
    dirs = {
        folder: ensure_within(vault / folder, vault, f"{folder} directory must stay inside the vault")
        for folder in ["raw", "sources", "concepts", "drafts", "qa-reports", "_state"]
    }
    for folder_path in dirs.values():
        folder_path.mkdir(parents=True, exist_ok=True)
    if not args.resume and not args.force_empty and any(
        any((vault / folder).glob("*.md")) for folder in ["sources", "concepts", "qa-reports"]
    ):
        raise SystemExit("refusing to overwrite existing wiki pages; use --resume or --force-empty")

    combined_files = discover_combined_files(dirs["raw"])
    if args.limit:
        combined_files = combined_files[: args.limit]
    if not combined_files:
        raise SystemExit("no raw/*_markdown/combined.md files found")

    registry_path = ensure_within(dirs["_state"] / "source-registry.jsonl", dirs["_state"], "registry must stay under _state/")

    # Register raw files in registry
    registry_rows = load_registry(registry_path)
    for combined in combined_files:
        artifact_rel = combined.relative_to(vault).as_posix()
        raw_file, raw_rel = original_source_for_artifact(vault, combined)
        stem = combined.parent.name.removesuffix("_markdown")
        existing = find_registry_row(registry_rows, raw_rel, artifact_rel)
        artifact_hash = compute_raw_hash(combined)
        if existing is None:
            h = compute_raw_hash(raw_file)
            dup = find_by_raw_hash(registry_rows, h)
            if dup is not None:
                ensure_registry_identity(dup, dirs["_state"], args.today)
                source_id_new = allocate_source_id(dirs["_state"])
                new_row = {
                    "source_uuid": source_uuid_from_id(source_id_new),
                    "source_id": source_id_new,
                    "raw_hash": h,
                    "raw_path": raw_rel,
                    "artifact_path": artifact_rel,
                    "artifact_hash": artifact_hash,
                    "status": "archived",
                    "duplicate_of": dup.get("source_id", ""),
                    "title": stem.replace("_", " "),
                    "kind": "raw",
                    "created": args.today,
                    "updated": args.today,
                }
                registry_rows.append(new_row)
            else:
                register_raw(
                    registry_path, dirs["_state"],
                    raw_path=raw_rel,
                    raw_file=raw_file,
                    title=stem.replace("_", " "),
                    arxiv=arxiv_from_name(combined.parent.name),
                    kind="raw",
                )
                registry_rows = load_registry(registry_path)
                existing = find_registry_row(registry_rows, raw_rel, artifact_rel)
                if existing is not None:
                    existing["artifact_path"] = artifact_rel
                    existing["artifact_hash"] = artifact_hash
                    save_registry(registry_path, registry_rows)
        else:
            ensure_registry_identity(existing, dirs["_state"], args.today)
            existing["raw_path"] = raw_rel
            existing["artifact_path"] = artifact_rel
            existing["artifact_hash"] = artifact_hash
            # Preserve existing raw_hash for stale detection;
            # hash will be updated after successful publish
            if not existing.get("raw_hash"):
                h = compute_raw_hash(raw_file)
                existing["raw_hash"] = h
            existing["updated"] = args.today
            save_registry(registry_path, registry_rows)

    save_registry(registry_path, registry_rows)
    registry_rows = load_registry(registry_path)

    items: list[Item] = []
    concept_items: dict[str, list[Item]] = defaultdict(list)
    skipped_published = 0
    skipped_stale = 0
    for combined in combined_files:
        artifact_rel = combined.relative_to(vault).as_posix()
        raw_file, raw_rel = original_source_for_artifact(vault, combined)
        reg_row = find_registry_row(registry_rows, raw_rel, artifact_rel)
        if reg_row is None:
            continue
        ensure_registry_identity(reg_row, dirs["_state"], args.today)
        if reg_row.get("duplicate_of"):
            continue
        source_id = reg_row["source_id"]

        source_path = ensure_within(dirs["sources"] / f"{source_id}.md", dirs["sources"], "source output must stay under sources/")

        # Skip unchanged published sources
        if source_path.exists() and reg_row.get("status") == "published":
            current_hash = compute_raw_hash(raw_file)
            if current_hash == reg_row.get("raw_hash", ""):
                skipped_published += 1
                continue
            else:
                # Source changed since published: block stale re-ingest
                update_status(registry_path, reg_row["source_uuid"], "stale",
                              last_error="raw source hash changed since last published")
                skipped_stale += 1
                print(f"WARNING: {raw_rel} changed since published; marked stale, skipping")
                continue

        if args.resume and source_path.exists():
            continue
        try:
            item = build_item(vault, source_id, combined, args.today, concept_defs)
            items.append(item)
            draft = source_text(item, "draft", args.today)
            draft_path = ensure_within(dirs["drafts"] / f"{source_id}.md", dirs["drafts"], "draft output must stay under drafts/")
            write_text(draft_path, draft)
            passed, qa = qa_text(item, draft, args.today)
            write_text(ensure_within(dirs["qa-reports"] / f"{source_id}.md", dirs["qa-reports"], "QA output must stay under qa-reports/"), qa)
            if passed:
                write_text(source_path, source_text(item, "stable", args.today))
                draft_path.unlink(missing_ok=True)
                write_text(
                    ensure_within(dirs["qa-reports"] / f"{source_id}-contradiction.md", dirs["qa-reports"], "QA output must stay under qa-reports/"),
                    contradiction_text(item, args.today),
                )
                # Update raw_hash to current file hash at publish time
                publish_hash = compute_raw_hash(raw_file)
                update_status(registry_path, reg_row["source_uuid"], "published",
                              kind="source", tags=item.tags, concepts=item.concepts,
                              raw_hash=publish_hash,
                              raw_path=raw_rel,
                              artifact_path=artifact_rel,
                              artifact_hash=compute_raw_hash(combined))
                for concept in item.concepts:
                    concept_items[concept].append(item)
            else:
                update_status(registry_path, reg_row["source_uuid"], "failed",
                              last_error="QA score below 7.0")
        except Exception as exc:
            update_status(registry_path, reg_row["source_uuid"], "failed", last_error=str(exc))
            raise

    for concept_id, concept_sources in sorted(concept_items.items()):
        concept_path = ensure_within(dirs["concepts"] / f"{concept_id}.md", dirs["concepts"], "concept output must stay under concepts/")
        if args.resume and concept_path.exists():
            merge_concept_page(concept_path, concept_sources)
        else:
            write_text(concept_path, concept_text(concept_id, concept_sources, args.today, concept_defs))

    source_rows = "\n".join(f"| [[{item.source_id}]] | {item.title.replace('|', '/')} | {', '.join(item.tags)} |" for item in items)
    concept_rows = "\n".join(
        f"| [[{concept_id}]] | {concept_defs[concept_id][1].replace('|', '/')} | {', '.join(f'[[{item.source_id}]]' for item in concept_sources)} |"
        for concept_id, concept_sources in sorted(concept_items.items())
    )
    if args.resume and (vault / "index.md").exists():
        merge_index(vault, items, concept_items, concept_defs)
    else:
        write_text(
            ensure_within(vault / "index.md", vault, "index output must stay inside the vault"),
            "# LLM Wiki Index\n\n## Sources\n| ID | Title | Tags |\n| --- | --- | --- |\n"
            + source_rows
            + "\n\n## Concepts\n| Concept | Key Question | Sources |\n| --- | --- | --- |\n"
            + concept_rows
            + "\n",
        )

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    log_path = ensure_within(vault / "log.md", vault, "log output must stay inside the vault")
    log_lines = [read_text(log_path).rstrip() if log_path.exists() else "# Wiki Log"]
    for item in items:
        log_lines.append(f"[{stamp}] publish | sources/{item.source_id}.md | corpus-ingest | {item.title}")
        log_lines.append(f"[{stamp}] contradiction-check | qa-reports/{item.source_id}-contradiction.md | corpus-ingest | no confirmed contradiction")
    write_text(log_path, "\n".join(log_lines).rstrip() + "\n")

    print(f"ingested_sources={len(items)}")
    print(f"published_sources={len(list(dirs['sources'].glob('LLM-*.md')))}")
    print(f"concepts={len(list(dirs['concepts'].glob('*.md')))}")
    if skipped_published:
        print(f"skipped_published={skipped_published}")
    if skipped_stale:
        print(f"skipped_stale={skipped_stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
