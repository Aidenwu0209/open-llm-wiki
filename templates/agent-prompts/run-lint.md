# Agent Prompt: Run Lint

## Goal

Check vault health without making automatic edits.

## Inputs

- Vault path:
- Obsidian checks required: yes/no
- Fail threshold:

## Allowed Writes

- No writes by default.
- If the user asks for a saved report, write it under `qa-reports/` or `runs/` outside the vault only when that path is inside the approved workspace.

## Safety Boundaries

- Lint is report-only.
- Do not fix pages unless the user asks for a specific follow-up change.
- Do not mark review items approved.
- Do not bypass P0/P1 findings.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
python .open-llm-wiki/scripts/wiki_status.py .
```

## Final Report

Return the lint command, result, P0/P1 findings, P2/P3 summary, and recommended one-PR scope if a fix is needed.
