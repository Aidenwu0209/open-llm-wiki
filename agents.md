# AGENTS.md — Contributor Guide for AI Agents and Humans

> Read this file before contributing. It defines the rules, structure, and workflow for this project.

---

## Before making any changes

1. **Search existing issues** at https://github.com/yourusername/open-llm-wiki/issues
2. **If no issue exists, create one** — describe what you want to add/fix and why
3. **Comment on the issue** stating your approach
4. **Branch from `main`**: `git checkout -b feat/short-description main`

---

## Repo Map

```
open-llm-wiki/
├── README.md              ← Start here. What this project is.
├── README.zh.md           ← Chinese version
├── AGENTS.md              ← This file. Rules and structure.
├── SHOWCASE.md            ← Real output from 23 papers. Proof it works.
├── PHILOSOPHY.md          ← Design philosophy. Why these decisions.
├── EXAMPLES.md            ← Anti-patterns. What we learned the hard way.
├── QUICKSTART.md          ← 5-minute setup guide.
├── AGENTS_SNIPPET.md      ← Copy-paste config for your AGENTS.md.
├── SCHEMA.md              ← Wiki data structure and conventions.
├── LICENSE                ← MIT
│
├── skills/                ← OpenClaw Skills (the core product)
│   ├── wiki-ingest/       ←   Paper → source page pipeline (10 steps)
│   ├── query-writeback/   ←   Query → wiki growth pipeline (6 steps)
│   └── wiki-lint/         ←   Periodic health check (5 dimensions)
│
├── templates/             ← Page templates for wiki content
│   ├── source-template.md ←   One paper's understanding page
│   └── concept-template.md←   One concept's accumulation page
│
└── examples/
    ├── deepseek-v3-sample.md  ← Real source page example
    └── minimal-vault/         ← Complete minimal wiki you can run
        ├── index.md           ←   Navigation hub
        ├── log.md             ←   Operation audit trail
        ├── _state/            ←   ID counter
        ├── sources/           ←   Stable paper pages
        ├── concepts/          ←   Evolving concept pages
        ├── drafts/            ←   Pre-QA drafts
        ├── raw/               ←   Original files (empty in example)
        ├── qa-reports/        ←   QA audit records (empty in example)
        └── log-archive/       ←   Archived logs (empty in example)
```

### What goes where

| Want to... | Edit this | Don't touch |
|-----------|-----------|-------------|
| Fix a Skill pipeline | `skills/*/SKILL.md` | Other skills |
| Add a new anti-pattern | `EXAMPLES.md` | SCHEMA.md |
| Update setup instructions | `QUICKSTART.md` | PHILOSOPHY.md |
| Change data conventions | `SCHEMA.md` | Individual skills |
| Add a page template | `templates/` | examples/ |
| Update the example vault | `examples/minimal-vault/` | templates/ |

---

## Architecture

### Three pipelines, one system

```
                    ┌─────────────────────────────────┐
                    │         open-llm-wiki            │
                    │                                 │
  Paper (PDF) ─────▶│  wiki-ingest                    │
                    │    parse → draft → QA → promote │
                    │         ↓                       │
  User query ──────▶│  query-writeback                │
                    │    search → answer → writeback   │
                    │         ↓                       │
  Cron / manual ──▶│  wiki-lint                      │
                    │    format + QA + cross-refs      │
                    └─────────────────────────────────┘
```

### Data flow

```
raw/paper.pdf
    ↓ parse (PyMuPDF or PaddleOCR)
raw/paper_fulltext.txt
    ↓ draft (AI writes understanding)
drafts/LLM-NNNN.md (status: draft)
    ↓ independent QA sub-agent (≥7.0)
sources/LLM-NNNN.md (status: stable)
    ↓ update 3-5 concept pages
concepts/*.md
    ↓ contradiction check (independent sub-agent)
qa-reports/LLM-NNNN-contradiction.md
    ↓ query triggers synthesis
concepts/*.md (updated via writeback)
```

