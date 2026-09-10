# MemoryHub 四项指标评测报告

> 证据等级：**DEMONSTRATION_ONLY**
> 检索与延迟使用内置确定性 mock 通道，仅验证评测数据、检索编排和回归；不得作为真实 Kylin Embedding + Milvus 的生产验收结论。

| 指标 | 结果 | 阈值 | 样本数 | 判定 |
|---|---:|---:|---:|---|
| 偏好提取准确率 | 30.00% | ≥ 85% | 120 | 未通过 |
| 知识检索召回率 Recall@K | 98.33% | ≥ 85% | 250 | 通过 |
| 知识检索响应时间 P95 | 0.274 | ≤ 500ms | 750 | 通过 |
| 知识冲突处理正确率 | 55.00% | ≥ 88% | 100 | 未通过 |

## 环境指纹

- 运行模式：`development`；向量引擎：`faiss`；Embedding：`mock`
- vNext 模式：`vnext`；Embedding 维度：`1024`

## 生产验收前置条件

- 在目标麒麟机器执行 scripts/check_kylin_embedding_runtime.py。
- 执行 scripts/run_milvus_real_smoke_test.py --app_id <真实 app_id>。
- 使用真实服务的 HTTP 评测替换本报告中的 mock 检索与延迟结果。
