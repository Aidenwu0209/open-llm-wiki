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

Override the skill directory when needed:

```bash
OPEN_LLM_WIKI_SKILL_DIR="$HOME/.openclaw-autoclaw/skills" bash setup.sh my-llm-wiki
```

## Option B: Manual Setup

```bash
git clone https://github.com/AIwork4me/open-llm-wiki.git
mkdir -p ~/.claude/skills
cp -R open-llm-wiki/skills/* ~/.claude/skills/

mkdir -p my-llm-wiki/{raw,sources,concepts,drafts,qa-reports,templates,_state,log-archive}
cp open-llm-wiki/SCHEMA.md my-llm-wiki/
cp open-llm-wiki/templates/* my-llm-wiki/templates/
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
7. `log.md` records the operation

## Convert PDF to Markdown

For layout-heavy PDFs, use the project-local uv environment and keep the token
outside the repository:

```bash
export OPEN_LLM_WIKI_LAYOUT_TOKEN="<token>"
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf \
  --output my-llm-wiki/raw/attention_markdown
```

Useful options:

```bash
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --dry-run
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --no-download-images
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf --api-url "$OPEN_LLM_WIKI_LAYOUT_API_URL"
```

This sends the PDF bytes to the configured layout-parsing API. Use it only for
documents you are allowed to process externally. The output includes
`combined.md`, per-document Markdown files, downloaded images when enabled, and
`manifest.json`.

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

## Validate the Repository

From the repo root:

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

The repo uses uv's project-local `.venv/` and `uv.lock`; no package needs to be
installed into the global Python environment.