### Key constraint: independent QA

**LLMs cannot self-evaluate.** This is the project's core insight.

- `wiki-ingest` Step 5: **Independent sub-agent** runs QA (separate context, separate session)
- `wiki-ingest` Step 9: **Independent sub-agent** runs contradiction check
- The writing agent can self-check (Step 4), but self-check ≠ QA

Any change that weakens the independence of QA or contradiction detection is a regression.

---

## Hard Rules

Violating any of these will cause a PR to be rejected:

- **QA is always independent** — never self-evaluate, never use the same session that wrote the content
- **QA score ≥ 7.0 required** — no exceptions, no "it looks fine to me"
- **Contradictions are marked, never silently overwritten** — use `⚠️ [CONTRADICTION YYYY-MM-DD]`
- **One paper at a time** — serial ingestion for stability and error isolation
- **Hard numbers in every source page** — "competitive results" is not acceptable
- **Tables over Figures** — when extracting data, always verify against Table text
- **QA reports are append-only** — never modify an existing QA report
- **No new dependencies without an issue** — keep the framework lightweight
- **No API keys required for basic use** — PyMuPDF (local) works out of the box; PaddleOCR is optional

---

## Adding a new Skill

Skills live in `skills/<name>/SKILL.md`. To add a new one:

### Minimal structure

```
skills/my-skill/
└── SKILL.md    ← Required. Frontmatter + pipeline definition.
```

### SKILL.md frontmatter

```yaml
---
name: my-skill
description: One-line description of what this skill does.
version: 0.1.0
---
```

### Skill design rules

1. **Pipeline-based** — define clear steps with inputs and outputs
2. **State success criteria** — each step must have a verifiable check
3. **Reference SCHEMA.md** — don't duplicate data conventions in the skill
4. **Independent evaluation where needed** — any quality gate must use a separate sub-agent
5. **Document lessons learned** — add anti-patterns to EXAMPLES.md, not inline

### Testing a Skill

Before submitting a PR:

1. Install the skill: `cp -r skills/my-skill ~/.openclaw-autoclaw/skills/`
2. Run it against a real paper in a test wiki
3. Verify the output matches SCHEMA.md conventions
4. Check that QA sub-agent produces a valid report

---

## Fixing a bug in a Skill

1. **Identify the specific step** that fails (reference the pipeline step number)
2. **Reproduce with a real paper** — not a hypothetical example
3. **Fix the step** — don't refactor the whole pipeline
4. **Add the anti-pattern to EXAMPLES.md** if it's a new failure mode
5. **Test with the same paper** that triggered the bug

---

## Writing Style

### Skills (SKILL.md)
- Technical, precise, pipeline-oriented
- Each step has: input → action → output → verify
- Include task templates for sub-agents

### Documentation (README, QUICKSTART, PHILOSOPHY)
- Conversational but not chatty
- Lead with the insight, not the history
- English as primary, Chinese translation in README.zh.md

### Wiki content (templates, examples)
- Karpathy style: conversational, opinionated, grounded in hard numbers
- 1-2 KB per source page — not a paper summary, an understanding note
- Concept pages are alive — they grow with every new source

---

## Submitting a PR

```bash
git push -u origin feat/my-feature
gh pr create --base main --fill
```

**Checklist before marking ready for review:**

- [ ] Changes are limited to the files you intended to modify (surgical changes)
- [ ] No new dependencies added without an issue
- [ ] If you changed a Skill, tested it against a real paper
- [ ] If you changed SCHEMA.md, updated all affected Skills
- [ ] Documentation is consistent (English + Chinese README if applicable)
- [ ] No private data, API keys, or personal information in commits

---

## Branch conventions

| Prefix | Use for |
|--------|---------|
| `feat/` | New skill, new feature, new template |
| `fix/` | Bug fix in a skill or documentation |
| `docs/` | Documentation-only changes |
| `refactor/` | Restructure without behavior change |
| `test/` | Add or update test examples |

All PRs target `main`. Squash-merge on approval.
