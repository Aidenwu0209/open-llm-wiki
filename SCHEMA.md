# SCHEMA.md — LLM Wiki 执行协议

> 最小协议，按需演化。修改此文件前先读 `log.md` 了解变更历史。

## 1. 目录结构

```
my-llm-wiki/              ← vault 根（当前工作目录）
├── raw/                   ← 不可变事实层（原始资料只读存档）
├── concepts/              ← 概念页（wiki 核心，按概念组织）
├── sources/               ← 论文理解页（一篇论文一个页面）
├── drafts/                ← 草稿（未通过 QA 的内容）
├── qa-reports/            ← QA 审计记录（append-only，不可篡改）
├── log-archive/           ← 归档日志（按月，log.md 超 30 天的条目）
├── templates/             ← 页面模板
├── _state/                ← 内部状态（id-counter 等）
├── SCHEMA.md              ← 本文件
├── README.md              ← vault 说明
├── index.md               ← 按概念组织的导航
├── log.md                 ← 操作审计日志（近 30 天）
└── (已有文件不动)         ← AGENTS/SOUL/TOOLS/USER/MEMORY 等
```

## 2. 页面类型

| 类型 | 目录 | 说明 |
|------|------|------|
| **concept** | `concepts/` | 按概念组织的 wiki 页面，一个概念一个页面，持续积累多个 source 的理解 |
| **source** | `sources/` | 一篇论文的理解笔记，有 frontmatter（id, status, tags） |
| **draft** | `drafts/` | 编写中或 QA 未通过的内容 |
| **raw** | `raw/` | 原始资料，不可修改 |

**核心理念**：论文只是 source，概念才是 wiki 的节点。一个 source 的 ingest 可能更新 3-5 个 concept 页。

## 3. Frontmatter 规范（entry）

```yaml
---
id: LLM-NNNN          # 唯一 ID，从 _state/id-counter.md 分配
title: 条目标题
status: draft|stable  # draft=未QA / stable=已通过独立QA(≥7.0)
created: YYYY-MM-DD
updated: YYYY-MM-DD
source: 来源描述       # 人可读，如 "Karpathy LLM Wiki" 或论文标题
tags: [tag1, tag2]     # 最多5个，用-分隔的小写词
---
```

## 4. ID 分配

- 前缀固定 `LLM-`
- 编号从 `_state/id-counter.md` 读取，分配后立即递增
- 格式：`LLM-0001`，4位零填充

## 5. 生命周期

### Source 页（sources/）
```
drafts/LLM-XXXX.md          ← 创建时放这里，status: draft
    ↓ 独立子代理 QA（≥7.0）
    ↓ 移动到 sources/LLM-XXXX.md，status 改为 stable
sources/LLM-XXXX.md         ← 正式 source 页
```

### Concept 页（concepts/）
Concept 页不需要 QA——它们是理解积累，不是事实声明。由 source 页的 ingest 触发创建和更新。风格自由，像给自己写笔记。

**晋升门槛**（缺一不可）：
1. 独立上下文子代理执行 QA（不能自评）
2. 综合评分 ≥ 7.0
3. QA 报告已存档到 `qa-reports/`
4. `status` 字段更新为 `stable`

**降级**：如果后续发现错误，将条目从 `entries/` 移回 `drafts/`，status 改回 `draft`。

## 6. QA 规则

- **独立执行**：QA 必须由独立上下文的子代理（sessions_spawn）完成
- **评分维度**（0-10）：
  - 准确性（事实是否正确）
  - 完整性（是否遗漏关键信息）
  - 压缩性（是否有冗余/废话）
  - 可追溯性（来源是否清晰）
- **综合分** = 四项均值，≥ 7.0 通过
- **QA 报告**格式（append-only）：

```markdown
# QA Report: LLM-XXXX
- date: YYYY-MM-DD
- reviewer: 子代理标识
- 准确性: X/10
- 完整性: X/10
- 压缩性: X/10
- 可追溯性: X/10
- 综合: X.X/10
- verdict: PASS|FAIL
- issues: [问题描述，无则为空]
```

- 评分 < 7.0 → 修正后重跑，最多3轮
- QA 报告只允许 append，不允许修改已有内容

## 7. QA 与 self_check 的区分

- **self_check**：编写者在同一 session 内做的初步检查（发现明显错误、格式问题）
- **QA（independent）**：独立子代理的正式评审（有评分门槛，存档）
- self_check 不能代替 QA。status 只有经过独立 QA 后才能从 `draft` 变为 `stable`

## 8. Ingest 流程

1. 原始资料放入 `raw/`（不修改原始内容）
2. 在 `drafts/` 创建 source 页，status: draft
3. 执行 self_check（同 session，快速扫错）
4. **spawn 独立子代理执行 QA**（大模型自评不可信）
5. QA 通过 → promote 到 `sources/`
6. **更新 3-5 个相关 concept 页**（这是关键步骤，不是可选的）
7. 如果 concept 页不存在，创建新的
8. 更新 `index.md`
9. **spawn 独立子代理执行矛盾检测**（检查新 source 与已有 concept 页的冲突）
10. 如果发现矛盾 → 用 `⚠️ [CONTRADICTION YYYY-MM-DD]` 标注，不静默覆盖
11. 记录操作到 `log.md`
12. **每 10 次 ingest 触发 concept 修订**（独立子代理 review，防止事实堆砌）

