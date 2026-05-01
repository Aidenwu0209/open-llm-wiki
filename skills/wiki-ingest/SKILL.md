---
name: wiki-ingest
description: Ingest a research paper or document into the LLM Wiki. Full pipeline - parse PDF, write source page, self-check, QA, fix, promote, update concepts/index/log. One paper at a time.
version: 0.2.0
---

# Wiki Ingest Pipeline

Ingest a source document (PDF/paper) into the wiki. Serial, one at a time, with mandatory independent QA.

## When to Use

When the user wants to add a new paper/document to the wiki:
- "ingest this paper"
- "add XXX to the wiki"
- Drops a PDF into raw/ and asks to process it
- Points to a URL or arXiv paper

**One paper at a time** — no parallel ingestion. Trade speed for stability and error isolation.

---

## Pipeline Overview

```
Parse → Draft → Self-Check → QA → Fix → Promote → Update Network → Contradiction Check → Log
```

Total time: ~12 min/paper (QA + contradiction check are the two sub-agent calls).

---

## Step 1: Parse

### File Size Decision

| File size | Parser | Reason |
|-----------|--------|--------|
| < 2 MB | PaddleOCR cloud API | Better layout understanding |
| ≥ 2 MB | PyMuPDF (`fitz`) | PaddleOCR unreliable for large files (timeout risk) |

### PyMuPDF Script (default)

```python
import fitz
doc = fitz.open('path/to/file.pdf')
texts = [page.get_text() for page in doc]
all_text = '\n\n'.join(texts)
with open('raw/{name}_fulltext.txt', 'w', encoding='utf-8') as f:
    f.write(all_text)
print(f'Pages: {len(doc)}, Chars: {len(all_text)}', flush=True)
```

### Output

- Save to `raw/{papername}_fulltext.txt` (PyMuPDF) or `raw/{papername}_paddleocr_full.md` (PaddleOCR)
- Record pages and character count

---

## Step 2: Allocate ID

Read `_state/id-counter.md`, increment by 1, write back.

---

## Step 3: Write Draft

### Frontmatter (required)

```yaml
---
id: LLM-NNNN
title: "Full Paper Title"
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
source: "Authors, Title, arXiv:XXXX.XXXXX, Year"
tags: [relevant, tags]
---
```

### Section Structure (all required)

| Section | Purpose |
|---------|---------|
| H1 title | Paper name |
| 一句话 | Key contribution + numbers |
| 核心问题/核心思路 | What and why |
| **关键数据** | **Hard numbers: benchmarks, params, training scale** |
| 进化位置 | Where in timeline, ASCII tree |
| 我的理解 | Personal insight |
| 关联 | Wiki-links |

### ⚠️ CRITICAL RULE: Hard Numbers First

**The #1 reason QA fails: missing hard numbers.**

Before writing any other section, extract from raw text:
- Benchmark scores with exact numbers (not "competitive")
- Parameter counts (total AND active)
- Training data scale (tokens, images, etc.)
- Comparison with baselines (specify WHICH baseline)
- Key architectural details

**Write the 关键数据 section FIRST with specific data.**

### Writing Style

- Karpathy style: conversational, opinionated, grounded
- Not academic prose — explain to a smart friend
- Target: 1.0–2.0 KB per paper

---

## Step 4: Self-Check

Before spawning QA, verify yourself:

1. **Hard numbers correct?** Grep raw text to confirm each number
2. **Comparison baseline correct?** "+7.2" — vs what? Specify clearly
3. **Evolution tree consistent?** Check chronological order
4. **Wiki-links valid?** Each `[[LLM-XXXX]]` should exist

**Common catches**:
- Figure data often unlabeled → verify in Table text
- Abstract claims may differ from Table data → prefer Tables
- "Comprehensive" model names need specific variant attribution

---

## Step 5: QA — Independent Sub-Agent ⚠️

### Core Principle

**大模型自评不可信。QA 必须由独立上下文的子代理执行。**

