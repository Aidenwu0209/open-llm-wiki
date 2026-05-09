---
type: concept
concept_id: attention-mechanisms
id: attention-mechanisms
title: "Attention Mechanisms"
status: active
created: 2026-05-01
updated: 2026-05-10
updated_at: 2026-05-10
supporting_claims: 5
contradicted_claims: 0
stale_claims: 1
related_concepts: []
---
# Attention Mechanisms

## Definition

Attention lets a model weight relevant tokens directly instead of relying only
on sequential recurrence.

## Core Intuition

In the Transformer, self-attention replaced recurrent sequence processing as
the main computation path. Each token gets a direct path to every other token,
with learned weights determining relevance.

## Why It Matters

Attention is central to modern language models because it gives each token a
direct path to other relevant tokens. [[LLM-0001]]

## Key Mechanisms

- Transformer did not invent attention, but it showed that a network built
  primarily from multi-head self-attention could outperform strong recurrent
  and convolutional sequence models on machine translation. [[LLM-0001]]
- Multi-head attention is useful because different heads can attend to different
  relationship patterns in parallel. [[LLM-0001]]
- Positional encoding is required because pure self-attention does not encode
  token order by itself. [[LLM-0001]]

## Supporting Evidence

<!-- open-llm-wiki:semantic-claims:start -->
| Source | Type | Status | Claim | Evidence |
| --- | --- | --- | --- | --- |
| [[LLM-0001]] | contribution | supported | The paper introduced the Transformer, a sequence transduction architecture based on multi-head self-attention that reached 27.3 BLEU on WMT 2014 English-German  | sources/LLM-0001.md#One-Sentence Contribution |
| [[LLM-0001]] | metric | supported | WMT 2014 EN-DE BLEU, big: 28.4 | sources/LLM-0001.md#Key Data |
| [[LLM-0001]] | metric | supported | WMT 2014 EN-DE BLEU, base: 27.3 | sources/LLM-0001.md#Key Data |
<!-- open-llm-wiki:semantic-claims:end -->

## Revision Notes

- This section is generated from `claims/claims.jsonl` and excludes claims that require second-pass scientific review unless they are marked `science_review: approved`.
- Claim counts: 5 supported, 0 contested, 1 needs-review.
- Held for review in this concept: 3.
- Treat cross-source comparisons as inference unless units, baselines, and evaluation protocol are aligned.

## Counter-examples & Controversies

- None detected yet. Rerun contradiction scanning after adding more sources.
- 1 claim needs review (Base model layers metric).

## Related Methods & Concepts

- none yet

## Representative Sources

- [[LLM-0001|Attention Is All You Need]] - Transformer paper introducing the
  attention-only sequence modeling architecture.

## Open Questions

- Which later positional encoding variants preserve the most long-context
  performance?
- When does sparse or linear attention preserve enough quality to replace full
  attention?