**核心原则**：
- 一个 source 的 ingest 应该 touch 多个 concept 页。如果只写了 source 页没有更新任何 concept 页，这次 ingest 不算完成。
- **大模型自评不可信**：QA 和矛盾检测都必须由独立子代理执行，不能用主 session 自检。

## 9. Lint 规则

- 每个 `sources/` 下的条目必须有对应的 `qa-reports/` 文件
- `sources/` 下的条目 status 必须为 `stable`
- `drafts/` 下的条目 status 必须为 `draft`
- frontmatter 必须包含 id、title、status、created、updated
- ID 不得重复
- 每个 concept 页应至少引用 2 个 source（孤立概念页需要检查是否该合并）

## 10. log.md 规范

每条操作记录一行，格式：
```
[YYYY-MM-DD HH:MM] action | target | agent | note
```
action: create / edit / promote / demote / lint / qa / concept-update / query-writeback / contradiction-check / concept-revision
agent: 操作执行者标识

### Log 归档

- `log.md` 只保留**近 30 天**的记录
- 超过 30 天的条目按月归档到 `log-archive/YYYY-MM.md`
- Lint Skill 自动执行归档（每天检查）
- 归档文件 append-only，不修改

## 11. 查询与导航

- `index.md` 按**概念**组织（不是按论文编号）
- 概念页之间用 `[[concept-name]]` 链接
- Source 页之间用 `[[LLM-NNNN|显示文本]]` 链接
- 概念页链接到 source 页，source 页也链接到相关概念页

## 12. Query 回写（query → wiki compounding）

**核心理念**：wiki 不只在 ingest 时增长。好的问答、比较、分析也应该回写 wiki，让知识复利积累。

### 触发条件
以下类型的问答产出**应该**回写 wiki：

1. **跨 source 比较分析**（如 "LLaMA 和 GPT-3 的训练策略有什么不同？"）
2. **深度解释**（如 "为什么 Decoder-only 赢了而不是 Encoder-Decoder？"）
3. **时间线/演进梳理**（如 "位置编码是怎么演化的？"）
4. **概念间关系分析**（如 "MoE 和 dense 模型的效率对比"）

### 不需要回写的
- 简单事实查询（"BERT 有几层？"）
- 一次性的、不含新综合的问题
- 用户明确不想要的

### 回写方式
- **更新现有 concept 页**：在相关概念页中追加新的段落或洞察
- **创建新 concept 页**：如果问答揭示了值得独立记录的新概念
- **格式**：标注 `[query-derived, YYYY-MM-DD]`，区分 ingest 来源和问答来源
- **记录到 log.md**：action 用 `query-writeback`

### 判断标准
> 这个回答如果消失了，下次再问同样的问题，需要重新从 source 里推导吗？如果是 → 值得回写。

## 13. 写回（sync to 飞书）

- **仅在 stable source 页上执行**
- 飞书知识库为只读镜像（space_id: 7627999127539829723）
- sync 前确认 QA 报告存在
- sync 失败不降级本地条目

## 14. 写作风格

### Source 页（sources/）
理解笔记，不是论文摘要。1-3KB。用自己的话写"这篇论文的本质贡献"。

### Concept 页（concepts/）
给自己写的理解积累。风格自由。关键是：
- **积累性**：每读一篇新论文，相关概念页就长一点
- **有态度**：可以写判断、预测、质疑，不只是事实陈述
- **简洁**：不废话，像给未来的自己写备忘录
- **带来源**：每个关键断言链接到 source 页

**反模式**：
- ❌ 逐段翻译原文
- ❌ 百科全书式第三人称
- ❌ 写完不再更新

## 15. 概念页的生命周期

概念页是**活的**，没有 draft/stable 状态。它们随 ingest 持续生长：

- **创建**：ingest 新 source 时发现需要新概念页
- **更新**：后续 ingest 带来新视角、新数据、新链接
- **分裂**：概念页太长时，拆成更细粒度的概念
- **合并**：两个概念页高度重叠时合并

概念页不需要 QA——它们代表"我当前的理解"，不是事实声明。但如果 source 页的 QA 发现了错误，相关概念页也应同步修正。

### 概念页修订（每 10 次 ingest）

概念页不能只做追加——会变成事实堆砌。每 10 次 ingest 后：

1. **独立子代理 review** 所有 concept 页（不是主 session 自检）
2. 检查项：结构是否清晰？有无过时断言？有无重复内容？
3. **修订而非重写**——保留有价值内容，删减过时的，重组混乱的
4. 修订报告存入 `qa-reports/concept-revision-{LLM-NNNN}.md`

修订周期：LLM-0050, LLM-0060, LLM-0070...（每 10 个 ID 触发一次）