不能用同一个 session 评估自己写的条目。QA 子代理必须：
- 独立的上下文（看不到主会话历史）
- 独立的模型调用
- 输出写入独立文件

### Spawn Configuration

```
model: glm-5.1
mode: run
runTimeoutSeconds: 180
```

### QA Task Template

```
你是一个独立的 QA 审查员。请审查 source 页草稿 LLM-NNNN（{title}）。

## 审查标准
4 维度打分（0-10）：准确性、完整性、压缩性、可追溯性。综合=均值，≥7.0 通过。
特别关注：关键数据段必须有可验证的硬数字。

## 审查方法
1. 用 read 工具读取草稿：{draft_path}
2. 用 read 工具读取原文：{raw_path}（只读前 300 行）
3. 逐条核对
4. 用 write 工具写 QA 报告到：{qa_report_path}

QA 报告格式同前。严格审查。务必用 write 工具将报告写入文件。
```

### QA Report Format

```markdown
# QA Report: LLM-NNNN
- date: YYYY-MM-DD
- reviewer: qa-subagent-v1
- 准确性: X/10
- 完整性: X/10
- 压缩性: X/10
- 可追溯性: X/10
- 综合: X.X/10
- verdict: PASS|FAIL
- issues: [description]
```

### QA Decision

| Result | Action |
|--------|--------|
| ≥ 7.0 PASS | → Step 7 (Promote) |
| < 7.0 FAIL | → Step 6 (Fix) |

**Only re-QA if first QA timed out without producing a report.** Fixed drafts promote without re-QA.

---

## Step 6: Fix (if QA FAIL)

1. Read QA report — identify specific issues
2. Grep raw text for correct data
3. Fix the draft
4. Promote (no re-QA)

**Common fixes**:
- Add missing benchmark numbers → grep raw text, add to 关键数据
- Fix comparison baseline ambiguity → clarify "vs X" or "vs Y"
- Fix parameter count errors → verify in Table text
- Add missing architectural details → extract from method section

---

## Step 7: Promote

1. Edit: `status: draft` → `status: stable`
2. Move: `Move-Item "drafts/LLM-NNNN.md" "sources/LLM-NNNN.md"`

---

## Step 8: Update Network

Three mandatory updates after every promote:

### 8a. Concept Pages

For each relevant concept page:
1. Innovation table: add row with bottleneck + result
2. Source list: add `- [[LLM-NNNN|Title]]：one-line description`
3. Timeline/rhythm: add entry if relevant

### 8b. Index

- Source entry: `| [[LLM-NNNN]] | Title | tag1, tag2 |`
- Update concept range if needed

### 8c. Log

Append to `log.md`: `[YYYY-MM-DD HH:MM] action | file | who | description`

---

## Step 9: Contradiction Check — Independent Sub-Agent ⚠️

### Why This Exists

Karpathy: *"Noting where new data contradicts old claims, strengthening or challenging the evolving synthesis."*

**大模型自评不可信。矛盾检测也必须由独立子代理执行。**

主 session 刚写了 source 页、刚更新了 concept 页——它不可能客观地检查自己写的有没有矛盾。

### Spawn Configuration

```
model: glm-5.1
mode: run
runTimeoutSeconds: 180
```

### Task Template

```
你是一个独立的矛盾检测员。一篇新论文 LLM-NNNN（{title}）刚刚入库。

## 任务
检查新论文的发现是否与已有 concept 页产生矛盾。

## 方法
1. 用 read 工具读取新 source 页：{source_path}
2. 用 read 工具读取相关 concept 页：{concept_paths}
3. 逐条对比：新论文的每个关键断言，是否与已有断言冲突？
4. 输出检测报告

## 检测重点
- 数值矛盾（旧说 X%，新说 Y%）
- 方法论矛盾（旧说方法 A 有效，新说方法 A 有缺陷）
- 结论矛盾（旧说方向 X 是未来，新说方向 X 已过时）
- 时间性矛盾（旧断言基于早期数据，新数据推翻了它）

## 输出格式（写入文件）
# Contradiction Report: LLM-NNNN
- date: YYYY-MM-DD
- new_source: {source_id}
- contradictions_found: 0|N
- items:
  - [如果有矛盾] concept 页路径 | 旧断言 | 新证据 | 建议（修订/标注/保留）
  - [如果无矛盾] "No contradictions detected"
- concept_revision_needed: YES|NO

## 关键
- 不要为了找矛盾而找矛盾——数据自然演进不算矛盾
- 只有同一指标/同一结论的明确冲突才算矛盾
- 务必用 write 工具将报告写入文件：{report_path}
```

