---
name: wiki-lint
description: "Run a health check for an open-llm-wiki vault. Use when the user asks to lint, audit, validate, or periodically check wiki quality. The default mode is report-only: inspect schema compliance, QA coverage, links, stale claims, contradictions, and log health. Modify files only when the user explicitly requests fix mode or a scheduled automation has been configured to allow safe maintenance writes."
license: MIT
metadata:
  version: "0.2.0"
  reviewed-for: "Claude Code Skills quality"
---

# Wiki Lint

Audit an open-llm-wiki vault for structural, traceability, and maintenance
problems. Default to report-only.

## Runtime Tool

Use the deterministic linter whenever available:

```bash
uv run python scripts/wiki_lint.py "<vault>" --fail-on p1
```

The script checks structure, frontmatter, QA gates, contradiction reports,
links, index coverage, stale claims, and log format. Read its report before
doing any manual inspection.

## Safety Boundary

- Read-only by default.
- Fix mode requires explicit user approval or an automation prompt that clearly
  authorizes maintenance writes.
- Never edit files in `raw/`.
- Never rewrite QA reports; they are append-only audit records.
- When fixing, show a write plan first and keep edits targeted.

## Checks

### 1. Structure

- required directories exist: `raw/`, `sources/`, `concepts/`, `drafts/`,
  `qa-reports/`, `_state/`, `templates/`
- required root files exist: `SCHEMA.md`, `index.md`, `log.md`
- source page filenames match `LLM-NNNN.md`

### 2. Frontmatter

- source pages include `id`, `title`, `status`, `created`, `updated`, `source`,
  and `tags`
- stable source pages live in `sources/`
- draft source pages live in `drafts/`
- concept pages include `id`, `title`, `created`, and `updated`
- IDs are unique and sequential enough to audit

### 3. QA Coverage

- every stable source has `qa-reports/LLM-NNNN.md`
- every QA report has `overall` and `verdict`
- no stable source has a failing or missing QA gate
- contradiction reports exist after publish when required by the workflow

### 4. Links and Index

- `[[LLM-NNNN]]` links resolve to source pages
- `[[concept-name]]` links resolve to concept pages
- `index.md` lists all stable source pages and concept pages
- orphan pages are reported, not automatically deleted

### 5. Claim Hygiene

- flag words such as "latest", "current", and "state of the art" when the page
  is older than 90 days
- report `[CONTRADICTION ...]` markers that need follow-up
- suggest concept pages for topics appearing in three or more sources

### 6. Log Health

- log entries should follow:
  `[YYYY-MM-DD HH:MM] action | target | agent | note`
- report entries older than 30 days
- in fix mode, archive old entries to `log-archive/YYYY-MM.md` without changing
  archived history

## Output

Return a concise report:

```markdown
# Wiki Lint Report
- date: YYYY-MM-DD
- mode: report-only|fix
- structure: PASS|FAIL
- frontmatter: PASS|FAIL
- qa: PASS|FAIL
- links: PASS|FAIL
- claim hygiene: PASS|WARN|FAIL
- log: PASS|WARN|FAIL

## Findings
- [P1] path: issue and suggested fix

## Files changed
- none
```

Use priorities:

- `P0`: data corruption, missing stable-source QA, broken schema
- `P1`: broken links, unsafe status, duplicate IDs
- `P2`: stale claims, missing index rows, orphan pages
- `P3`: style or cleanup

## Fix Mode

If the user asks to fix issues, address only the reported findings. Re-run
`wiki_lint.py` after edits and report remaining findings.
