# open-llm-wiki Schema

This file defines the vault structure and safety rules used by the skills.
Agents should read it before editing a wiki vault.

## Directory Structure

```text
my-llm-wiki/
|-- .open-llm-wiki/ # runtime scripts copied by setup/init
|-- raw/             # original source files and parsed text
|-- drafts/          # source pages before QA approval
|-- sources/         # stable source pages
|-- concepts/        # evolving concept pages
|-- qa-reports/      # append-only QA and contradiction reports
|-- log-archive/     # archived log entries by month
|-- templates/       # source and concept templates
|-- _state/          # counters and internal state
|-- SCHEMA.md
|-- README.md
|-- index.md
`-- log.md
```

## Page Types

| Type | Directory | Purpose |
| --- | --- | --- |
| source | `sources/` | stable understanding page for one source document |
| draft | `drafts/` | source page before QA approval |
| concept | `concepts/` | evolving synthesis across multiple sources |
| raw | `raw/` | immutable evidence and parsed text |

## Source Frontmatter

```yaml
---
id: LLM-NNNN
title: "Paper Title"
status: draft|stable
created: YYYY-MM-DD
updated: YYYY-MM-DD
source: "Authors, title, venue or arXiv ID, year"
tags: [tag1, tag2]
---
```

Rules:

- `id` must match the filename.
- `status: stable` is allowed only after independent QA passes.
- `created` is the source publication date when known.
- `updated` is the last wiki edit date.
- every source page needs hard numbers or an explicit note that the source has
  no quantitative claims.
- important claims should include evidence anchors: page, section, table, line,
  or extraction offset.

## Concept Frontmatter

```yaml
---
id: concept-name
title: "Concept Display Name"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

Concept pages are living synthesis. They do not use `stable` status, but every
important claim should cite a source page.

## ID Allocation

- source IDs use `LLM-NNNN`
- read `_state/id-counter.md`
- allocate the next number only once a draft is created
- do not reuse IDs after deletion or failed ingest

## Lifecycle

```text
raw/source.pdf
  -> raw/source_fulltext.txt or raw/source_markdown/combined.md
  -> drafts/LLM-NNNN.md (status: draft)
  -> qa-reports/LLM-NNNN.md
  -> sources/LLM-NNNN.md (status: stable)
  -> concepts/*.md
  -> qa-reports/LLM-NNNN-contradiction.md
  -> log.md
```

## QA Gate

A stable source page requires:

- independent QA, not self-review
- `overall >= 7.0`
- `verdict: PASS`
- report saved under `qa-reports/`
- traceable fixes for any QA issues

QA report format:

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

QA reports are append-only. Do not rewrite historical reports.

## Evidence Anchors

Every durable factual claim should be traceable. Use the best available anchor:

- `page: 7`
- `section: 3.2`
- `table: 2`
- `raw extraction: raw/paper_fulltext.txt#L120-L145`
- `doi:` or `arxiv:` when the claim is source identity

If exact anchors are unavailable, write the nearest human-readable anchor and
mark what needs improvement.

## Contradictions

When new evidence conflicts with an existing concept claim:

- keep both pieces of evidence
- mark the tension with `[CONTRADICTION YYYY-MM-DD]`
- cite both sources
- do not silently overwrite older claims

## Query Writeback

Query writeback is for reusable synthesis, not every answer.

Writeback is appropriate when the answer:

- cites three or more sources
- creates a durable comparison table or timeline
- connects concepts not already linked
- identifies a recurring research question

Answering is read-only by default. Writeback requires approval unless the user
has pre-authorized automatic wiki growth.

Preferred writeback flow:

1. answer with citations
2. generate a proposed diff
3. get approval or use explicit pre-authorization
4. apply the diff
5. run lint
6. append `log.md`

## Log Format

Each operation appends one line:

```text
[YYYY-MM-DD HH:MM] action | target | agent | note
```

Allowed actions include:

- `parse`
- `draft`
- `qa`
- `publish`
- `concept-update`
- `query-writeback`
- `contradiction-check`
- `lint`
- `archive`

## File Safety Rules

- never edit original source files in `raw/`
- never modify files outside the wiki vault
- never publish without QA
- never delete pages during ingest or lint without explicit user approval
- prefer targeted edits over whole-page rewrites
- list changed files in the final response

## Runtime Commands

The vault may contain runtime scripts at `.open-llm-wiki/scripts/`:

```bash
python .open-llm-wiki/scripts/pdf_to_markdown.py raw/source.pdf --output raw/source_markdown
python .open-llm-wiki/scripts/wiki_lint.py . --fail-on p1
python .open-llm-wiki/scripts/wiki_search.py . "query terms"
python .open-llm-wiki/scripts/wiki_writeback.py . --target concepts/page.md --query "..." --body "..."
```