### If Contradictions Found

1. Read the contradiction report
2. **Do NOT silently overwrite** — mark with `⚠️ [CONTRADICTION YYYY-MM-DD]` in the concept page
3. Add the new evidence alongside the old claim
4. Notify chairman if the contradiction affects a core thesis

### Report Storage

Save to `qa-reports/LLM-NNNN-contradiction.md` (append-only, same rules as QA reports).

---

## Step 10: Concept Revision (Every 10 Ingests)

### Why This Exists

Concept pages 只做追加会变成"事实堆砌"。定期 review 让 concept 页保持"活的认知"。

### Trigger

After every **10th promote** (LLM-0050, LLM-0060, LLM-0070, ...), spawn a concept revision sub-agent.

### Task Template

```
你是一个独立的知识审校员。已有 N 篇论文入库，concept 页可能需要修订。

## 任务
Review 每个 concept 页，检查是否有需要修订的内容。

## 方法
1. 用 read 工具读取 index.md，获取所有 concept 页列表
2. 逐个读取 concept 页
3. 对每个 concept 页评估：
   - 结构是否清晰？（还是变成了事实堆砌？）
   - 有无过时断言需要更新？
   - 有无重复内容需要合并？
   - 段落之间的逻辑是否连贯？
4. 输出修订报告

## 输出（写入文件）
# Concept Revision Report
- date: YYYY-MM-DD
- after_ingest: LLM-NNNN
- pages_reviewed: N
- revisions_needed: 
  - concept 页路径 | 问题 | 建议操作
- summary: 一段话总结

## 关键
- 不是重写，是修订——保留有价值的内容，删减过时的，重组混乱的
- 务必用 write 工具将报告写入文件
```

### Execution

Read the revision report, then execute the suggested revisions. This is one of the few cases where concept pages get **revised** rather than just appended to.

---

## Lessons Learned

| Lesson | Source | Fix |
|--------|--------|-----|
| Hard numbers = QA PASS | 9/13 initial FAILs | Write key data FIRST |
| Figure data misattribution | V3.2: 4/5 numbers wrong | Verify in Tables, not Figures |
| PaddleOCR hangs >2MB | VL 5.8MB hung 20min | Size-based parser selection |
| Sub-agent status ≠ completion | claude-sonnet-4: 0 tokens | Use glm-5.1, verify output file |
| Abstract ≠ Table | Engram: +3.4 vs +3.0 | Prefer Table data |
| Baseline ambiguity | mHC: +7.2 vs which? | Always specify comparison target |
| **Self-evaluation unreliable** | Cherny training C13 | **QA + contradiction check = independent sub-agents** |
| **Concept pages become dumps** | 23 papers, concepts grew organically | Periodic revision every 10 ingests |
| **Contradictions are invisible** | No mechanism to detect conflicts | Step 9 contradiction check sub-agent |

---

## Reference

- Wiki schema: `schema.md`
- QA reports: `qa-reports/LLM-NNNN.md`
- Contradiction reports: `qa-reports/LLM-NNNN-contradiction.md`
- ID counter: `_state/id-counter.md`
- Source pages: `sources/LLM-NNNN.md`
- Draft pages: `drafts/LLM-NNNN.md`
- Raw extractions: `raw/{name}_fulltext.txt`
