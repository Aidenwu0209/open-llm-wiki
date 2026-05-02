# open-llm-wiki

**A Claude Code skill bundle and lightweight runtime for turning research
papers into an auditable, compounding LLM wiki.**

open-llm-wiki helps an agent convert papers into source pages, extract durable
claims, connect those claims into concept notes, and keep the knowledge base
honest with independent QA, contradiction checks, append-only logs,
deterministic semantic-growth tools, and reviewable writeback diffs.

Inspired by [Andrej Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

[Quick start](QUICKSTART.md) | [Evaluation checklist](Checklist.md) | [Schema](SCHEMA.md) | [Examples](EXAMPLES.md) | [Showcase](SHOWCASE.md)

---

## Why This Exists

Research notes often become a pile of isolated summaries. open-llm-wiki treats
papers as evidence and concept pages as the living wiki. Each ingest can update
multiple concepts, and useful cross-source answers can be written back after
approval.

The core quality principle is simple: **the agent that writes a source page
must not be the only reviewer of that page**. Stable source pages require an
independent QA pass and an audit record.

## What It Does

| Pipeline | Trigger | Result |
| --- | --- | --- |
| `wiki-ingest` | User asks to add one paper | parsed text, draft source page, independent QA, stable source page, concept updates, contradiction report |
| `query-writeback` | User asks a cross-source wiki question | cited answer first; optional approved writeback to concept pages |
| `wiki-lint` | User or automation asks for a health check | deterministic report-first audit; optional approved maintenance fixes |
| `wiki-grow` runtime | User or automation asks for semantic self-growth | claim extraction, semantic QA, contradiction scan, concept revision, lint |

![Pipeline](assets/pipeline.svg)

## Runtime Layer

The skills coordinate judgment. The runtime scripts handle repeatable checks:

| Script | Purpose |
| --- | --- |
| `scripts/wiki_init.py` | initialize a portable personal/team vault |
| `scripts/pdf_corpus_report.py` | verify converted corpus coverage, manifests, parser warnings, and semantic hits |
| `scripts/pdf_corpus_to_markdown.py` | batch-convert a PDF folder with retries, skip logic, and a TSV audit log |
| `scripts/pdf_to_markdown.py` | convert PDFs to Markdown through a configurable layout-parsing API |
| `scripts/wiki_ingest_corpus.py` | turn parsed Markdown corpus outputs into source/QA/concept pages |
| `scripts/wiki_claims.py` | extract normalized claims into `claims/claims.jsonl` |
| `scripts/wiki_normalize_metrics.py` | normalize metric names, units, baselines, and numeric values |
| `scripts/wiki_semantic_qa.py` | verify extracted claims against source pages and evidence anchors |
| `scripts/wiki_contradictions.py` | scan normalized claims for contradiction candidates |
| `scripts/wiki_science_review.py` | prepare second-pass LLM/human scientific review queues and packets |
| `scripts/wiki_discover_sources.py` | discover raw/arXiv candidates and detect duplicates by arXiv, DOI, hash, and title |
| `scripts/wiki_queue.py` | plan and run a durable growth queue for scheduled wiki maintenance |
| `scripts/wiki_concept_revision.py` | refresh concept pages from review-eligible claims |
| `scripts/wiki_grow.py` | orchestrate discovery, claims, normalization, QA, review, contradictions, revision, and lint |
| `scripts/wiki_lint.py` | verify structure, QA gates, links, index, logs, and stale claims |
| `scripts/wiki_search.py` | local markdown search across source and concept pages |
| `scripts/wiki_writeback.py` | generate or apply reviewable query-writeback diffs |
| `scripts/wiki_eval.py` | smoke-test the runtime against the example vault |

`setup.sh` and `wiki_init.py` copy the runtime into
`<vault>/.open-llm-wiki/scripts/` so a wiki can keep validating itself after it
leaves this repository.

## Quick Start

Inspect the script first if this is your first run:

```bash
curl -fsSL https://raw.githubusercontent.com/AIwork4me/open-llm-wiki/main/setup.sh -o setup.sh
less setup.sh
bash setup.sh my-llm-wiki
```

Or install manually:

```bash
git clone https://github.com/AIwork4me/open-llm-wiki.git
mkdir -p ~/.claude/skills
cp -R open-llm-wiki/skills/* ~/.claude/skills/
```

Then add a paper:

```bash
cp ~/papers/attention.pdf my-llm-wiki/raw/
# Ask Claude Code:
# Ingest this paper: my-llm-wiki/raw/attention.pdf
```

For layout-heavy PDFs, convert to Markdown first with the project-local uv
environment:

```bash
export OPEN_LLM_WIKI_LAYOUT_TOKEN="<token>"
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf \
  --output my-llm-wiki/raw/attention_markdown
```

For a paper corpus:

```bash
uv run python scripts/pdf_corpus_to_markdown.py my-llm-wiki/raw \
  --output-root my-llm-wiki/raw \
  --no-download-images
```

The token is read from the environment and must not be committed. Override the
endpoint with `OPEN_LLM_WIKI_LAYOUT_API_URL` or `--api-url` when using a
different layout-parsing service. Transient cloud failures are retried, and
each output `manifest.json` records the number of API attempts.

After sources exist, run the semantic growth loop:

```bash
uv run python scripts/wiki_grow.py my-llm-wiki \
  --discover-sources \
  --plan-queue \
  --queue-cadence weekly \
  --science-review \
  --apply-concept-revision
```

For a parsed corpus that has `raw/*_markdown/combined.md` but no source pages
yet, add `--ingest-corpus`.

Concept refreshes omit claims that require second-pass scientific review unless
the claim is explicitly marked `science_review: approved`, so uncertain metrics
do not become durable synthesis by accident.

Open `my-llm-wiki/` in [Obsidian](https://obsidian.md) if you want graph view,
backlinks, and tag navigation.

## Safety Boundaries

- Skills write only inside the resolved wiki vault.
- `raw/` is treated as immutable evidence.
- Source pages publish only after independent QA passes.
- Query writeback is read-only by default and requires approval unless the user
  has explicitly pre-authorized automatic wiki growth.
- Lint is report-only by default.
- Cloud OCR is optional and requires explicit configuration and user acceptance
  because document content may leave the local machine.
- PDF-to-Markdown conversion sends document bytes to the configured layout
  parsing API. Use it only for documents the user is allowed to process.
- QA reports and contradiction reports are append-only audit records.
- Semantic self-growth writes a claim graph under `claims/`, source/discovery
  and queue state under `_state/`, QA/review reports under `qa-reports/`, and
  concept revisions only when explicitly applied.

## Repository Layout

```text
open-llm-wiki/
|-- setup.sh
|-- SCHEMA.md
|-- skills/
|   |-- wiki-ingest/
|   |-- query-writeback/
|   `-- wiki-lint/
|-- templates/
|-- examples/
|   `-- minimal-vault/
|-- assets/
|-- QUICKSTART.md
|-- EXAMPLES.md
`-- SHOWCASE.md
```

## Quality Gates

This repository is designed to be checked automatically:

```bash
uv sync --dev
uv run python -m skills_ref.cli validate skills/wiki-ingest
uv run python -m skills_ref.cli validate skills/query-writeback
uv run python -m skills_ref.cli validate skills/wiki-lint
uv run python scripts/check_quality.py
uv run python scripts/wiki_lint.py examples/minimal-vault --fail-on p1
uv run python scripts/wiki_eval.py
bash -n setup.sh
```

`uv` creates and uses the project-local `.venv/`; dependencies are locked in
`uv.lock` and do not need to be installed into the global Python environment.
The validator is invoked through `python -m skills_ref.cli` so Windows systems
with strict application-control policies do not need to execute a generated
`agentskills.exe` shim.

GitHub Actions runs the same checks on push and pull request.

## Design Principles

1. Sources are evidence; concepts are the wiki.
2. Independent QA is a quality gate, not a nice-to-have.
3. Hard numbers need traceable sources and explicit baselines.
4. Contradictions are marked, not silently overwritten.
5. Query writeback should be proposed as a diff before it becomes knowledge.
6. File writes are scoped, logged, and reviewable.
7. Long-term growth requires normalized claims, semantic QA, contradiction
   recall, and periodic concept revision.

## License

MIT
