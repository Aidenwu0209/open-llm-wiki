# open-llm-wiki Schema

This file defines the vault structure and safety rules used by the skills.
Agents should read it before editing a wiki vault.

## Directory Structure

```text
my-llm-wiki/
|-- .open-llm-wiki/ # runtime scripts copied by setup/init
|-- .graph/          # optional derived graph JSON/report/schema
|-- .obsidian/       # optional Obsidian settings when enabled
|-- raw/             # original source files and parsed text
|   `-- inbox/       # optional unprocessed material drop zone
|-- drafts/          # source pages before QA approval
|-- sources/         # stable source pages
|-- concepts/        # evolving concept pages
|-- qa-reports/      # append-only QA and contradiction reports
|-- claims/          # normalized claim graph for semantic QA and growth
|-- canvas/          # optional explanatory diagrams, not evidence
|-- assets/          # optional Obsidian/diagram assets
|-- log-archive/     # archived log entries by month
|-- templates/       # source and concept templates
|   `-- agent-prompts/
|-- _state/          # counters and internal state
|   |-- source-registry.jsonl
|   |-- growth-queue.jsonl
|   |-- science-review-queue.jsonl
|   |-- actions.jsonl
|   `-- action-state.jsonl
|-- _dashboard.md    # optional generated Obsidian status homepage
|-- AGENTS.md        # optional generated agent context for the vault
|-- CLAUDE.md        # optional generated Claude context for the vault
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
| claim graph | `claims/` | normalized durable claims extracted from stable source pages |
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

## Claim Graph

Semantic self-growth uses `claims/claims.jsonl`. Each row is a JSON object
representing a claim ledger entry with the following fields:

### Core Ledger Fields

| Field | Type | Description |
| --- | --- | --- |
| `claim_id` | string | stable generated identifier (e.g. `claim-abc123`) |
| `source_uuid` | string | SHA-256-based UUID derived from source_id |
| `source_id` | string | wiki source ID (`LLM-NNNN`) |
| `chunk_id` | string | optional chunk reference from parse artifacts |
| `claim_text` | string | full human-readable claim text |
| `normalized_claim` | string | lowercased, whitespace-normalized claim text |
| `claim_type` | string | `contribution` or `metric` |
| `entities` | list of strings | named entities extracted from claim text |
| `concepts` | list of strings | related concept page ids |
| `evidence_quote` | string | short precise quote from source (max 300 chars) |
| `evidence_hash` | string | SHA-256[:16] of evidence_quote for tamper detection |
| `anchor` | string | machine-resolvable evidence location |
| `confidence` | float | confidence score |
| `verdict` | string | QA verdict: unreviewed, supported, weak, contradicted, retracted, stale |
| `contradiction_group` | string | group ID if claim is part of a contradiction cluster |
| `created_at` | ISO 8601 | claim creation timestamp |
| `updated_at` | ISO 8601 | last modification timestamp |

### Normalization Fields (metric claims)

- `metric_key`, `normalized_value`, `normalized_unit`, `unit_family`
- `baseline_key`, `protocol_key`, and `normalization_warnings`

### Legacy Fields (kept for backward compatibility)

- `source_title`, `page`, `subject`, `predicate`, `object`
- `value`, `unit`, `baseline`, `evidence`, `needs_review`

### Verdict Lifecycle

```text
unreviewed -> supported | weak
supported -> stale (when source becomes stale)
weak -> supported | contradicted
contradicted -> retracted (after human review)
any -> stale (when source is removed or marked stale)
```

- `supported`: claim is backed by verifiable evidence_quote
- `weak`: evidence_quote is missing, too long, or hash mismatches
- `contradicted`: claim conflicts with another supported claim
- `retracted`: human reviewer confirmed the contradiction
- `stale`: source page no longer exists or has been marked stale

### Concept Synthesis Rules

- Only `supported` claims enter stable concept pages by default
- `weak` and `unreviewed` claims can only enter the review queue section
- `contradicted`, `retracted`, and `stale` claims must not appear in stable
  synthesis
