---
id: LLM-0043
title: "DeepSeek-V3 Technical Report"
status: stable
created: 2024-12-27
updated: 2026-05-01
source: "DeepSeek-AI, DeepSeek-V3 Technical Report, 2024"
tags: [deepseek, moe, mla, auxiliary-loss-free, multi-token-prediction]
---

# DeepSeek-V3

> 671B 总参数，37B 激活，14.8T tokens。V3 在 V2 的 MLA + MoE 基础上做了两个关键改进：去掉 auxiliary loss（用 bias 替代）、加入 multi-token prediction。结果：开源最强，接近 GPT-4o 和 Claude 3.5 Sonnet。DeepSeek 的"核弹级"论文。

## 核心贡献

### 继承 V2 的 MLA + DeepSeekMoE
V3 保留了 V2 验证过的 MLA（KV 压缩）和 DeepSeekMoE（细粒度 expert），直接放大到 671B。

### 两大新改进

1. **Auxiliary-loss-free 负载均衡**
   MoE 的老大难问题：expert 负载不均（有些 expert 被疯狂选中，有些无人问津）。传统方法加 auxiliary loss 来惩罚不均衡——但这会损害模型性能。
   V3 的解法：**不加 auxiliary loss，只加一个可学习的 bias 项**。简单、有效、不影响模型性能。

2. **Multi-Token Prediction (MTP)**
   传统 LM 每步只预测下一个 token。V3 额外预测未来 2 个 token（MTP），训练信号更丰富。
   MTP 还在推理时用于 **speculative decoding**——加速推理。

### 训练细节
- **数据**：14.8T tokens（比 V2 大很多）
- **训练**：2048 块 H800 GPU，约 2 个月
- **成本**：约 $5.6M（当时震惊行业——同等规模模型通常要 $50M+）
- **FP8 混合精度**：大部分计算用 FP8，关键部分 BF16

## 关键数据

| 模型 | 总参数 | 激活 | MMLU | MATH | HumanEval |
|------|--------|------|------|------|-----------|
| LLaMA-3.1 405B | 405B | 405B | 69.4% | — | — |
| **DeepSeek-V3** | **671B** | **37B** | **79.4%** | **76.2%** | **82.6%** |
| GPT-4o | — | — | ~80% | ~76% | ~88% |
| Claude 3.5 Sonnet | — | — | ~78% | ~71% | ~84% |

V3 在开源模型中碾压一切，接近 GPT-4o 水平。

## 概念关联

- 前驱：[[LLM-0042|DeepSeek-V2]]（MLA + MoE）→ V3 放大 + 优化
- 后续：[[LLM-0040|DeepSeek-V4]] 继承 V3 的设计，升级混合注意力
- 成本对比：[[LLM-0038|PaLM]] 540B 花 $50M+ vs V3 671B 花 $5.6M
- 概念页：[[decoder-only]]

## 洞察

V3 证明了两件事：

1. **MoE 是最划算的 scaling 方式**：671B 总参数只激活 37B，训练成本 $5.6M——比 dense 模型便宜 10 倍，效果相当。

2. **工程创新和架构创新同样重要**：FP8 训练、auxiliary-loss-free 负载均衡、MTP——这些不是花哨的架构改动，而是让大规模训练变得可行的工程优化。DeepSeek 的核心能力不只是设计架构，更是让架构在工程上跑起来。

V3 的 $5.6M 训练成本震动了整个行业——它证明了"顶级模型不需要十亿美元"。

---

> 原始论文：`raw/DeepSeek-V3.pdf`

## Changelog
- 2026-04-27: 初始 ingest



