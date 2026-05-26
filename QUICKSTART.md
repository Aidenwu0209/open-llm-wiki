# Quick Start

This guide sets up open-llm-wiki for Claude Code. The skills may also be adapted
to other agents, but Claude Code is the default path.

## Prerequisites

- Git
- Bash
- Claude Code with access to `~/.claude/skills/`
- A workspace directory for your wiki vault

Optional:

- PyMuPDF for local PDF parsing
- Obsidian for graph view, backlinks, local search, and daily reading
- `OPEN_LLM_WIKI_LAYOUT_TOKEN` for cloud PDF-to-Markdown conversion of
  layout-heavy documents

## Option A: Scripted Setup

Inspect before running:

```bash
curl -fsSL https://raw.githubusercontent.com/AIwork4me/open-llm-wiki/main/setup.sh -o setup.sh
less setup.sh
bash setup.sh my-llm-wiki
```

The script:

- creates `my-llm-wiki/`
- copies `SCHEMA.md` and templates
- initializes `index.md`, `log.md`, and `_state/id-counter.md`
- installs the three skills into `~/.claude/skills/`
- copies runtime scripts into `my-llm-wiki/.open-llm-wiki/scripts/`
- when Obsidian is enabled, creates `_dashboard.md`, agent context files, and
  reusable prompt templates under `templates/agent-prompts/`

Override the skill directory when needed:

```bash
OPEN_LLM_WIKI_SKILL_DIR="$HOME/.openclaw-autoclaw/skills" bash setup.sh my-llm-wiki
```

Enable the optional Obsidian experience layer during setup:

```bash
OPEN_LLM_WIKI_OBSIDIAN=1 OPEN_LLM_WIKI_OBSIDIAN_PROFILE=minimal bash setup.sh my-llm-wiki
```

Set `OPEN_LLM_WIKI_OBSIDIAN_SKIP_DOWNLOADS=1` when you want the vault settings,
`raw/inbox/`, and sort order without downloading community plugins or the
Minimal theme. Supported profiles are `minimal`, `research`, and `full`.
Fresh Obsidian-enabled vaults open to `_dashboard.md`, which lists pipeline
status, review queues, recent reports, common commands, and Agent prompt
templates.

## Option B: Manual Setup

```bash
git clone https://github.com/AIwork4me/open-llm-wiki.git
mkdir -p ~/.claude/skills
cp -R open-llm-wiki/skills/* ~/.claude/skills/

mkdir -p my-llm-wiki/{raw,sources,concepts,drafts,qa-reports,templates,_state,log-archive}
mkdir -p my-llm-wiki/claims
mkdir -p my-llm-wiki/.open-llm-wiki/scripts
cp open-llm-wiki/SCHEMA.md my-llm-wiki/
cp -R open-llm-wiki/templates/* my-llm-wiki/templates/
cp open-llm-wiki/scripts/*.py my-llm-wiki/.open-llm-wiki/scripts/
```

Create `my-llm-wiki/_state/id-counter.md`:

```markdown
# ID Counter
next: 1
```

Create `my-llm-wiki/index.md`:

```markdown
# LLM Wiki Index

## Sources
| ID | Title | Tags |
| --- | --- | --- |

## Concepts
| Concept | Key Question | Sources |
| --- | --- | --- |
```

Create `my-llm-wiki/log.md`:

```markdown
# Wiki Log
```

Create `my-llm-wiki/claims/claims.jsonl`:

```bash
touch my-llm-wiki/claims/claims.jsonl
```

Create required state JSONL files:

```bash
touch my-llm-wiki/_state/growth-queue.jsonl
touch my-llm-wiki/_state/source-registry.jsonl
touch my-llm-wiki/_state/science-review-queue.jsonl
```

## Ingest Your First Paper

Copy a paper into `raw/`:

```bash
cp ~/papers/attention.pdf my-llm-wiki/raw/
```

Ask Claude Code:

```text
Ingest this paper: my-llm-wiki/raw/attention.pdf
```

Expected result:

1. parsed text is written under `raw/`
2. a draft source page is created under `drafts/`
3. independent QA writes `qa-reports/LLM-NNNN.md`
4. passing drafts move to `sources/`
5. related concept pages and `index.md` are updated
6. a contradiction report is recorded
7. normalized claims can be extracted into `claims/claims.jsonl`
8. `log.md` records the operation

## Extract A Local ZIP Corpus

If papers arrive as a ZIP package, place the ZIP under the vault raw area first,
then extract it locally. The extractor refuses path traversal, absolute paths,
symlinks, and overwrites, and appends an audit manifest under `_state/`.

```bash
mkdir -p my-llm-wiki/raw/inbox
cp deepseek_paper.zip my-llm-wiki/raw/inbox/
uv run python scripts/wiki_extract_archive.py my-llm-wiki raw/inbox/deepseek_paper.zip --dry-run
uv run python scripts/wiki_extract_archive.py my-llm-wiki raw/inbox/deepseek_paper.zip \
  --output-dir raw/deepseek_paper
```

## Convert PDF to Markdown

