---
name: query-writeback
description: Query-driven wiki growth engine. When users ask about wiki content, auto-assess coverage, supplement missing ingest, and writeback valuable synthesis. The knowledge base grows with every query.
version: 0.2.0
---

# Query Writeback

> Karpathy: "Good answers can be filed back into the wiki as new pages. A comparison you asked for, an analysis, a connection you discovered — these are valuable and shouldn't disappear into chat history."

## When to Use

When the user asks questions about wiki content that require **cross-source synthesis**:
- "What's the relationship between X and Y?"
- "How did X evolve over time?"
- "Compare A, B, and C on X"
- Any question requiring synthesis across multiple source/concept pages

**Do NOT trigger for**: simple factual lookups ("What's V3's param count?"), casual chat, non-wiki topics.

---

## Pipeline

### Step 1: Parse Query

Extract knowledge requirements:
- Concepts needed
- Entities referenced
- Relationships to trace
- Expected output type (comparison table / timeline / analysis)

### Step 2: Search Wiki

Priority order:
1. **index.md** — quick page discovery
2. **concept pages** — topic-level synthesis
3. **source pages** — detailed evidence
4. **log.md** — recent updates (optional)

### Step 3: Coverage Assessment

| Verdict | Condition | Action |
|---------|-----------|--------|
| FULL | Wiki has a direct, sufficient answer | → Step 4 |
| PARTIAL | Related pages exist but incomplete | → Supplement → Step 4 |
| NONE | Wiki has no relevant content | → Suggest ingest → Step 4 (best effort) |

**Partial coverage**: check if raw/ has un-ingested files → trigger ingest pipeline. Record gaps for future.

### Step 4: Answer + Writeback Decision

**Answer**: synthesize from wiki, cite `[[LLM-XXXX]]` / `[[concept-name]]`.

**Writeback if ANY is true**:

| Condition | Reason |
|-----------|--------|
| Answer cites **3+ source pages** | Cross-source synthesis not in wiki |
| Answer has **comparison table or timeline** | Structured analysis, high reuse value |
| Question is **likely to recur** | Writeback makes future queries instant |
| Answer reveals **cross-concept relationships** | "Connections" are wiki's highest-value content |

### Step 5: Self-Check Before Writeback ⚠️

**Synthesis errors are the most insidious** — each fact individually correct, but the relationship wrong.

Before writing, check every **relational claim** (X evolved from Y, X improved on Y, X replaced Y):

1. Does the source page **explicitly state** this relationship? → ✅ Write as fact
2. Is this relationship **implied but not stated**? → ⚠️ Write as "推断" (inference), not fact
3. Am I **guessing** based on chronological proximity? → ❌ Don't write, flag for future verification

**Example of synthesis error**:
- Source A: "V2 uses MLA" ✅
- Source B: "V3 uses aux-loss-free" ✅
- Bad synthesis: "V3's MoE evolved from V2's MLA" ❌ (MLA is attention, MoE is routing — different axes)

### Step 6: Execute Writeback

**Create/update concept page**:

```yaml
---
id: concept-xxx
title: "Descriptive title"
status: stable
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [[LLM-XXXX]], [[LLM-YYYY]]
writeback: true
query: "Original question that triggered this"
---
```

**Sync the triad**:
1. **index.md** — add new page (if new concept)
2. **Related concept pages** — add bidirectional links
3. **log.md** — record: `[YYYY-MM-DD HH:MM] query-writeback | concepts/xxx.md | 太宗 | query: "..."`

**No independent QA needed** — writeback synthesizes from verified sources, not introducing new knowledge. But the self-check in Step 5 is mandatory.

---

## Rules

1. **Writeback is optional** — don't force it. Single-source detail queries don't need it.
2. **Every claim must cite a source** — `[[LLM-XXXX]]` traceability required.
3. **Merge into existing pages first** — don't create new concepts if one already covers the topic.
4. **Mark writebacks** — `writeback: true` + `query: "original question"` in frontmatter.
5. **Don't block the answer** — writeback happens after answering, async.
6. **No duplication** — check existing concepts before writing.
7. **Self-check relational claims** — Step 5 is mandatory, not optional.

---

## Pipeline Relationships

| Pipeline | Trigger | Output | QA |
|----------|---------|--------|----|
| **Ingest** | User provides new source | source page + concept updates | YES (independent QA) |
| **Query Writeback** | User queries wiki content | concept page (synthesis) | SELF-CHECK (Step 5) |
| **Lint** | Cron / manual | Fixes / cleanup | NO (corrections) |

---

## Reference

- Karpathy, "LLM Wiki" (2026.04.04): https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Core quote: "Good answers can be filed back into the wiki as new pages. This way your explorations compound in the knowledge base just like ingested sources do."