- `wiki_concept_revision.py` enforces this by verdict filtering

### Contradiction Groups

`wiki_contradictions.py --assign-groups` builds contradiction groups based on
normalized_claim, entities, and concepts overlap. Group IDs are formatted as
`CG-NNNN` and assigned to the `contradiction_group` field.

### Stale Hook

When a source page is removed or marked stale, `mark_stale_claims()` sets all
related claims to `verdict: stale`. This is a local claim-level hook; a full
impact graph is planned separately.

The claim graph is generated from stable source pages. It can be regenerated,
but concept-page conclusions and QA reports remain reviewable Markdown records.

## Source Discovery And Deduplication

`_state/source-registry.jsonl` records discovered or ingested source candidates.
Desktop clients should consume this registry instead of maintaining their own
`desktop-ingest-registry.jsonl`. The runtime owns the registry.

Each registry row is a JSON object with required fields `source_uuid`, `source_id`,
`raw_hash`, `raw_path`, and `status`. Valid statuses: `candidate`, `queued`,
`parsed`, `chunked`, `drafted`, `qa_passed`, `published`, `stale`, `failed`,
`archived`.

Deduplication keys include `arxiv`, `doi`, `sha256`/`raw_hash`, and `title_key`.
When a duplicate raw hash is detected, the new row gets `duplicate_of` set to the
original `source_id` and `status: archived`.

Discovery is advisory. It must not delete raw files or source pages.

## Ingest Plan

`_state/ingest-plan.json` is the runtime-owned plan that tells desktop and batch
ingest pipelines what action to take for each source. Desktop clients should read
this file instead of maintaining their own `desktop-ingest-plan.json`.

Generate with: `python wiki_ingest_plan.py <vault> --write`

Plan item schema:

```json
{
  "source_path": "raw/paper_markdown/combined.md",
  "source_hash": "sha256-of-source-file",
  "artifact_path": "raw/paper_markdown/combined.md",
  "artifact_hash": "sha256-of-artifact",
  "parser": "layout-api",
  "parser_version": "",
  "source_uuid": "unique-id",
  "source_id": "LLM-0001",
  "state": "published",
  "reason": "source already published and unchanged",
  "recommended_action": "skip",
  "freshness_verdict": "fresh"
}
```

Plan states and their semantics:

| State | Meaning | Action |
| --- | --- | --- |
| `ready` | Parsed artifact exists and is fresh | Ingest |
| `stageable` | Markdown/txt available for local staging | Ingest via combined.md |
| `blocked` | Needs parser or unsupported format | Run parser first |
| `cached` | Source/artifact unchanged, safe to skip | Skip |
| `published` | Already published, no re-ingest needed | Skip |
| `failed` | Previous ingest failed, needs retry | Retry after fixing |
| `stale` | Source hash changed, old artifact stale | Re-parse and re-ingest |

### Desktop Migration

Desktop clients that previously maintained their own
`_state/desktop-ingest-plan.json` or `_state/desktop-ingest-registry.jsonl`
should migrate to:

1. Read `_state/source-registry.jsonl` for identity and status
2. Read `_state/ingest-plan.json` for action recommendations
3. Stop writing to desktop-owned plan/registry files
4. Let the runtime manage all plan and registry state

## Growth Queue

`_state/growth-queue.jsonl` records durable tasks with `task_id`, `action`,
`target`, `status`, `priority`, `due_at`, `attempts`, and `reason`.
Supported actions are `discover`, `grow`, `science-review`, `concept-revision`,
and `lint`. Queue runners may mark tasks done or failed, but should not edit
raw evidence.
Planning supports `now`, `daily`, `weekly`, and `monthly` cadence values and
stages dependent actions a few minutes apart.

## Second-Pass Scientific Review

