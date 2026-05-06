# Agent Prompt: Science Review

## Goal

Generate or inspect the science review queue without fabricating review approval.

## Inputs

- Vault path:
- Claims file:
- Review threshold or focus:

## Allowed Writes

- `_state/science-review-queue.jsonl`
- `qa-reports/`
- `log.md`

## Safety Boundaries

- A generated review queue is not a human approval.
- Do not change `needs_review` to false unless an explicit human review decision is provided.
- Do not edit raw evidence.
- Preserve claim IDs and evidence links.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_science_review.py . --write-report --queue
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
python .open-llm-wiki/scripts/wiki_status.py . --write-dashboard --force
```

## Final Report

Return review item counts, report path, queue path, highest-risk claims, and the exact human decisions still required.
