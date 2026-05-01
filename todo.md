# TODO — 明早完成

## 必做（10 分钟）

### 1. GitHub 仓库设置（2 分钟）
打开 https://github.com/AIwork4me/open-llm-wiki/settings

- **Description**: `Your AI knowledge base that compounds. Drop papers in → get a living wiki out.`
- **Website**: `https://github.com/AIwork4me/open-llm-wiki`
- **Topics**: `knowledge-base, llm, obsidian, research-papers, ai-agent, karpathy, pkm, deepseek`
- 点 Save

### 2. 截图（5 分钟）
在本地 Obsidian 打开 `open-llm-wiki/examples/minimal-vault/`

**截图 1 — Graph View**：
- Obsidian → 左侧栏 → 打开 Graph View（快捷键 Ctrl/Cmd+G）
- 截图，保存为 `assets/graph-view.png`

**截图 2 — Concept Page**：
- 打开 `concepts/attention-mechanisms.md`
- 截图，保存为 `assets/concept-page.png`

然后 push：
```bash
cd open-llm-wiki
git add assets/*.png
git commit -m "docs: add Obsidian screenshots"
git push origin main
```

### 3. 更新 README 引用截图（已准备好了，push 截图后自动生效）
README 里已经有 `> 📸 Drop a screenshot of Obsidian graph view here: assets/graph-view.png`
截图放进去后，改成：
```markdown
![Knowledge Graph](assets/graph-view.png)
```

## 建议做（明天，30 分钟）

### 4. 录 Demo GIF
用屏幕录制工具（OBS / macOS 自带 / Windows Game Bar）：
- 打开 Obsidian vault
- Drop 一个 PDF 到 `raw/`
- 等 agent 处理完
- 切回 Obsidian 看 graph 多了一个节点
- 保存为 `assets/demo.gif`（10-15 秒）

### 5. 打 v0.1.0 Release
```bash
git tag -a v0.1.0 -m "Initial release: 3 skills, 23 papers validated"
git push origin v0.1.0
```
然后在 GitHub → Releases → Draft a new release，写 release notes。

### 6. 发帖推广
- **HackerNews**: Show HN post
- **Reddit**: r/MachineLearning, r/LocalLLaMA
- **Twitter/X**: 发推 @karpathy（他可能会转）

## 已完成（今晚）
- [x] README 重写（5 秒 hook + 对比表 + 流程图）
- [x] 中文 README 重写（独立 pitch + 对比表）
- [x] SVG 流程图（GitHub 兼容）
- [x] setup.sh 一键安装
- [x] 修 license → LICENSE
- [x] 修 showcase.md → SHOWCASE.md
- [x] 修 examples.md → EXAMPLES.md
- [x] 修所有内部引用
- [x] Star History badge（两个 README）
- [x] 清除所有 yourusername 占位符
- [x] 修 V3.2 引用（保留真实故事）
