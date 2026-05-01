# open-llm-wiki

**Your AI knowledge base that compounds. Drop papers in → get a living wiki out.**

Inspired by [Karpathy's LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). 23 papers ingested. 11 concept pages. Zero manual writing. Every fact independently verified.

[Quick Start](#quick-start) · [What It Looks Like](#what-it-looks-like) · [How It Works](#how-it-works) · [Why This Exists](#why-this-exists)

---

## The Problem

You read papers, take notes, and forget everything in a week. Your notes don't grow. Every paper starts from scratch.

## The Fix

A wiki that **compounds** — every paper enriches existing concepts, every question can grow the knowledge base, and contradictions are caught automatically by independent AI reviewers.

---

## What It Looks Like

After ingesting 23 DeepSeek research papers into Obsidian:

**The knowledge graph** — every node is a paper or concept, edges show relationships:

> 📸 Drop a screenshot of Obsidian graph view here: `assets/graph-view.png`

**A concept page** after 8 papers feed into it — evolving understanding, not a static summary:

```markdown
# MoE (Mixture of Experts)

> Fine-grained expert segmentation with load balancing. DeepSeek's signature architecture.

## Innovation Timeline
| When   | What              | Key Result                    |
|--------|-------------------|-------------------------------|
| 2024.01 | DeepSeekMoE      | top-6/64 experts, 2.8B active |
| 2024.06 | Coder-V2         | 236B/21B, MoE for code        |
| 2024.12 | V3               | 671B/37B, aux-loss-free ★     |
| 2026.04 | V4               | 1.6T/49B, 1M context ★★      |

## Key Insight
MoE went from "experimental" to "production architecture" over 4 generations.
The breakthrough was V3's auxiliary-loss-free routing — no more balancing tax.
```

**An anti-pattern we caught** (real example):

> Extracting data from Figures is risky — they have artistic license. We learned this the hard way: unlabeled bars led to 4/5 wrong attributions. **Always verify against Table text.**

---

## How It Works

![Pipeline](assets/pipeline.svg)

Three pipelines, one system:

| Pipeline | Trigger | What It Does |
|----------|---------|-------------|
| **Ingest** | Drop a PDF | Parse → draft → **independent QA** → promote → update concepts → contradiction check |
| **Ask** | Ask a question | Search wiki → synthesize → **write answer back** to wiki |
| **Check** | Daily cron | Format, QA coverage, cross-references, log health |

### The Key Innovation: Independent QA

**LLMs cannot self-evaluate.** This is the #1 lesson from 23 papers.

- Self-check catches typos. It does NOT catch wrong numbers, misattributed data, or subtle contradictions.
- Every paper goes through an **independent sub-agent QA** (separate context, separate session).
- QA score ≥ 7.0 required. No exceptions.
- Contradiction detection also uses independent sub-agents.

```
31% first-pass QA rate  →  taught us to write hard numbers first
0/3 reliability (claude) →  4/4 reliability (glm-5.1)
1 critical misattribution caught  →  Figure vs Table data extraction error
```

---

## Why This Exists

| | Manual Notes | Zotero | Readwise | **open-llm-wiki** |
|---|:-:|:-:|:-:|:-:|
| Auto-ingest papers | ❌ | ❌ | ❌ | ✅ |
| Independent AI QA | ❌ | ❌ | ❌ | ✅ |
| Contradiction detection | ❌ | ❌ | ❌ | ✅ |
| Concepts compound across papers | ❌ | ❌ | Partial | ✅ |
| Query writeback (questions grow the wiki) | ❌ | ❌ | ❌ | ✅ |
| Obsidian native (graph view, backlinks) | ❌ | ✅ | ✅ | ✅ |
| No API keys required | ✅ | ✅ | ❌ | ✅ |

---

## Quick Start

```bash
# One-line setup
curl -sSL https://raw.githubusercontent.com/AIwork4me/open-llm-wiki/main/setup.sh | bash

# Or with a custom directory
curl -sSL https://raw.githubusercontent.com/AIwork4me/open-llm-wiki/main/setup.sh | bash -s my-wiki
```

This creates your wiki structure, copies templates, and initializes state files. Then:

```bash
# Drop a paper and ingest it
cp ~/papers/attention.pdf my-llm-wiki/raw/
# Tell your agent: "Ingest this paper: my-llm-wiki/raw/attention.pdf"

# Open in Obsidian
open my-llm-wiki/
```

**Prerequisites**: An AI agent that can spawn sub-agents (we use [OpenClaw](https://github.com/openclaw/openclaw) + glm-5.1, but the concepts are portable).

See [QUICKSTART.md](QUICKSTART.md) for the full guide.

---

## What's Included

```
open-llm-wiki/
├── setup.sh                  ← One-line install
├── SCHEMA.md                 ← Wiki data structure
├── skills/
│   ├── wiki-ingest/          ← Paper → wiki pipeline (10 steps)
│   ├── query-writeback/      ← Question → wiki growth (6 steps)
│   └── wiki-lint/            ← Health check (5 dimensions)
├── templates/                ← Page templates
├── examples/
│   ├── deepseek-v4-sample.md ← Real source page example
│   └── minimal-vault/        ← Complete minimal wiki you can run
└── assets/                   ← Diagrams and screenshots
```

---

## Battle-Tested

Built and validated through ingesting **23 DeepSeek research papers** (Jan 2024 – Jan 2026):

| Metric | Value |
|--------|-------|
| Papers ingested | 23 |
| Source pages (stable) | 23 |
| Concept pages | 11 |
| First-pass QA rate | 31% → ~70% after "hard numbers first" rule |
| Critical misattributions caught | 1 (Figure vs Table data extraction) |
| Sub-agent reliability (glm-5.1) | 4/4 = 100% |

Coverage: architecture evolution (DeepSeek LLM → V4), reasoning (R1, GRPO), multimodal (VL, Janus family), specialized (Math, OCR, Prover).

See [SHOWCASE.md](SHOWCASE.md) for the full output and [EXAMPLES.md](EXAMPLES.md) for every mistake we made.

---

## Design Principles

1. **Sources are input, Concepts are the wiki** — papers feed concepts, not the other way around
2. **LLMs cannot self-evaluate** — QA and contradiction detection use independent sub-agents, always
3. **Queries grow the wiki** — good synthesis gets written back, not lost in chat
4. **Contradictions are marked, never overwritten** — `⚠️ [CONTRADICTION]` preserves both sides
5. **Hard numbers are the backbone** — "competitive results" is useless; exact benchmarks are knowledge

---

## Acknowledgments

- **[Andrej Karpathy](https://twitter.com/karpathy)** — the [LLM Wiki concept](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) that started it all
- **[OpenClaw](https://github.com/openclaw/openclaw)** — the agent platform powering independent QA
- **DeepSeek** — the 23 papers that served as our test suite

## License

MIT
