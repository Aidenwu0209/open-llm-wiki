# open-llm-wiki

**The personal AI knowledge base that writes itself.**

Inspired by [Andrej Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Battle-tested with 23 research papers. 3 OpenClaw Skills. Ingest → QA → Query → Evolve.

---

## The Problem

You read papers, take notes, and... forget everything in a week.

Traditional note-taking is **write-only** — you capture knowledge but never retrieve or connect it. Even worse, your notes don't grow. Every paper you read starts from scratch.

## The Insight

Karpathy's LLM Wiki idea: **your knowledge base should compound like interest**.

- Every paper you ingest adds to existing concepts (not just new files)
- Every question you ask can grow the wiki (not just consume it)
- Contradictions are detected automatically (not silently overwritten)
- Quality is enforced by independent AI reviewers (not self-evaluation)

**The result**: a knowledge base that gets smarter with every interaction, not just bigger.

## How It Works

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Paper   │────▶│  Ingest  │────▶│    QA    │────▶│  Promote │
│  (PDF)   │     │ Pipeline │     │ (indep.) │     │  stable  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                                                            │
                       ┌────────────────────────────────────┘
                       ▼
              ┌──────────────┐     ┌──────────────┐
              │   Concept    │────▶│  Contradiction│
              │   Updates    │     │    Check      │
              └──────────────┘     └──────────────┘
                       ▲
                       │
              ┌──────────────┐
              │    Query     │
              │  Writeback   │  ← Your questions grow the wiki too
              └──────────────┘
```

### Three Pipelines

| Pipeline | When | What |
|----------|------|------|
| **Ingest** | You add a paper | Parse → draft → self-check → independent QA → fix → promote → update concepts → contradiction check |
| **Query Writeback** | You ask about wiki content | Search wiki → assess coverage → answer → write synthesis back if valuable |
| **Lint** | Daily (cron) | Format compliance, QA coverage, cross-reference integrity, log health |

### The Key Innovation: Independent QA

**LLMs cannot self-evaluate.** This is the #1 lesson from 23 papers:

- Self-check catches typos. It does NOT catch wrong numbers, misattributed data, or subtle contradictions.
- Every paper goes through an **independent sub-agent QA** (separate context, separate session).
- QA score ≥ 7.0 required to promote from draft to stable.
- Contradiction detection also uses independent sub-agents.

## What's Included

```
open-llm-wiki/
├── README.md                    # This file
├── PHILOSOPHY.md                # Design philosophy and Karpathy's original vision
├── QUICKSTART.md                # 5-minute setup guide
├── SCHEMA.md                    # Wiki data structure and conventions
├── EXAMPLES.md                  # Anti-patterns from 23 papers of experience
├── skills/
│   ├── wiki-ingest/SKILL.md     # Paper ingestion pipeline (10 steps)
│   ├── query-writeback/SKILL.md # Query-driven wiki growth (6 steps)
│   └── wiki-lint/SKILL.md       # Periodic health check (5 dimensions)
├── templates/
│   ├── source-template.md       # Template for paper understanding pages
│   └── concept-template.md      # Template for concept accumulation pages
├── examples/
│   └── deepseek-v3-sample.md   # A complete source page example
└── LICENSE                      # MIT
```

## Quick Start

### Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) installed and running
- An AI model configured (we recommend GLM-5.1 for sub-agents)

### Install

```bash
# Clone the repo
git clone https://github.com/yourusername/open-llm-wiki.git

# Copy skills to your OpenClaw skills directory
cp -r open-llm-wiki/skills/* ~/.openclaw-autoclaw/skills/

# Create your wiki directory structure
mkdir -p my-wiki/{raw,sources,concepts,drafts,qa-reports,templates,_state,log-archive}

# Copy templates and schema
cp open-llm-wiki/SCHEMA.md my-wiki/
cp open-llm-wiki/templates/* my-wiki/templates/
```

### Use

```
You: ingest this paper → drops PDF

Agent: [runs 10-step pipeline, ~12 min]
       ✓ Parsed 24 pages, 45KB
       ✓ Draft LLM-0001 written (1.8KB)
       ✓ QA: 8.2/10 PASS
       ✓ Promoted to sources/
       ✓ Updated 3 concept pages
       ✓ No contradictions detected

You: How did MoE architectures evolve from DeepSeek-V2 to V3?

Agent: [searches wiki, synthesizes from 5 sources]
       [writes comparison back to concept page]
       Answer: ...
```

See [QUICKSTART.md](QUICKSTART.md) for detailed setup instructions.

## Design Principles

### 1. Sources are input, Concepts are the wiki

Papers are just raw material. Concepts — the evolving, cross-referenced understanding — are the real knowledge base. One paper's ingest should update 3-5 concept pages.

### 2. LLMs cannot self-evaluate

Self-check catches typos. Independent QA catches wrong numbers, misattributed benchmarks, and subtle contradictions. QA AND contradiction detection use separate sub-agent sessions.

### 3. Queries grow the wiki

Good questions produce good synthesis. A comparison table, a timeline, a connection you discovered — these are valuable and shouldn't disappear into chat history.

### 4. Contradictions are marked, never silently overwritten

When new evidence conflicts with old claims, both are kept with `⚠️ [CONTRADICTION]` markers. Truth emerges from debate, not from overwriting.

### 5. Hard numbers are the backbone

"The model achieves competitive results" is useless. "MiniF2F-test: 88.9% pass ratio, PutnamBench: 47/658" is knowledge. Every QA failure we saw was caused by missing hard numbers.

## Battle-Tested

This framework was built and validated through ingesting **23 DeepSeek research papers** (Jan 2024 – Jan 2026), covering:

- Architecture evolution: DeepSeek LLM → V2 → V3 → V4
- Reasoning breakthroughs: R1, GRPO, distillation
- Multimodal: VL, VL2, Janus family
- Specialized: Math, OCR, Prover, mHC

Key metrics from development:
- 31% first-pass QA rate → taught us to write hard numbers first
- 0/3 reliability with claude-sonnet-4 sub-agents → 4/4 with glm-5.1
- 1 critical data misattribution caught (V3.2 Figure vs Table)
- All 23 papers cross-verified against raw text

See [EXAMPLES.md](EXAMPLES.md) for the full catalog of lessons learned.

## Why OpenClaw?

[OpenClaw](https://github.com/openclaw/openclaw) is an open-source AI agent platform that provides:
- **Sub-agent spawning** — independent QA and contradiction checks run in separate sessions
- **Skill system** — the three pipelines are installable, versioned Skills
- **Heartbeat/cron** — periodic lint runs automatically
- **Multi-model** — use different models for different tasks (main agent + QA sub-agent)

The framework's key features (independent QA, sub-agent contradiction checks) fundamentally require an agent platform. OpenClaw is what we use, but the concepts are portable.

## Acknowledgments

- **Andrej Karpathy** — the [original LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) that inspired this framework
- **OpenClaw** — the agent platform that makes independent QA and sub-agent workflows possible
- **DeepSeek** — the 23 papers that served as our test suite

## License

MIT
