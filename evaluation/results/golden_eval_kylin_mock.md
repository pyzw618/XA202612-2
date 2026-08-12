# MemoryHub 检索评测报告

## 1. 环境信息

- **Embedding Provider**: kylin_mock (请求: kylin)
- **Embedding 模型**: ensemble-embd_gte-base_uint8-text
- **Embedding 维度**: 768
- **Embedding Fallback**: 否
- **向量引擎**: faiss
- **Top-K**: 10
- **数据集**: evaluation/datasets/memoryhub_golden_retrieval_v1.json
- **时间戳**: 2026-08-11T08:20:40.184281+00:00
- **Git Commit**: 06d95bc

---

## 2. 总体指标

### 2.1 最佳组 (A组) 汇总

| 指标 | 值 |
|------|-----|
| recall_1 | 0.39 |
| recall_5 | 0.535 |
| recall_10 | 0.57 |
| precision_1 | 0.36 |
| precision_5 | 0.118 |
| precision_10 | 0.064 |
| mrr | 0.4092 |
| ndcg_5 | 0.3721 |
| ndcg_10 | 0.386 |
| latency P50 | 1.043 ms |
| latency P95 | 8.371 ms |
| latency P99 | 11.371 ms |
| latency Max | 12.916 ms |

### 2.2 消融对比

| 组 | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms | latency_p99_ms |
|---|---:|---:|---:|---:|---:|---:|
| A (纯 BM25) | 0.535 | 0.57 | 0.4092 | 0.386 | 8.371 | 11.371 |
| B (纯 FAISS) | 0.165 | 0.19 | 0.0351 | 0.037 | 3.758 | 6.17 |
| C (Hybrid默认) | 0.195 | 0.21 | 0.0984 | 0.0759 | 2.189 | 3.098 |
| D (Hybrid均衡) | 0.53 | 0.555 | 0.4088 | 0.3679 | 1.454 | 3.664 |
| E (Hybrid重向量) | 0.195 | 0.21 | 0.0984 | 0.0759 | 1.104 | 3.679 |

### 2.3 召回率达标检查 (Recall@5 ≥ 0.85)

- 最佳组 (A) Recall@5 = **0.5350** → ❌ 未达标 (0.5350)
- Test 集 400 条查询，A 组计算结果

---

## 3. 分组统计

### 3.4 按 difficulty

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| cross-domain | 15 | 0.2 | 0.2333 | 0.1389 | 0.1642 | 3.92 |
| exact | 15 | 0.9 | 0.9333 | 0.9333 | 0.9122 | 11.823 |
| hard-negative | 25 | 0.46 | 0.5 | 0.3447 | 0.3356 | 5.369 |
| no-answer | 10 | 1.0 | 1.0 | 0.0 | 0.0 | 3.49 |
| semantic | 35 | 0.4429 | 0.4857 | 0.4633 | 0.4017 | 7.043 |

### 3.11 按 knowledge_type

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| case | 18 | 0.3889 | 0.4444 | 0.4093 | 0.3491 | 3.131 |
| template | 28 | 0.5179 | 0.5536 | 0.5565 | 0.5156 | 10.3 |
| workflow | 77 | 0.4675 | 0.5065 | 0.4502 | 0.4226 | 8.62 |

### 3.12 按 language

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| en-US | 27 | 0.2593 | 0.2593 | 0.0988 | 0.0926 | 8.022 |
| mixed | 8 | 0.25 | 0.4375 | 0.2396 | 0.2547 | 1.42 |
| zh-CN | 65 | 0.6846 | 0.7154 | 0.559 | 0.524 | 8.36 |

### 3.21 按 user_id

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| user_001 | 100 | 0.535 | 0.57 | 0.4092 | 0.386 | 8.371 |

---

## 4. 延迟分布

| 组 | P50 | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| A (纯 BM25) | 1.043 | 8.371 | 11.371 | 12.916 |
| B (纯 FAISS) | 0.782 | 3.758 | 6.17 | 8.604 |
| C (Hybrid默认) | 0.762 | 2.189 | 3.098 | 3.696 |
| D (Hybrid均衡) | 0.681 | 1.454 | 3.664 | 4.211 |
| E (Hybrid重向量) | 0.71 | 1.104 | 3.679 | 6.596 |

---

## 5. 用户隔离性验证

| 用户 | 查询数 | 平均异用户召回率 | 最大异用户召回率 | 通过(≤0.05) |
|---|---:|---:|---:|:---:|
| user_001 | 100 | 0.0000 | 0.0000 | ✅ |

---

## 6. 完全失败查询分析 (R@5=0)

- 完全失败: **39/100** (39.0%)
- 难度分布: {'exact': 1, 'semantic': 15, 'hard-negative': 12, 'cross-domain': 11}

| 查询ID | 难度 | 查询文本 |
|---|---|---|
| gq_003 | exact | How to do code review on my PR |
| gq_016 | semantic | 领导要我写一份这周干了什么的总结邮件 |
| gq_020 | semantic | 网站怎么加上https小锁 |
| gq_022 | semantic | Quick question: how do I back up my database and files safel |
| gq_023 | semantic | 每天花一点时间记录学到的东西 |
| gq_024 | semantic | The new server needs to be locked down before going live |
| gq_026 | semantic | Make sure the deployment rolls out gradually to avoid breaki |
| gq_028 | semantic | 这个季度我花了多少钱看看有没有超预算 |
| gq_030 | semantic | Let me know if there are any outstanding payments from last  |
| gq_031 | semantic | 上次那个故障后来是怎么修复的帮我复盘一下 |
| gq_036 | semantic | System upgrade broke the balance sheet - what happened |
| gq_038 | semantic | Just got an alert that disk is full - help |
| gq_040 | semantic | Need a template for my weekly project status update |
| gq_042 | semantic | How to handle a customer complaint about a wrongly closed ti |
| gq_044 | semantic | Can you run a security audit on this server |
| gq_050 | semantic | Please send a company-wide announcement about the new policy |
| gq_052 | hard-negative | 帮我check一下服务器的health然后发送一份audit |
| gq_054 | hard-negative | 帮我把这个服务deploy到Kubernetes上 |
| gq_055 | hard-negative | We need a review of our expenses from last month |
| gq_056 | hard-negative | Configuration management for production servers |
| ... | ... | 还有 19 条 |

---

## 7. 已知问题与建议

### 7.1 Bootstrap 95% CI
- **状态**: TODO（未实现）
- **建议**: 在后续版本中实现 Bootstrap 重采样 1000 次计算 95% 置信区间。

### 7.2 核心记忆规模
- Test 集核心手工记忆 358 条，接近但未达 ≥500 条目标。
- 合成记忆 9,640 条填补总规模至 10K+，覆盖 10 个领域但内容模板化。
- **建议**: 补充 140+ 条高质量手工记忆到 v1.1。

### 7.3 冷/热缓存对比
- **状态**: 待 P0-1 完成后启用独立缓存层。
- **建议**: 在麒麟环境上跑 latency 集验证冷查询 P99≤500ms。

### 5.4 冷/热缓存对比
- **状态**: 部分实现。当前 Hyrid 检索器不启用独立缓存层。
- **影响**: 无法测量 result cache 和 query-vector cache 的命中率。
- **建议**: 在 P0-1 完成后启用独立缓存并记录命中率。

### 5.5 原 eval_dataset.py 格式兼容
- 当前脚本仅支持新格式（0-3 级 relevance 标注），不支持旧的 `relevant_ids` 扁平列表格式。
- 旧格式评测请使用原 `evaluation/run_retrieval_eval.py`（版本请查阅 git log）。
