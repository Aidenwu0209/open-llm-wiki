# Agent Prompt: Graph Export

## Goal

Export or inspect the wiki graph without treating visualization output as evidence.

## Inputs

- Vault path:
- Export format:
- Output path inside the vault:

## Allowed Writes

- Graph export output under a user-approved folder inside the vault.
- No writes to `raw/`, `sources/`, `drafts/`, `concepts/`, `claims/`, `qa-reports/`, or `_state/`.

## Safety Boundaries

- Graphs are navigation aids, not source evidence.
- Do not modify claims or concept pages from graph export.
- Reject output paths outside the vault.
- Keep Obsidian settings merge-safe and preserve user configuration.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_status.py .
python .open-llm-wiki/scripts/wiki_lint.py . --obsidian --fail-on p1
```

## Final Report

Return the export command used, output path, graph limitations, lint result, and whether any missing links or orphan concepts should become a separate one-PR fix.
