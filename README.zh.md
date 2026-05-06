# open-llm-wiki

[![GitHub Actions: Validate](https://img.shields.io/github/actions/workflow/status/AIwork4me/open-llm-wiki/validate.yml?branch=main&label=GitHub%20Actions%3A%20Validate)](https://github.com/AIwork4me/open-llm-wiki/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/github/license/AIwork4me/open-llm-wiki)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![uv](https://img.shields.io/badge/env-uv-4B32C3)](https://docs.astral.sh/uv/)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-6B46C1)](skills/)
[![QA Checklist](https://img.shields.io/badge/QA%20Checklist-ready-brightgreen)](Checklist.md)
[![Last Commit](https://img.shields.io/github/last-commit/AIwork4me/open-llm-wiki)](https://github.com/AIwork4me/open-llm-wiki/commits/main)

[English README](README.md) | [快速开始](QUICKSTART.md) | [测评清单](Checklist.md) | [Schema](SCHEMA.md) | [展示](SHOWCASE.md)

**把研究论文变成可审计、可持续自增长的 LLM Wiki。**

open-llm-wiki 是一个面向 Claude Code 的 Skill 套件和项目本地 Python
runtime，可将 PDF 和解析后的 Markdown 转成稳定 source pages、normalized
claim graph、concept pages、科学审稿队列和可复现 QA 报告。

它适合想让个人/团队研究知识库长期增长，同时保留科学审慎边界的人。

| 你会得到 | 为什么重要 |
| --- | --- |
| 证据优先的 source pages | 每条长期笔记都能回到论文、解析文本或 evidence anchor。 |
| 语义自增长 | claims 经过 QA、矛盾检查和 metric 归一化后再进入 concept pages。 |
| 审稿门禁 | 模糊 metric 会进入二级 LLM/人工科学审稿队列，不会直接写入长期 synthesis。 |
| 可迁移 runtime | `uv` 管理本地 `.venv`；vault 自带 `.open-llm-wiki/scripts/` 继续自检。 |

60 秒试跑 runtime：

```bash
git clone https://github.com/AIwork4me/open-llm-wiki.git
cd open-llm-wiki
uv sync --dev --locked
uv run python scripts/wiki_eval.py
bash setup.sh my-llm-wiki
```

灵感来自 [Andrej Karpathy 的 LLM Wiki 构想](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)。

---

## 这个项目解决什么问题

普通论文笔记很容易变成孤立摘要。open-llm-wiki 把论文当作证据，把概念页当作真正会生长的 wiki 节点。每次 ingest 都可以更新多个概念；有价值的跨论文回答也可以在用户批准后写回知识库。

核心质量原则是：**写 source page 的 Agent 不能是唯一审稿人**。稳定条目必须通过独立 QA，并留下审计记录。

## 三个核心 Skill

| Skill | 触发 | 结果 |
| --- | --- | --- |
| `wiki-ingest` | 用户要求加入一篇论文 | 解析文本、草稿页、独立 QA、稳定 source page、概念更新、矛盾报告 |
| `query-writeback` | 用户提出跨 source 的 wiki 问题 | 先给有引用的回答；必要时提出写回计划 |
| `wiki-lint` | 用户或自动化要求健康检查 | 默认只报告；经授权后才执行维护写入 |
| `wiki-grow` runtime | 用户或自动化要求语义自增长 | claim 抽取、语义 QA、矛盾扫描、概念修订、lint |

## Runtime 层

Skill 负责判断和协调；runtime 脚本负责可重复检查：

| Script | 用途 |
| --- | --- |
| `scripts/wiki_init.py` | 初始化个人/团队 vault |
| `scripts/wiki_obsidian_setup.py` | 增加可选 Obsidian profile，合并设置、插件、主题、收件箱和图表目录 |
| `scripts/pdf_corpus_report.py` | 验证批量解析覆盖率、manifest、解析告警和语义命中 |
| `scripts/pdf_corpus_to_markdown.py` | 批量将 PDF 文件夹转成 Markdown，并记录 TSV 审计日志 |
| `scripts/pdf_to_markdown.py` | 通过可配置的 layout parsing API 将 PDF 转成 Markdown |
| `scripts/wiki_ingest_corpus.py` | 将解析后的 Markdown 语料发布为 source/QA/concept 页面 |
| `scripts/wiki_claims.py` | 抽取 normalized claims 到 `claims/claims.jsonl` |
| `scripts/wiki_normalize_metrics.py` | 归一化 metric 名称、单位、baseline 和数值 |
| `scripts/wiki_semantic_qa.py` | 按 evidence anchor 检查 claim 质量 |
| `scripts/wiki_contradictions.py` | 基于 normalized claims 扫描矛盾候选 |
| `scripts/wiki_science_review.py` | 生成二级 LLM/人工科学审稿队列和审稿包 |
| `scripts/wiki_discover_sources.py` | 发现 raw/arXiv 候选并按 arXiv、DOI、hash、标题去重 |
| `scripts/wiki_queue.py` | 规划并执行持久化增长队列 |
| `scripts/wiki_concept_revision.py` | 用已通过门禁的 claims 刷新 concept pages |
| `scripts/wiki_grow.py` | 串起语义自增长循环 |
| `scripts/wiki_lint.py` | 检查结构、QA、链接、index、log 和过时断言 |
| `scripts/wiki_search.py` | 本地 markdown 搜索 |
| `scripts/wiki_writeback.py` | 生成或应用可审阅 writeback diff |
| `scripts/wiki_eval.py` | 对示例 vault 做 smoke test |

初始化会把 runtime 复制到 `<vault>/.open-llm-wiki/scripts/`，让知识库离开本仓库后也能继续自检。

## 快速开始

第一次运行建议先检查脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/AIwork4me/open-llm-wiki/main/setup.sh -o setup.sh
less setup.sh
bash setup.sh my-llm-wiki
```

可选启用 Obsidian 体验层：

```bash
OPEN_LLM_WIKI_OBSIDIAN=1 OPEN_LLM_WIKI_OBSIDIAN_PROFILE=minimal bash setup.sh my-llm-wiki
```

也可以对已有 vault 单独启用，不会让核心 runtime 依赖 Obsidian：

```bash
uv run python scripts/wiki_obsidian_setup.py my-llm-wiki --profile minimal
uv run python scripts/wiki_lint.py my-llm-wiki --obsidian --fail-on p1
```

profile 包括 `minimal`、`research` 和 `full`。重复运行会合并 JSON 配置和
community plugin 列表，不覆盖用户已有键。若希望手动安装插件/主题，使用
`--skip-downloads`。

手动安装：

```bash
git clone https://github.com/AIwork4me/open-llm-wiki.git
mkdir -p ~/.claude/skills
cp -R open-llm-wiki/skills/* ~/.claude/skills/
```

然后添加论文：

```bash
cp ~/papers/attention.pdf my-llm-wiki/raw/
# 告诉 Claude Code:
# Ingest this paper: my-llm-wiki/raw/attention.pdf
```

## 安全边界

- Skill 只在已解析的 wiki vault 内写文件。
- `raw/` 被视为不可变证据层。
- Source page 必须通过独立 QA 后才能 publish。
- Query writeback 默认只读，除非用户明确批准或预授权自动写回。
- Lint 默认只报告。
- Cloud OCR 是可选能力；如果文档内容会离开本机，必须明确告知用户。
- QA report 和 contradiction report 是 append-only 审计记录。
- Obsidian 只是阅读、搜索、导航和轻量编辑体验层，不能绕过 source QA、claim
  graph、semantic QA、contradiction scan 或 query writeback approval gate。

## 质量验证

```bash
uv sync --dev
uv run python -m skills_ref.cli validate skills/wiki-ingest
uv run python -m skills_ref.cli validate skills/query-writeback
uv run python -m skills_ref.cli validate skills/wiki-lint
uv run python scripts/check_quality.py
uv run python scripts/wiki_lint.py examples/minimal-vault --fail-on p1
uv run python scripts/wiki_obsidian_setup.py examples/minimal-vault --dry-run --skip-downloads
uv run python scripts/wiki_eval.py
bash -n setup.sh
```

`uv` 会在项目内使用 `.venv/`，依赖固定在 `uv.lock`，不需要污染全局 Python 环境。
validator 通过 `python -m skills_ref.cli` 调用，避免 Windows 严格应用控制策略拦截生成的 `agentskills.exe`。

PDF 转 Markdown 需要把文档内容发送到配置的 layout parsing API。token 只从环境变量读取：

```bash
export OPEN_LLM_WIKI_LAYOUT_TOKEN="<token>"
uv run python scripts/pdf_to_markdown.py my-llm-wiki/raw/attention.pdf \
  --output my-llm-wiki/raw/attention_markdown
```

批量处理论文文件夹：

```bash
uv run python scripts/pdf_corpus_to_markdown.py my-llm-wiki/raw \
  --output-root my-llm-wiki/raw \
  --no-download-images
```

云端解析会自动重试临时失败；每个输出目录的 `manifest.json` 会记录 API 尝试次数和解析告警。

有 source pages 后运行语义自增长循环：

```bash
uv run python scripts/wiki_grow.py my-llm-wiki \
  --discover-sources \
  --plan-queue \
  --queue-cadence weekly \
  --science-review \
  --apply-concept-revision
```

如果 vault 只有 `raw/*_markdown/combined.md` 解析产物，还没有 source pages，加上 `--ingest-corpus`。

概念页刷新默认跳过需要二级科学审稿的 claim；只有显式标记为
`science_review: approved` 的高风险 claim 才会进入长期 synthesis。

GitHub Actions 会在 push 和 pull request 时运行这些检查。

## License

MIT