`_state/science-review-queue.jsonl` contains claims that need human or second
LLM review. `qa-reports/science-review-YYYY-MM-DD.md` is the append-only review
packet. This layer checks scientific meaning, metric comparability, protocol
compatibility, and baseline fairness beyond deterministic anchor validation.
Queue rows include `review_id`, `review_status`, `review_decision`,
`reviewed_by`, `reviewed_at`, `review_reasons`, and `review_questions`.
Concept revision excludes review-required claims unless the claim is explicitly
marked `science_review: approved`.

## Action Model

The dashboard action model drives the vault's "what should I do next" panel.
Actions are generated from vault state and persisted to `_state/actions.jsonl`.

### Action Row Schema

| Field | Type | Description |
| --- | --- | --- |
| `action_id` | string | fingerprint-based stable identifier (`act-<hash>`) |
| `kind` | string | one of the supported action kinds |
| `severity` | string | `critical`, `high`, `medium`, or `low` |
| `title` | string | short human-readable action title |
| `body` | string | description of what needs attention |
| `reason` | string | why this action matters |
| `status` | string | `open`, `resolved`, or `ignored` |
| `primary_object_type` | string | type of the main object (source, claims, directory, etc.) |
| `primary_object_id` | string | identifier of the main object |
| `affected_objects` | list of strings | other objects impacted by this action |
| `recommended_action` | string | what the user should do |
| `command` | string | CLI command to address this action |
| `links` | list of strings | related wiki links |
| `created_at` | ISO 8601 | action generation timestamp |
| `updated_at` | ISO 8601 | last status change timestamp |

### Supported Kinds

- `parse_required` — unprocessed raw inbox items
- `artifact_stale` — parse artifacts no longer match source
- `ingest_failed` — ingest job in failed state
- `published_duplicate` — duplicate published source detected
- `qa_failed` — draft pages need QA before promotion
- `claims_need_review` — claims flagged for scientific review
- `contradiction_review` — contradiction reports awaiting resolution
- `unsupported_claim` — claims with contradicted/retracted/stale verdict
- `concept_stale` — concepts with time-sensitive wording older than 90 days
- `source_updated` — source page updated within last 7 days
- `impact_review` — downstream concepts may be affected by a change
- `runtime_missing` — runtime scripts directory not installed
- `schema_invalid` — vault structure does not match required schema
- `lint_error` — lint P0/P1 findings that block writeback
- `obsidian_profile_missing` — Obsidian settings incomplete

### Action State Persistence

`_state/action-state.jsonl` records resolved or ignored actions so they do not
reappear on every dashboard refresh. Each row contains `action_id`, `status`,
and `updated_at`.

Actions are fingerprinted from kind, object type, object ID, and reason. The
same underlying issue regenerates the same action_id, so resolved issues stay
suppressed until the underlying condition changes.

### CLI Commands

```bash
python .open-llm-wiki/scripts/wiki_status.py . --actions
python .open-llm-wiki/scripts/wiki_status.py . --resolve-action <action_id>
python .open-llm-wiki/scripts/wiki_status.py . --ignore-action <action_id>
python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force
```

### Dashboard Rendering

The `_dashboard.md` action panel lists open actions sorted by severity
(critical > high > medium > low). Each action card includes severity icon,
kind, reason, affected objects, recommended action, and command. Resolved and
ignored actions are suppressed.

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
4. apply the diff with `--approval-note` so the approval is auditable
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

## Optional Obsidian Layer

Obsidian settings, plugins, themes, and diagrams are an experience layer for
reading, search, navigation, backlinks, and light editing. They must not change
the evidence model.

Rules:

- enable Obsidian only through explicit setup, such as
  `wiki_obsidian_setup.py` or `wiki_init.py --obsidian`.
- merge `.obsidian/*.json` settings; do not overwrite unrelated user keys.
- prefer `[[wikilink]]` for internal wiki links.
- important concept-page conclusions must cite source pages such as
  `[[LLM-NNNN]]`.
- `raw/inbox/` may hold unprocessed material, but it is not stable evidence
  until ingest creates a draft/source page and registry entry.
