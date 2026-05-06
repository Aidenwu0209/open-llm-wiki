# Agent Prompt: Ingest One Source

## Goal

Ingest exactly one source into this LLM Wiki and leave a reviewable audit trail.

## Inputs

- Vault path:
- Raw evidence path under `raw/`:
- Source title:
- Date:

## Allowed Writes

- `drafts/`
- `claims/`
- `qa-reports/`
- `_state/source-registry.jsonl`
- `log.md`

Do not edit `raw/` after the source is copied into the vault.

## Safety Boundaries

- Work only inside this vault.
- Treat `raw/` as immutable evidence.
- Do not promote a draft source to `sources/` until QA passes.
- Do not fabricate human review, science review, or approval.
- Do not use cloud OCR, hosted parsers, or external model APIs unless the user explicitly approves that path.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_discover_sources.py .
python .open-llm-wiki/scripts/wiki_ingest_corpus.py .
python .open-llm-wiki/scripts/wiki_semantic_qa.py . --write-report --fail-on p1
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force
```

## Final Report

Return the source page path, QA report path, claim output path, lint result, status dashboard update result, and any review-required claims.
