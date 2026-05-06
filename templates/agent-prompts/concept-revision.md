# Agent Prompt: Concept Revision

## Goal

Preview or apply concept-page updates from reviewed claims while preserving evidence traceability.

## Inputs

- Vault path:
- Target concept(s):
- Apply changes: yes/no

## Allowed Writes

- Preview mode: no writes.
- Apply mode after user approval: `concepts/` and `log.md`.

## Safety Boundaries

- Preview before applying.
- Do not add claims that still require science review as settled concept knowledge.
- Every material statement must cite source evidence.
- Do not edit `raw/`, `sources/`, `drafts/`, `claims/`, `_state/`, or `qa-reports/`.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_concept_revision.py .

# Only after explicit approval:
python .open-llm-wiki/scripts/wiki_concept_revision.py . --apply
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force
```

## Final Report

Return the preview summary, changed concept paths if applied, held-for-review claims, lint result, and dashboard update result.