For layout-heavy PDFs, use the project-local uv environment and keep the token
outside the repository:

```bash
export OPEN_LLM_WIKI_LAYOUT_TOKEN="<token>"
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf \
  --output my-llm-wiki/raw/attention_markdown
```

For a folder of papers, use the corpus wrapper. It skips completed conversions
unless `--force` is set and writes a TSV audit log:

```bash
uv run python scripts/pdf_corpus_to_markdown.py my-llm-wiki/raw \
  --output-root my-llm-wiki/raw \
  --no-download-images
```

Useful options:

```bash
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --dry-run
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --retries 4 --timeout 900
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --no-download-images
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --api-url "$OPEN_LLM_WIKI_LAYOUT_API_URL"
```

This sends the PDF bytes to the configured layout-parsing API. Use it only for
documents you are allowed to process externally. The output includes
`combined.md`, per-document Markdown files, downloaded images when enabled, and
`manifest.json` with the API attempt count and parser warnings.

## Run Semantic Self-Growth

After source pages exist, run the semantic loop:

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_grow.py my-llm-wiki \
  --discover-sources \
  --plan-queue \
  --queue-cadence weekly \
  --science-review \
  --apply-concept-revision
```

This writes `_state/source-registry.jsonl`, `_state/growth-queue.jsonl`,
`_state/science-review-queue.jsonl`, `claims/claims.jsonl`, normalized claim
fields, a semantic QA report, a second-pass science review packet, a claim-level
contradiction report, refreshed semantic claim matrices in concept pages, and a
lint result. Concept refresh skips review-required claims until they are marked
`science_review: approved`. If the vault only has parsed Markdown outputs, add
`--ingest-corpus`.

## Ask the Wiki

Ask a synthesis question:

```text
How did attention mechanisms evolve from RNN seq2seq to Transformer?
```

The `query-writeback` skill answers from wiki pages first. If the answer is
valuable enough to preserve, it proposes a writeback plan. File changes happen
only after approval unless you have explicitly pre-authorized automatic
writeback.

You can also search locally before asking for synthesis:

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_search.py my-llm-wiki "attention transformer"
```

## Run a Health Check

```text
Run wiki lint on my-llm-wiki.
```

Lint is report-only by default. Ask for fix mode only when you want maintenance
writes such as index repair or log archival.

Run the deterministic linter directly:

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_lint.py my-llm-wiki --fail-on p1
```

If the vault has the optional Obsidian profile, include the Obsidian checks:

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_lint.py my-llm-wiki --obsidian --fail-on p1
python my-llm-wiki/.open-llm-wiki/scripts/wiki_status.py my-llm-wiki --write-dashboard --force
```

To add Obsidian settings to an existing vault:

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_obsidian_setup.py my-llm-wiki --profile minimal
```

## Export a Knowledge Graph

The graph export is read-only. It creates derived files under `.graph/` or
`canvas/` and never rewrites source, concept, claim, or QA pages.

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_graph_export.py my-llm-wiki --format json
python my-llm-wiki/.open-llm-wiki/scripts/wiki_graph_export.py my-llm-wiki \
  --focus concepts/attention-mechanisms.md --depth 2
python my-llm-wiki/.open-llm-wiki/scripts/wiki_graph_export.py my-llm-wiki \
  --format obsidian-canvas --output canvas/wiki-graph.canvas
python my-llm-wiki/.open-llm-wiki/scripts/wiki_lint.py my-llm-wiki --graph --fail-on p1
```

## Propose a Writeback Diff

For long-lived team knowledge bases, preserve useful answers through reviewable
diffs:

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_writeback.py my-llm-wiki \
  --target concepts/attention-mechanisms.md \
  --query "Why did attention become central?" \
  --body "Attention created direct token-to-token interaction paths. [[LLM-0001]]"
```

Review the diff before applying. Add `--apply` only after approval.

```bash
python my-llm-wiki/.open-llm-wiki/scripts/wiki_writeback.py my-llm-wiki \
  --target concepts/attention-mechanisms.md \
  --query "Why did attention become central?" \
  --body "Attention created direct token-to-token interaction paths. [[LLM-0001]]" \
  --apply \
  --approval-note "User approved this diff after review"
```

## Validate the Repository

From the repo root:

```bash
uv sync --dev
uv run python -m skills_ref.cli validate skills/wiki-ingest
uv run python -m skills_ref.cli validate skills/query-writeback
uv run python -m skills_ref.cli validate skills/wiki-lint
uv run python scripts/check_quality.py
uv run python scripts/wiki_lint.py examples/minimal-vault --fail-on p1
uv run python scripts/wiki_lint.py examples/minimal-vault --graph --fail-on p1
uv run python scripts/wiki_status.py examples/minimal-vault
uv run python scripts/wiki_obsidian_setup.py examples/minimal-vault --dry-run --skip-downloads
uv run python scripts/wiki_graph_export.py examples/minimal-vault --format json
uv run python scripts/wiki_eval.py
bash -n setup.sh
```

The repo uses uv's project-local `.venv/` and `uv.lock`; no package needs to be
installed into the global Python environment.
