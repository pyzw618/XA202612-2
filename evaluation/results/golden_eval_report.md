# MemoryHub 检索评测报告

## 1. 环境信息

- **Embedding Provider**: kylin_ollama (请求: kylin_ollama)
- **Embedding 模型**: nomic-embed-text
- **Embedding 维度**: 768
- **Embedding Fallback**: 否
- **向量引擎**: faiss
- **Top-K**: 10
- **数据集**: evaluation/datasets/memoryhub_golden_retrieval_v1.json
- **时间戳**: 2026-08-11T04:09:43.235798+00:00
- **Git Commit**: 06d95bc

---

## 2. 总体指标

### 2.1 最佳组 (A组) 汇总

| 指标 | 值 |
|------|-----|
| recall_1 | 0.39 |
| recall_5 | 0.555 |
| recall_10 | 0.6 |
| precision_1 | 0.36 |
| precision_5 | 0.124 |
| precision_10 | 0.069 |
| mrr | 0.4184 |
| ndcg_5 | 0.3818 |
| ndcg_10 | 0.4007 |
| latency P50 | 76.258 ms |
| latency P95 | 122.691 ms |
| latency P99 | 154.761 ms |
| latency Max | 157.61 ms |

### 2.2 消融对比

| 组 | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms | latency_p99_ms |
|---|---:|---:|---:|---:|---:|---:|
| A (纯 BM25) | 0.555 | 0.6 | 0.4184 | 0.4007 | 122.691 | 154.761 |
| B (纯 FAISS) | 0.34 | 0.435 | 0.181 | 0.2027 | 0.751 | 0.9 |
| C (Hybrid默认) | 0.385 | 0.435 | 0.2692 | 0.2583 | 0.754 | 0.952 |
| D (Hybrid均衡) | 0.55 | 0.59 | 0.3722 | 0.3586 | 0.854 | 1.294 |
| E (Hybrid重向量) | 0.385 | 0.435 | 0.2692 | 0.2583 | 0.762 | 1.153 |

### 2.3 召回率达标检查 (Recall@5 ≥ 0.85)

- 最佳组 (A) Recall@5 = **0.5550** → ❌ 未达标 (0.5550)
- Test 集 400 条查询，A 组计算结果

---

## 3. 分组统计

### 3.4 按 difficulty

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| cross-domain | 15 | 0.2 | 0.2333 | 0.1389 | 0.1642 | 90.093 |
| exact | 15 | 0.9333 | 0.9667 | 0.9467 | 0.9304 | 89.802 |
| hard-negative | 25 | 0.48 | 0.54 | 0.3613 | 0.3565 | 90.834 |
| no-answer | 10 | 1.0 | 1.0 | 0.0 | 0.0 | 140.497 |
| semantic | 35 | 0.4714 | 0.5286 | 0.4722 | 0.4211 | 123.341 |

### 3.11 按 knowledge_type

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| case | 18 | 0.3889 | 0.4444 | 0.4093 | 0.3491 | 100.153 |
| template | 28 | 0.5536 | 0.625 | 0.5825 | 0.5557 | 91.006 |
| workflow | 77 | 0.4935 | 0.5455 | 0.4623 | 0.4418 | 108.694 |

### 3.12 按 language

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| en-US | 27 | 0.3333 | 0.3704 | 0.1331 | 0.1472 | 124.919 |
| mixed | 8 | 0.25 | 0.4375 | 0.2396 | 0.2547 | 86.946 |
| zh-CN | 65 | 0.6846 | 0.7154 | 0.559 | 0.524 | 94.103 |

### 3.21 按 user_id

| 分组 | count | recall_5 | recall_10 | mrr | ndcg_10 | latency_p95_ms |
|---|---:|---:|---:|---:|---:|---:|
| user_001 | 100 | 0.555 | 0.6 | 0.4184 | 0.4007 | 122.691 |

---

## 4. 延迟分布

| 组 | P50 | P95 | P99 | Max |
|---|---:|---:|---:|---:|
| A (纯 BM25) | 76.258 | 122.691 | 154.761 | 157.61 |
| B (纯 FAISS) | 0.569 | 0.751 | 0.9 | 0.959 |
| C (Hybrid默认) | 0.587 | 0.754 | 0.952 | 1.144 |
| D (Hybrid均衡) | 0.605 | 0.854 | 1.294 | 1.853 |
| E (Hybrid重向量) | 0.581 | 0.762 | 1.153 | 1.67 |

---

## 5. 用户隔离性验证

| 用户 | 查询数 | 平均异用户召回率 | 最大异用户召回率 | 通过(≤0.05) |
|---|---:|---:|---:|:---:|
| user_001 | 100 | 0.0000 | 0.0000 | ✅ |

---

## 6. 完全失败查询分析 (R@5=0)

- 完全失败: **36/100** (36.0%)
- 难度分布: {'semantic': 14, 'hard-negative': 11, 'cross-domain': 11}

| 查询ID | 难度 | 查询文本 |
|---|---|---|
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
| gq_050 | semantic | Please send a company-wide announcement about the new policy |
| gq_052 | hard-negative | 帮我check一下服务器的health然后发送一份audit |
| gq_054 | hard-negative | 帮我把这个服务deploy到Kubernetes上 |
| gq_055 | hard-negative | We need a review of our expenses from last month |
| gq_056 | hard-negative | Configuration management for production servers |
| gq_058 | hard-negative | 怎么check数据库的index是不是有问题 |
| gq_060 | hard-negative | 帮我把钱从一个账户转到另一个 |
| ... | ... | 还有 16 条 |

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
