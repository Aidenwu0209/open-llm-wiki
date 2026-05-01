# PHILOSOPHY.md — Why This Exists

## The Original Idea

On April 4, 2026, Andrej Karpathy published [a gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) titled "LLM Wiki" — a vision for how AI agents should maintain personal knowledge bases.

His key insight:

> "Good answers can be filed back into the wiki as new pages. A comparison you asked for, an analysis, a connection you discovered — these are valuable and shouldn't disappear into chat history. This way your explorations compound in the knowledge base just like ingested sources do."

This resonated because it described exactly what was missing from every note-taking system: **compounding**.

## Why Traditional Note-Taking Fails for Researchers

### The Write-Only Problem

You read a paper, highlight key passages, maybe write a summary. Six months later, you vaguely remember reading something relevant but can't find it. Your notes became a write-only archive.

### The Isolation Problem

Each paper's notes exist in isolation. Paper A says "X achieves 92%". Paper B says "Y achieves 94%". But nowhere does it say "Y improved on X by 2 points" — because that synthesis only exists in your head, temporarily.

### The Stale Problem

Your understanding evolves. What you wrote 6 months ago might be wrong now. But there's no mechanism to flag contradictions or update old notes with new evidence.

## What Karpathy Got Right

1. **Sources feed concepts** — papers are input, but the wiki's nodes are concepts, not papers
2. **Queries grow the wiki** — good questions produce reusable synthesis
3. **Contradictions are features** — noting where new data challenges old claims is valuable
4. **Agents do the heavy lifting** — parsing, QA, cross-referencing should be automated

## What We Had to Learn the Hard Way

Karpathy's gist was a vision, not a blueprint. Here's what 23 papers taught us:

### LLMs Cannot Self-Evaluate

The single most important lesson. **Every** initial QA failure (9/13 papers) was something the writing agent "checked" but didn't actually catch. When you write something, you can't see its flaws — this is true for humans and doubly true for LLMs.

**Solution**: Independent sub-agent QA. Separate context, separate session, no access to the writing process.

### Hard Numbers Are the Backbone

"Competitive results" = useless. "MiniF2F-test: 88.9%, PutnamBench: 47/658" = knowledge. 100% of QA failures were missing or vague numbers.

**Solution**: Write the "Key Data" section first, before anything else.

### Figures Lie, Tables Don't

V3.2 paper had Figure 1 with unlabeled numbers. We attributed 4 out of 5 data points to wrong benchmarks. Tables have labels. Figures have artistic license.

**Solution**: Always verify data against Table text, never against unlabeled Figure elements.

### Contradictions Are Invisible Without Active Detection

After ingesting 15 papers, some concept pages had claims that directly contradicted newer papers. Nobody noticed because there was no mechanism to check.

**Solution**: Independent contradiction detection sub-agent after every promote.

### Concept Pages Become Dumps Without Pruning

After 20+ papers, concept pages became chronological append logs — fact dumps without synthesis.

**Solution**: Periodic concept revision (every 10 ingests) by an independent sub-agent.

## The Compound Effect

This is the real payoff. After 23 papers:

- **Asking "how did DeepSeek's MoE evolve?"** produces a 12-row innovation table spanning 2 years, synthesized from 8 source pages, something no single paper contains
- **Querying "what's the relationship between GRPO and PPO?"** produces a comparison that gets written back to the `reasoning` concept page, available for every future query
- **Ingesting paper #23** automatically checks for contradictions with papers #1-22

Each interaction makes the next one better. That's compounding.

## Design Tradeoffs

### Serial > Parallel

We ingest one paper at a time. This is slower but:
- Error isolation (one failure doesn't cascade)
- Stable context (no rate limit surprises)
- Sequential learning (each ingest benefits from the last)

### Caution > Speed

QA failures require manual fixes. Contradictions get marked, not overwritten. This is slower but:
- Trust in the knowledge base (every number is verified)
- No silent corruption
- Errors are caught early

### Structure > Freedom

Fixed frontmatter, required sections, strict QA criteria. This is more restrictive but:
- Machine-checkable (lint can verify compliance)
- Consistent quality
- Clear lifecycle (draft → stable)

## Who Is This For?

Anyone who:
- Reads research papers and wants to actually remember them
- Needs to track evolving topics (not just snapshot understanding)
- Wants their AI agent to be a research partner, not just a summarizer
- Believes knowledge should compound, not just accumulate

## The Aspiration

Karpathy described a vision. We built the machinery. The aspiration is that others take this framework, adapt it to their domains (not just LLM research — biology, economics, law, anything), and build knowledge bases that compound with every interaction.

The best wiki is the one you actually use. This framework tries to make using it effortless.
