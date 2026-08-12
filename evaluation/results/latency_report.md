# MemoryHub 检索延迟测试报告

## 环境
- Embedding: kylin_ollama (nomic-embed-text)
- 记忆索引数: 10338
- 预热查询: 100
- 正式查询: 9900

## 三阶段延迟

| 阶段 | 数量 | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | 均值 (ms) |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| cold | 9900 | 23.44 | 41.34 | 152.46 | 705.15 | 26.99 |
| vector_hot | 9900 | 19.48 | 33.15 | 39.34 | 119.88 | 19.43 |
| result_hot | 9900 | 0.0 | 27.22 | 35.73 | 175.56 | 4.49 |

## 达标检查 (cold P95≤350ms, cold P99≤500ms)

- cold P95: **41.34ms** → ✅ 达标
- cold P99: **152.46ms** → ✅ 达标

## 缓存收益

- P50 加速: cold 23.44ms → vector_hot 19.48ms (17%)
- P95 加速: cold 41.34ms → vector_hot 33.15ms
- P95 加速: cold 41.34ms → result_hot 27.22ms

> 冷查询阶段包含 embedding API 调用延迟；vector_hot 阶段 embedding 缓存命中；result_hot 阶段结果缓存命中。
