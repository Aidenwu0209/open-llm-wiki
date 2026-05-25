---
name: wiki-ingest
description: "Ingest exactly one research paper or source document into an open-llm-wiki vault. Use when the user explicitly asks to add, ingest, process, or publish a paper into the wiki. The workflow parses the source, drafts a source page, runs independent QA, publishes only after the quality gate passes, extracts and normalizes claims, updates concepts/index/log, runs semantic QA, prepares second-pass scientific review, updates source discovery/queue state, and records contradiction checks. Do not use for casual paper summaries or for modifying files outside the wiki vault."
license: MIT
metadata:
  version: "0.3.0"
  reviewed-for: "Claude Code Skills quality"
---

# Wiki Ingest

Ingest one source document into an open-llm-wiki vault. Optimize for
traceability, safe file changes, and independent verification rather than speed.

## Runtime Tools

Prefer deterministic runtime scripts when they are available in either the repo
or the vault:

- `<repo>/scripts/wiki_lint.py`
- `<vault>/.open-llm-wiki/scripts/wiki_lint.py`
- `<repo>/scripts/wiki_grow.py`
- `<vault>/.open-llm-wiki/scripts/wiki_grow.py`
- `<repo>/scripts/wiki_claims.py`
- `<vault>/.open-llm-wiki/scripts/wiki_claims.py`
- `<repo>/scripts/wiki_normalize_metrics.py`
- `<vault>/.open-llm-wiki/scripts/wiki_normalize_metrics.py`
- `<repo>/scripts/wiki_semantic_qa.py`
- `<vault>/.open-llm-wiki/scripts/wiki_semantic_qa.py`
- `<repo>/scripts/wiki_science_review.py`
- `<vault>/.open-llm-wiki/scripts/wiki_science_review.py`
- `<repo>/scripts/wiki_discover_sources.py`
- `<vault>/.open-llm-wiki/scripts/wiki_discover_sources.py`
- `<repo>/scripts/wiki_queue.py`
- `<vault>/.open-llm-wiki/scripts/wiki_queue.py`
- `<repo>/scripts/wiki_contradictions.py`
- `<vault>/.open-llm-wiki/scripts/wiki_contradictions.py`
- `<repo>/scripts/wiki_concept_revision.py`
- `<vault>/.open-llm-wiki/scripts/wiki_concept_revision.py`
- `<repo>/scripts/pdf_corpus_to_markdown.py`
- `<vault>/.open-llm-wiki/scripts/pdf_corpus_to_markdown.py`
- `<repo>/scripts/pdf_to_markdown.py`
- `<vault>/.open-llm-wiki/scripts/pdf_to_markdown.py`
- `<repo>/scripts/wiki_search.py`
- `<vault>/.open-llm-wiki/scripts/wiki_search.py`

Run lint before and after ingest:

```bash
uv run python scripts/wiki_lint.py "<vault>" --fail-on p1
```

## Safety Boundary

- Run only after the user explicitly asks to ingest a source.
- Process one source at a time. Do not batch ingest unless the user asks for a
  serial queue and confirms the order.
- Work only inside the resolved wiki vault. Never write outside `raw/`,
  `drafts/`, `sources/`, `concepts/`, `qa-reports/`, `claims/`, `_state/`,
  `templates/`, `index.md`, or `log.md`.
- Treat `raw/` as immutable evidence. Do not edit, rename, or delete source
  files. Write parsed text to a new file.
- Use local parsing by default. Use cloud OCR only when the user has configured
  credentials and accepts that document content leaves the local machine.
- Before publishing or changing concept pages, summarize the planned file
  changes. If the user requested a fully automated ingest, continue and record
  all changes in `log.md`.
- Never silently overwrite a stable source page, QA report, or contradiction
  report. Create a new draft or ask the user how to handle the conflict.

## Required Preflight

1. Resolve the wiki root and confirm `SCHEMA.md`, `_state/id-counter.md`,
   `index.md`, and `log.md` exist.
2. Confirm the source path exists and is inside `raw/` or was explicitly
   provided by the user.
3. Read `SCHEMA.md` before editing the wiki.
4. Check for an existing source page with the same title, arXiv ID, DOI, or
   filename. Stop and ask before duplicating.
5. Run source discovery/dedupe when available:
   `wiki_discover_sources.py <vault>`.
6. Create a write plan listing every file that may change.

## Pipeline

### 1. Parse

Prefer a local parser. For PDFs, use PyMuPDF when available and write
`raw/<slug>_fulltext.txt`. Record page count, character count, parser, and any
extraction limitations in the draft.

For layout-sensitive PDFs, use `pdf_to_markdown.py` when the user has configured
`OPEN_LLM_WIKI_LAYOUT_TOKEN` and accepts external processing:

```bash
uv run python scripts/pdf_to_markdown.py "<pdf>" --output "<vault>/raw/<slug>_markdown"
```

For an explicitly authorized paper corpus, use the batch wrapper first and then
ingest the resulting `combined.md` files one source at a time:

```bash
uv run python scripts/pdf_corpus_to_markdown.py "<vault>/raw" --output-root "<vault>/raw" --parser auto --no-download-images
```