- `raw/` remains immutable even when files are visible in Obsidian.
- `qa-reports/` remains append-only.
- diagrams under `canvas/` or `assets/excalidraw/` are explanatory aids, not
  evidence sources; link them from source or concept pages and keep evidence
  citations next to the claims they illustrate.
- Obsidian plugins must not bypass QA gates, science review, contradiction
  checks, or query writeback approval.
- `_dashboard.md` is generated status, not evidence. Regenerate it with
  `wiki_status.py --write-dashboard`; do not use it to approve review items.
- `templates/agent-prompts/` may contain reusable agent workflows, but those
  prompts must preserve the same raw immutability, review, QA, and writeback
  approval boundaries as the runtime.

## Optional Knowledge Graph Layer

The knowledge graph is a derived, read-only explanation layer. It may write
`graph.json`, `graph.schema.json`, and `graph-report.md` under `.graph/`, or an
Obsidian Canvas view under `canvas/`. It must not rewrite `sources/`,
`concepts/`, `claims/`, `qa-reports/`, `_state/`, or `raw/`.

Supported node types include `source`, `draft`, `concept`, `claim`, `metric`,
`qa-report`, `contradiction`, `science-review`, `raw`, and `queue-task`.
Supported edge types include `cites`, `derived-from`, `supports`,
`contradicts`, `needs-review`, `reviewed-by`, `updates`, and `related-to`.

Rules:

- graph nodes and Canvas nodes are not evidence sources.
- every durable concept conclusion still needs source or claim citations.
- useful evidence paths should resolve as
  `concept -> claim -> source -> evidence anchor`.
- focused graphs may hide unrelated context but must not change underlying
  Markdown or JSONL data.
- graph export must stay local and must not upload raw files or paper text.
- `wiki_lint.py --graph` reports broken evidence paths or isolated source and
  concept nodes; it does not apply fixes.

## Runtime Commands

The vault may contain runtime scripts at `.open-llm-wiki/scripts/`:

```bash
python .open-llm-wiki/scripts/pdf_corpus_report.py raw --fail-on-missing --fail-on-suspicious
python .open-llm-wiki/scripts/pdf_corpus_to_markdown.py raw --output-root raw --no-download-images
python .open-llm-wiki/scripts/pdf_to_markdown.py raw/source.pdf --output raw/source_markdown
python .open-llm-wiki/scripts/wiki_ingest_corpus.py . --resume
python .open-llm-wiki/scripts/wiki_claims.py .
python .open-llm-wiki/scripts/wiki_normalize_metrics.py . --in-place
python .open-llm-wiki/scripts/wiki_semantic_qa.py . --write-report --fail-on p1
python .open-llm-wiki/scripts/wiki_contradictions.py . --write-report
python .open-llm-wiki/scripts/wiki_science_review.py . --queue --write-report
python .open-llm-wiki/scripts/wiki_discover_sources.py .
python .open-llm-wiki/scripts/wiki_queue.py . plan
python .open-llm-wiki/scripts/wiki_concept_revision.py . --apply
python .open-llm-wiki/scripts/wiki_grow.py . --discover-sources --plan-queue --queue-cadence weekly --science-review --apply-concept-revision
python .open-llm-wiki/scripts/wiki_lint.py . --fail-on p1
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
python .open-llm-wiki/scripts/wiki_lint.py . --graph --fail-on p1
python .open-llm-wiki/scripts/wiki_search.py . "query terms"
python .open-llm-wiki/scripts/wiki_obsidian_setup.py . --profile minimal --skip-downloads
python .open-llm-wiki/scripts/wiki_graph_export.py . --format json
python .open-llm-wiki/scripts/wiki_graph_export.py . --format obsidian-canvas --output canvas/wiki-graph.canvas
python .open-llm-wiki/scripts/wiki_status.py .
python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force
python .open-llm-wiki/scripts/wiki_writeback.py . --target concepts/page.md --query "..." --body "..."
python .open-llm-wiki/scripts/wiki_writeback.py . --target concepts/page.md --query "..." --body "..." --apply --approval-note "User approved this diff"
```
