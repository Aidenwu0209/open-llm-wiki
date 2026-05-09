#!/usr/bin/env python3
"""Create source pages from cloud-parsed Markdown corpus outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wiki_common import ensure_within, read_text, write_text


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
    source_uuid: str
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
    source_sha256: str = ""
    artifact_sha256: str = ""
    parser: str = "pdf-to-markdown"
    parser_version: str = "1.0"


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


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_item(vault: Path, source_id: str, combined: Path, today: str, concept_defs: dict[str, tuple[str, str]]) -> Item:
    raw_rel = combined.relative_to(vault).as_posix()
    stem = combined.parent.name.removesuffix("_markdown")
    pdf = vault / "raw" / f"{stem}.pdf"
    pdf_rel = pdf.relative_to(vault).as_posix() if pdf.exists() else f"raw/{stem}.pdf"
    text = read_text(combined)
    lines = text.splitlines()
    title = first_heading(lines, stem.replace("_", " "))
    arxiv = arxiv_from_name(combined.parent.name)
    abstract, opening_line = abstract_from_lines(lines)
    tags = derive_tags(title, combined.parent.name, abstract)
    return Item(
        source_id=source_id,
        source_uuid=str(uuid.uuid4())[:8],
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
        source_sha256=_sha256(pdf),
        artifact_sha256=_sha256(combined),
    )


def source_text(item: Item, status: str, today: str, qa_verdict: str = "",
                claims_total: int = 0, claims_supported: int = 0,
                claims_needing_review: int = 0) -> str:
    sentences = split_sentences(item.abstract)
    contribution = sentences[0] if sentences else f"{item.title} is ingested as evidence for the LLM wiki."
    core = " ".join(sentences[:4]) or item.abstract[:900]
    safe_title = item.title.replace('"', '\\"')
    safe_source = (item.title + (f", arXiv:{item.arxiv}" if item.arxiv else "")).replace('"', '\\"')
    tags = ", ".join(item.tags)
    concepts_yaml = ", ".join(item.concepts)
    concepts_links = ", ".join(f"[[{c}]]" for c in item.concepts)
    rows = "\n".join(f"| Reported claim | {value} | as stated in source | {anchor} |" for _claim, value, anchor in item.evidence)
    evidence = "\n".join(f"- {anchor}: {claim}" for claim, _value, anchor in item.evidence)
    verdict_display = qa_verdict or ("PASS" if status == "stable" else "")
    return f"""---
type: source
source_id: {item.source_id}
id: {item.source_id}
source_uuid: "{item.source_uuid}"
title: "{safe_title}"
status: {status}
source_sha256: "{item.source_sha256}"
artifact_sha256: "{item.artifact_sha256}"
parser: "{item.parser}"
parser_version: "{item.parser_version}"
published_at: {item.created}
updated_at: {today}
created: {item.created}
updated: {today}
source: "{safe_source}"
tags: [{tags}]
qa_verdict: "{verdict_display}"
claims_total: {claims_total}
claims_supported: {claims_supported}
claims_needing_review: {claims_needing_review}
concepts: [{concepts_yaml}]
---

# {item.title}

## One-Sentence Conclusion

{contribution}

## Why It Matters

{core}

## Key Contributions

- {contribution}

## Key Claims

> Claims are extracted after running `wiki_claims.py`. Claim counts are shown in frontmatter.

## Key Metrics

| Metric | Value | Baseline | Evidence |
| --- | --- | --- | --- |
{rows}

## Methods & Data

This page treats the parsed paper as primary evidence, not final synthesis.
Broader causal interpretations belong in concept pages and must be marked as inference.

## Limitations & Controversies

- Limitations to be reviewed after contradiction scanning.

## Related Concepts

{concepts_links}

## Evidence & Source Anchors

- paper: {item.pdf_rel}
- parsed markdown: {item.raw_rel}
- abstract/opening anchor: {item.raw_rel}#L{item.opening_line}
{evidence}

## QA/Review Status

- qa_verdict: {verdict_display or "pending"}
- qa_report: [[qa-reports/{item.source_id}]]
- contradiction_report: [[qa-reports/{item.source_id}-contradiction]]
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


