# EXAMPLES.md — Anti-Patterns from 23 Papers

Real mistakes we made, real fixes we applied. Each example shows what went wrong, why it matters, and the lesson.

---

## 1. Missing Hard Numbers → QA FAIL

**What happened**: 9 out of 13 papers failed initial QA. Every single failure had the same root cause: the "Key Data" section was missing specific numbers.

**Example**:
```
❌ "DeepSeek-V3 achieves competitive results across benchmarks"
✅ "DeepSeek-V3: 671B total params (37B active), 14.8T training tokens.
    MMLU: 88.5, HumanEval: 82.6, MATH-500: 90.2"
```

**Why it matters**: Without hard numbers, a source page is just a summary. The numbers are what make it verifiable and useful for future queries.

**Lesson**: Write the "Key Data" section **first**, before any other section. Extract from Tables, not Figures.

---

## 2. Figure vs Table Misattribution

**What happened**: DeepSeek-V3.2's Figure 1 contained unlabeled performance bars. We guessed which benchmark each bar belonged to. 4 out of 5 attributions were wrong.

**Example**:
```
❌ (from Figure 1, unlabeled) "BBH: +7.2 vs HC"
    Actually: +7.2 vs plain baseline, only +2.1 vs HC
✅ (from Table text) "mHC improves BBH by +7.2 over plain baseline,
    +2.1 over HC baseline"
```

**Why it matters**: Wrong numbers are worse than no numbers. They get copied into concept pages, query answers, and eventually become "common knowledge" that's wrong.

**Lesson**: Always verify data against **Table text**. Figures are for visual intuition, not data extraction.

---

## 3. Abstract ≠ Ground Truth

**What happened**: Engram paper's Abstract stated "27B parameters". The actual model has 26.7B total, with the memory module being only 5.7B. The Abstract rounded up and didn't distinguish module size.

**Example**:
```
❌ "Engram uses 27B parameters"
✅ "Engram: 26.7B total parameters, memory module 5.7B,
    based on Qwen2.5-14B backbone"
```

**Why it matters**: The Abstract is a marketing document. Tables contain the actual data.

**Lesson**: When Abstract and Table disagree, trust the Table. Always note which you're using.

---

## 4. Comparison Baseline Ambiguity

**What happened**: mHC paper reported "+7.2 improvement on BBH". We wrote that without specifying what the baseline was. QA flagged it as unverifiable.

**Example**:
```
❌ "mHC improves BBH by +7.2"
✅ "mHC improves BBH by +7.2 over plain baseline (no HC),
    +2.1 over HC baseline"
```

**Why it matters**: "+7.2" sounds impressive, but the baseline matters more than the delta. Cherry-picking baselines is the oldest trick in ML papers.

**Lesson**: Every comparison must specify the exact baseline. "Improvement" without a baseline is meaningless.

---

## 5. Self-Evaluation Unreliable

**What happened**: After writing a source page, the agent "self-checked" it and declared it correct. Independent QA found 3 factual errors, 2 missing numbers, and 1 misattribution.

**Example**: The writing agent checked its own work:
```
Agent: "Self-check complete. All numbers verified. ✅"
QA sub-agent (independent): "Accuracy: 5/10. Missing: training cost, 
    active param count. Wrong: BBH baseline attribution."
```

**Why it matters**: LLMs cannot see their own errors. The process of writing creates blind spots. This is not a model weakness — it's a cognitive limitation that applies to all writers, human or AI.

**Lesson**: QA must use **independent sub-agents** — separate context, separate session, no access to the writing process. "大模型自评不可信" (LLM self-evaluation is untrustworthy) is now Rule #1.

---

## 6. Sub-Agent Status ≠ Completion

**What happened**: Spawned a QA sub-agent using claude-sonnet-4. Status returned "completed". But the output file didn't exist — 0 tokens generated, 0 seconds of runtime.

**Example**:
```
❌ status=completed → assumed done → promoted draft without QA
✅ status=completed → checked file exists → file missing → 
    re-ran with glm-5.1 → got actual QA report
```

**Why it matters**: "completed" is a process status, not a result guarantee. The agent might have crashed, timed out, or hit a model limitation.

**Lesson**: After every sub-agent spawn, verify the output file exists and contains reasonable content. `status=completed` + no file = silent failure.

**Sub-lesson**: claude-sonnet-4 failed silently 3/3 times. glm-5.1 succeeded 4/4 times. Model reliability matters.

---

## 7. Batch Replace Without Semantic Awareness

**What happened**: Batch-updating 20 source pages to fix paper publication dates. Used find-replace to change both `created:` and `updated:` fields. But `created` (paper publication date) and `updated` (last wiki edit date) have different meanings.

**Example**:
```
❌ Both fields changed to "2024-05-07" (arXiv date)
✅ created: "2024-05-07" (when paper was published)
   updated: "2026-05-01" (when we last edited this page)
```

**Why it matters**: Conflating semantic fields silently corrupts data. The wiki's audit trail becomes unreliable.

**Lesson**: Before any batch operation, list every field that will be affected and verify each has the correct semantic meaning.

---

## 8. ArXiv ID Without Verification

**What happened**: DeepSeek-Prover-V2 was recorded with arXiv ID `2504.21852`. Months later, discovered this ID is actually a stellar mapping paper — not Prover-V2 at all. The correct ID is `2504.21801`.

**Why it matters**: Wrong arXiv IDs break traceability. Future readers can't verify claims or find the original paper.

**Lesson**: Every arXiv ID must be verified against the actual paper (title + authors match), not assumed from memory or pattern.

---

## 9. PaddleOCR Cloud API Instability

**What happened**: DeepSeek-VL paper (5.8MB PDF) sent to PaddleOCR cloud API. Hung for 20 minutes with no response. Three smaller papers worked fine.

**Why it matters**: Pipeline reliability depends on understanding tool limitations. "Works for most cases" ≠ "works for all cases".

**Lesson**: Size-based parser selection:
- < 2MB → PaddleOCR (better layout understanding)
- ≥ 2MB → PyMuPDF (reliable, local, no timeout risk)

---

## 10. Concept Pages Becoming Fact Dumps

**What happened**: After 20+ papers, the `deepseek-methodology` concept page had become a chronological append log — 15 sections, each just adding new data without synthesis.

**Why it matters**: Concept pages are supposed to be "evolving understanding", not "things we read in order". Without pruning, they become useless.

**Lesson**: Every 10 ingests, run an independent concept revision. Restructure, prune outdated claims, merge duplicates. Concept pages need editors, not just writers.

---

## Summary Table

| Anti-Pattern | Root Cause | Fix |
|-------------|-----------|-----|
| Missing numbers | Lazy writing | Key Data section FIRST |
| Figure misattribution | Unlabeled data | Verify against Tables |
| Abstract over-trust | Marketing ≠ data | Trust Tables over Abstract |
| Baseline ambiguity | Imprecise comparison | Always specify baseline |
| Self-evaluation | Cognitive blind spot | Independent QA sub-agent |
| Silent sub-agent failure | Status ≠ result | Verify output file exists |
| Batch semantic error | Undifferentiated replace | List field semantics first |
| Wrong arXiv ID | Unverified assumption | Cross-check title + authors |
| API instability | One-size-fits-all | Size-based parser selection |
| Concept dump growth | No pruning | Periodic revision (every 10) |

---

> "These mistakes aren't unique to AI agents. They're the same mistakes any research assistant would make — forgetting to write down numbers, trusting the abstract, assuming instead of verifying. The difference is that with AI agents, we can build systematic safeguards. With humans, we just say 'be more careful next time'."