Use `--parser layout-api` only for sources under the configured service limits
and only when the user accepts that document content leaves the local machine.

### 2. Allocate ID

Read `_state/id-counter.md`, allocate `LLM-NNNN`, and increment the counter
only after the draft file is successfully created. If any step fails before
draft creation, leave the counter unchanged.

### 3. Draft Source Page

Create `drafts/LLM-NNNN.md` with `status: draft`. Required sections:

- one-sentence contribution
- core idea
- key data
- timeline position
- interpretation
- links

Write the `key data` section first. Every numeric claim must include a source
location or table reference when available. Prefer tables over figures; if a
figure is the only source, mark the claim as figure-derived.

Add an `Evidence` block with page, table, section, line, or extraction-offset
anchors for the most important claims. If exact anchors are unavailable, state
what anchor is missing so future lint/review can improve it.

### 4. Self-Check

Before independent QA, verify:

- all required frontmatter fields exist
- every hard number is traceable to parsed text or the original paper
- comparisons name their baseline
- wiki links point to existing pages or are intentionally new
- no private paths, API keys, or unrelated notes were copied into the draft

Self-check is only a preparation step. It never replaces independent QA.

### 5. Independent QA

Run QA in an independent context whenever the environment supports it. The QA
reviewer should receive only the draft path, parsed source path, schema path,
and QA report path. It must not receive the writing history or intended answer.

Save the report to `qa-reports/LLM-NNNN.md` using this structure:

```markdown
# QA Report: LLM-NNNN
- date: YYYY-MM-DD
- reviewer: independent-qa
- accuracy: X/10
- completeness: X/10
- compression: X/10
- traceability: X/10
- overall: X.X/10
- verdict: PASS|FAIL
- issues:
  - ...
```

Publish requires `overall >= 7.0` and `verdict: PASS`. If QA cannot run, keep
the page in `drafts/` and tell the user the quality gate is incomplete.

### 6. Fix Failed QA

If QA fails, fix only the cited issues, re-check the changed claims against the
source, and append a short fix note to the QA report or create a follow-up QA
report if the environment requires immutable reports. Do not promote a page
whose factual issues remain unresolved.

### 7. Publish

When the QA gate passes:

1. Change `status: draft` to `status: stable`.
2. Move `drafts/LLM-NNNN.md` to `sources/LLM-NNNN.md`.
3. Update `_state/id-counter.md` if it was not already updated safely.

### 8. Update Wiki Network

Update concept pages only with claims supported by the source page:

- add or update relevant concept pages in `concepts/`
- add the source to `index.md`
- add bidirectional links when useful
- append a `log.md` entry:
  `[YYYY-MM-DD HH:MM] publish | sources/LLM-NNNN.md | agent | <summary>`

Mark inferred relationships explicitly as inference. Do not present chronology
or proximity as proof of causation.

### 9. Extract Claims And Run Semantic QA

After publish, extract normalized claims and run semantic QA:

```bash
uv run python scripts/wiki_claims.py "<vault>"
uv run python scripts/wiki_normalize_metrics.py "<vault>" --in-place
uv run python scripts/wiki_semantic_qa.py "<vault>" --write-report --fail-on p1
```

Semantic QA must pass at `P1` or better before automatic concept revision or
writeback. If semantic QA fails, keep the source stable only as a published
source page, but do not use it for autonomous synthesis until the cited evidence
issues are fixed.

### 10. Contradiction Check

After publish, compare the new source against related concept pages. Use an
independent context when available. Save findings to
`qa-reports/LLM-NNNN-contradiction.md`.

Then run claim-level contradiction scanning:

```bash
uv run python scripts/wiki_contradictions.py "<vault>" --write-report
```

Prepare second-pass scientific review for a human or independent LLM:

```bash
uv run python scripts/wiki_science_review.py "<vault>" --queue --write-report
```

If a contradiction is found, do not overwrite the older claim. Add both pieces
of evidence and mark the tension with:

`[CONTRADICTION YYYY-MM-DD]`

### 11. Periodic Concept Revision

After every tenth published source, run or recommend a concept revision pass.
Revision should restructure and prune concept pages while preserving useful
cited claims:

```bash
uv run python scripts/wiki_concept_revision.py "<vault>" --apply
uv run python scripts/wiki_queue.py "<vault>" plan
uv run python scripts/wiki_grow.py "<vault>" --discover-sources --plan-queue --queue-cadence weekly --science-review --apply-concept-revision
```

## Completion Criteria

The ingest is complete only when:

- the source page is stable in `sources/`
- QA report exists and passes
- normalized claims exist in `claims/claims.jsonl`
- metric claims have normalized metric/unit/baseline fields
- semantic QA report has no P0/P1 findings
- source registry and growth queue state exist under `_state/`
- science review queue/report exists for claims needing human or second-LLM review
- concept revision excludes review-required claims unless `science_review: approved`
- evidence anchors exist for key claims
- relevant concepts and `index.md` are updated
- contradiction report exists
- `log.md` records the operation
- `wiki_lint.py <vault> --fail-on p1` passes when the runtime is available
- the final response lists changed files and any residual uncertainty
