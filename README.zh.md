# open-llm-wiki

**一个面向 Claude Code 的 Skill 套件和轻量 runtime，用来把研究论文变成可审计、可持续增长的 LLM Wiki。**

open-llm-wiki 帮助 Agent 将论文转成 source page，把多个 source 连接成 concept page，并用独立 QA、矛盾检查、append-only 日志、确定性 lint/search 工具和可审阅 writeback diff 保持知识库可信。

灵感来自 [Andrej Karpathy 的 LLM Wiki 构想](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)。

[快速开始](QUICKSTART.md) | [Schema](SCHEMA.md) | [示例](EXAMPLES.md) | [展示](SHOWCASE.md)

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

## Runtime 层

Skill 负责判断和协调；runtime 脚本负责可重复检查：

| Script | 用途 |
| --- | --- |
| `scripts/wiki_init.py` | 初始化个人/团队 vault |
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

## 质量验证

```bash
uv sync --dev
uv run python -m skills_ref.cli validate skills/wiki-ingest
uv run python -m skills_ref.cli validate skills/query-writeback
uv run python -m skills_ref.cli validate skills/wiki-lint
uv run python scripts/check_quality.py
uv run python scripts/wiki_lint.py examples/minimal-vault --fail-on p1
uv run python scripts/wiki_eval.py
bash -n setup.sh
```

`uv` 会在项目内使用 `.venv/`，依赖固定在 `uv.lock`，不需要污染全局 Python 环境。
validator 通过 `python -m skills_ref.cli` 调用，避免 Windows 严格应用控制策略拦截生成的 `agentskills.exe`。

GitHub Actions 会在 push 和 pull request 时运行这些检查。

## License

MIT
