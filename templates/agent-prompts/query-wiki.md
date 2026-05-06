# Agent Prompt: Query Wiki

## Goal

Answer a research question from this LLM Wiki using only evidence already present in the vault.

## Inputs

- Vault path:
- User question:
- Required output format:

## Allowed Writes

- No writes by default.
- If the user asks for an artifact, write only to `qa-reports/` or another explicitly approved report path inside the vault.

## Safety Boundaries

- Work only inside this vault.
- Cite source, claim, or concept evidence for every determinate statement.
- Clearly separate evidence, inference, hypothesis, and forecast.
- Do not turn forecasts into facts.
- Do not edit concept or source pages during query answering.

## Required Checks

```bash
python .open-llm-wiki/scripts/wiki_search.py . "<query terms>" --limit 8
python .open-llm-wiki/scripts/wiki_status.py .
```

## Final Report

Return the answer, evidence links, unsupported claims to avoid, and whether a writeback proposal is recommended.
