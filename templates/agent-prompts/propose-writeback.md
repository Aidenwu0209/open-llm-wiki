# Agent Prompt: Propose Writeback

## Goal

Turn a query-derived insight into a reviewable writeback proposal without silently editing the wiki.

## Inputs

- Vault path:
- Query:
- Proposed target page under `concepts/`:
- Proposed body:
- Evidence links:

## Allowed Writes

- Proposal mode: no writes.
- Apply mode after explicit user approval: `concepts/` and `log.md` only.

## Safety Boundaries

- Query writeback is proposal-first.
- Do not apply without explicit approval from the user.
- Do not write to `raw/`, `sources/`, `drafts/`, `claims/`, `_state/`, or `qa-reports/` from this prompt.
- Preserve source evidence and review semantics.
- Warn if the latest semantic QA report has P0/P1 findings.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_writeback.py . \
  --target concepts/<concept-id>.md \
  --query "<query>" \
  --body "<proposed cited note>"

# Only after explicit approval:
python .open-llm-wiki/scripts/wiki_writeback.py . \
  --target concepts/<concept-id>.md \
  --query "<query>" \
  --body "<proposed cited note>" \
  --apply
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force
```

## Final Report

Return the proposed diff or write plan, target page, evidence links, risks, required human checks, approval status, and validation result if applied.
