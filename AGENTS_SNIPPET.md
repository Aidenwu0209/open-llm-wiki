# AGENTS_SNIPPET.md

Optional rules to paste into a wiki vault's `AGENTS.md`.

```markdown
## open-llm-wiki Rules

- Read `SCHEMA.md` before editing this wiki.
- Work only inside this wiki vault.
- Treat `raw/` as immutable evidence.
- Ingest one source at a time.
- Source pages start in `drafts/` with `status: draft`.
- A source page can move to `sources/` only after independent QA passes.
- QA reports and contradiction reports are append-only.
- Every important claim in a concept page must cite a source.
- Prefer `[[wikilink]]` for internal links when editing an Obsidian-enabled
  vault.
- Treat `raw/inbox/` as unprocessed material; do not promote it to stable
  evidence without ingest, QA, and registry updates.
- Diagrams under `canvas/` or `assets/excalidraw/` are explanatory aids, not
  evidence sources.
- Merge `.obsidian/*.json` changes and preserve user keys when editing
  Obsidian settings.
- Query writeback is read-only by default; ask before writing unless the user
  has pre-authorized automatic wiki growth.
- Lint is report-only by default; ask before applying fixes.
- Prefer `.open-llm-wiki/scripts/wiki_lint.py` and
  `.open-llm-wiki/scripts/wiki_search.py` when they are available.
- Use `.open-llm-wiki/scripts/wiki_obsidian_setup.py` for optional Obsidian
  setup instead of hand-editing plugin lists.
- Generate writeback diffs with `.open-llm-wiki/scripts/wiki_writeback.py`
  before applying them.
- Use `.open-llm-wiki/scripts/wiki_status.py` to inspect vault health and
  refresh `_dashboard.md` after ingest, review, grow, or approved writeback
  work.
- Treat `_dashboard.md` as generated status, not evidence or approval.
- Use `templates/agent-prompts/` as reusable workflows, but keep the same raw,
  QA, science review, and writeback approval boundaries.
- Log every write in `log.md` using:
  `[YYYY-MM-DD HH:MM] action | target | agent | note`
```

Use the skills:

| Skill | Use for |
| --- | --- |
| `wiki-ingest` | adding one paper or source document |
| `query-writeback` | answering and optionally preserving cross-source synthesis |
| `wiki-lint` | checking wiki health |