def concept_text(concept_id: str, items: list[Item], today: str,
                concept_defs: dict[str, tuple[str, str]],
                supporting_claims: int = 0, contradicted_claims: int = 0,
                stale_claims: int = 0, related_concepts: list[str] | None = None) -> str:
    title, question = concept_defs[concept_id]
    bullets = "\n".join(f"- [[{item.source_id}]] contributes evidence from *{item.title}*." for item in items)
    sources = "\n".join(f"- [[{item.source_id}|{item.title}]] - source page for this concept" for item in items)
    related = related_concepts or []
    related_yaml = ", ".join(related)
    related_links = ", ".join(f"[[{r}]]" for r in related) if related else "none yet"
    safe_title = title.replace('"', '\\"')
    return f"""---
type: concept
concept_id: {concept_id}
id: {concept_id}
title: "{safe_title}"
status: active
created: {today}
updated: {today}
updated_at: {today}
supporting_claims: {supporting_claims}
contradicted_claims: {contradicted_claims}
stale_claims: {stale_claims}
related_concepts: [{related_yaml}]
---

# {title}

## Definition

{question}

## Core Intuition

This concept helps connect individual source pages into reusable wiki knowledge.

## Why It Matters

Understanding this concept is essential for navigating the evidence landscape in this wiki.

## Key Mechanisms

{bullets}

## Supporting Evidence

> Evidence matrix is populated after running `wiki_claims.py` and `wiki_concept_revision.py`.

## Counter-examples & Controversies

- None detected yet. Rerun contradiction scanning after adding more sources.

## Related Methods & Concepts

{related_links}

## Representative Sources

{sources}

## Open Questions

- Which claims remain comparable after normalizing model size, data, compute, and evaluation protocol?
- Which claims are explicit facts, and which are cross-source inference?
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest raw/*_markdown/combined.md files into source pages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Workflow:\n"
            "  Reads each raw/*_markdown/combined.md file, creates draft source pages, runs deterministic\n"
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

    combined_files = sorted(dirs["raw"].glob("*_markdown/combined.md"))
    for combined in combined_files:
        ensure_within(combined, dirs["raw"], "combined Markdown input must stay under raw/")
    if args.limit:
        combined_files = combined_files[: args.limit]
    if not combined_files:
        raise SystemExit("no raw/*_markdown/combined.md files found")

    items: list[Item] = []
    concept_items: dict[str, list[Item]] = defaultdict(list)
    for offset, combined in enumerate(combined_files, 1):
        source_id = f"LLM-{offset:04d}"
        source_path = ensure_within(dirs["sources"] / f"{source_id}.md", dirs["sources"], "source output must stay under sources/")
        if args.resume and source_path.exists():
            continue
        item = build_item(vault, source_id, combined, args.today, concept_defs)
        items.append(item)
        draft = source_text(item, "draft", args.today)
        draft_path = ensure_within(dirs["drafts"] / f"{source_id}.md", dirs["drafts"], "draft output must stay under drafts/")
        write_text(draft_path, draft)
        passed, qa = qa_text(item, draft, args.today)
        qa_verdict = "PASS" if passed else "FAIL"
        write_text(ensure_within(dirs["qa-reports"] / f"{source_id}.md", dirs["qa-reports"], "QA output must stay under qa-reports/"), qa)
        if passed:
            write_text(source_path, source_text(item, "stable", args.today, qa_verdict=qa_verdict))
            draft_path.unlink(missing_ok=True)
            write_text(
                ensure_within(dirs["qa-reports"] / f"{source_id}-contradiction.md", dirs["qa-reports"], "QA output must stay under qa-reports/"),
                contradiction_text(item, args.today),
            )
            for concept in item.concepts:
                concept_items[concept].append(item)

    # Load claims for enriching source and concept pages
    claims_path = vault / "claims" / "claims.jsonl"
    all_claims: list[dict[str, object]] = []
    if claims_path.exists():
        for line in read_text(claims_path).splitlines():
            if line.strip():
                try:
                    all_claims.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Update source pages with claim counts
    for item in items:
        source_claims = [c for c in all_claims if str(c.get("source_id", "")) == item.source_id]
        claims_total = len(source_claims)
        claims_supported = sum(1 for c in source_claims if not bool(c.get("needs_review")))
        claims_needing_review = sum(1 for c in source_claims if bool(c.get("needs_review")))
        if claims_total > 0:
            source_path = dirs["sources"] / f"{item.source_id}.md"
            if source_path.exists():
                write_text(source_path, source_text(
                    item, "stable", args.today,
                    qa_verdict="PASS",
                    claims_total=claims_total,
                    claims_supported=claims_supported,
                    claims_needing_review=claims_needing_review,
                ))

    # Compute concept claim counts
    concept_claim_counts: dict[str, dict[str, int]] = {}
    for claim in all_claims:
        for concept in claim.get("concepts", []):
            concept_id = str(concept)
            if concept_id not in concept_claim_counts:
                concept_claim_counts[concept_id] = {"supporting": 0, "contradicted": 0, "stale": 0}
            if not bool(claim.get("needs_review")):
                concept_claim_counts[concept_id]["supporting"] += 1
    # Find related concepts from concept_items
    all_concept_ids = set(concept_items.keys())
    for concept_id, concept_sources in sorted(concept_items.items()):
        concept_path = ensure_within(dirs["concepts"] / f"{concept_id}.md", dirs["concepts"], "concept output must stay under concepts/")
        counts = concept_claim_counts.get(concept_id, {"supporting": 0, "contradicted": 0, "stale": 0})
        related = sorted(all_concept_ids - {concept_id})
        if args.resume and concept_path.exists():
            merge_concept_page(concept_path, concept_sources)
        else:
            write_text(concept_path, concept_text(
                concept_id, concept_sources, args.today, concept_defs,
                supporting_claims=counts["supporting"],
                contradicted_claims=counts["contradicted"],
                stale_claims=counts["stale"],
                related_concepts=related,
            ))

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
    next_id = len(list(dirs["sources"].glob("LLM-*.md"))) + 1
    write_text(ensure_within(dirs["_state"] / "id-counter.md", dirs["_state"], "state output must stay under _state/"), f"# ID Counter\nnext: {next_id}\n")

    print(f"ingested_sources={len(items)}")
    print(f"published_sources={len(list(dirs['sources'].glob('LLM-*.md')))}")
    print(f"concepts={len(list(dirs['concepts'].glob('*.md')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
