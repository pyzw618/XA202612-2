# 麒麟 / Milvus 检索链路改造方案

> 状态：待审核  
> 日期：2026-08-03  
> 适用范围：Kylin-MemoryHub 生产检索链路

## 1. 决策与目标

生产环境的唯一检索主链路为：

```text
API -> 银河麒麟 Embedding SDK -> 稀疏向量生成
    -> 麒麟向量引擎 SDK / Milvus HybridSearch（RRF）
    -> 元数据过滤 -> Top-K
```

FAISS 仅允许在 `development`、`test` 环境，或显式启用的故障诊断场景中作为降级后端；不得参与生产部署和性能验收。

当前阶段验收目标：完成可在真实麒麟环境部署、验证和基准测试的生产代码；不以当前环境无法执行的实机性能数据作为验收条件。后续由具备麒麟环境的同学在 10K 条记忆、Top-K=5 条件下验证 P95 不高于 350ms、P99 不高于 500ms。

## 2. 运行模式与配置门禁

新增 `runtime.mode`（`production`、`development`、`test`）与 `runtime.allow_fallback`。

生产模式启动时必须同时满足：

- `embedding.provider=kylin`，且 SDK 输出维度为 768；
- `vector_engine.provider=milvus`，且 collection schema 的维度为 768；
- Embedding `.so` 可加载、会话可初始化；
- 向量引擎 C API `.so` 可加载，并能连接 Milvus；
- 禁止 `mock`、`kylin_mock`、`faiss` 和静默降级。

建议配置：

```yaml
runtime:
  mode: production
  allow_fallback: false

embedding:
  provider: kylin
  so_path: /usr/lib/libkylin-coreai-embedding.so
  model_name: ensemble-embd_gte-base_uint8-text
  dimension: 768
  query_timeout_ms: 250

vector_engine:
  provider: milvus
  so_path: /usr/lib/libkysdk-vector-engine-client-capi.so
  host: 127.0.0.1
  port: 19530
  collection: memoryhub
  dimension: 768
  search_timeout_ms: 120

retrieval:
  default_top_k: 5
  candidate_multiplier: 4
  max_query_chars: 512
  target_p95_ms: 350
  target_p99_ms: 500
```

## 3. 检索链路

`MilvusHybridRetriever` 成为生产环境唯一 Retriever，具体步骤为：

1. 规范化查询并限制至 512 字符；
2. 查询结果缓存命中时直接返回；
3. 查询向量缓存命中时复用 768 维向量，否则调用常驻的银河麒麟 Embedding SDK 会话；
4. 用与 C API 一致的 FNV-1a 规则构造稀疏向量；
5. 调用 Milvus `HybridSearch`，由引擎执行稠密、稀疏与 RRF 融合；
6. 召回 `top_k * candidate_multiplier` 个候选；
7. 按 `memory_type`、`scope`、`confidence` 过滤，回表 SQLite 补齐记忆详情；
8. 返回 Top-K，并以索引版本号作为缓存键的一部分。

生产路径不再构建 `KeywordSearcher`、`HybridRetriever` 或 `VectorStore`，也不再进行应用层 BM25/向量的二次加权融合。普通重排默认关闭；如保留，仅能对前 20 个候选执行无模型规则重排。

## 4. 端侧存储设计

| 数据 | 存储位置 | 责任 |
|---|---|---|
| 偏好、知识、事实、版本、范围、状态 | SQLite | 事实源、事务、审计、详情回表 |
| 稠密和稀疏向量索引 | Milvus | 混合召回与 RRF 融合 |
| 高频过滤字段 | Milvus scalar fields | `user_id`、`status`、`memory_type`、scope、confidence |
| 正文和大字段 | SQLite | 减少 Milvus 索引与网络负担 |
| 查询向量、热查询结果 | 进程内 LRU | 降低 SDK 和引擎调用次数 |

SQLite 是端侧唯一事实源；Milvus 是可重建的检索投影。记忆正文在 Milvus 中只保留检索必要的短文本或摘要，避免端侧索引膨胀。

## 5. 写入、删除与一致性

```text
SafetyWriteGate
  -> SQLite 事务写入
  -> Embedding / sparse vector
  -> Milvus upsert
  -> 标记 index_version
  -> 失效检索缓存
```

- SQLite 成功而 Milvus 失败：标记 `pending_index`，由重试任务补偿；该条记忆不参与检索。
- Milvus 成功而 SQLite 失败：执行向量删除或记录补偿任务，避免幽灵向量。
- 遗忘：先将 SQLite 标记为 `deleted`，再删除 Milvus 记录，最后失效缓存。
- 启动时仅校验与修复待同步记录；禁止每次启动全量 embedding 和重复插入。

## 6. 延迟预算与后续环境验证

| 阶段 | P95 预算 |
|---|---:|
| 请求校验、缓存键 | 5ms |
| 银河麒麟 Embedding SDK | 180ms |
| 稀疏向量构造 | 10ms |
| Milvus HybridSearch | 100ms |
| 过滤、SQLite 回表、序列化 | 35ms |
| 调度预留 | 20ms |
| 合计 | 350ms |

SDK 推理超过 250ms、Milvus 查询超过 120ms 时，生产环境应返回稳定的超时/不可用错误，不得静默返回 FAISS 结果。开发环境可在明确记录结构化告警后按 `allow_fallback` 启用降级。

## 7. 改造范围

| 模块 | 改造内容 |
|---|---|
| `memoryhub/config.py` | 运行模式、生产门禁、超时和候选数配置 |
| `config.example.yaml` | 生产示例默认 `kylin + milvus + 768` |
| `memoryhub/app.py` | 生产仅装配 Milvus Retriever，增加启动健康检查与仓储注入 |
| `memoryhub/retrieval/milvus_hybrid.py` | 缓存、候选倍数、超时、分段耗时指标，以及可由实机基准采集的性能数据 |
| `memoryhub/storage/vector_engine/milvus_engine.py` | schema 校验、超时、过滤、批量 upsert |
| `memoryhub/embedding/kylin_client.py` | 常驻 session、线程安全、输入限制和稳定错误码 |
| `memoryhub/adapter/api.py` | 写入/遗忘的 SQLite-Milvus 同步与补偿 |
| FAISS 相关模块 | 标记为开发降级，生产配置不可达 |
| `evaluation/` 与 `tests/` | 实机延迟门禁、故障与降级、同步一致性测试 |

## 8. 实施顺序与验收

1. 完成配置与启动门禁；
2. 收敛生产检索到 `MilvusHybridRetriever`；
3. 接通安全写入、SQLite、Milvus、缓存的一致性链路；
4. 增加可观测性与可交接的真实麒麟基准脚本；
5. 隔离 FAISS 降级路径并补齐回归测试。

### 当前阶段：代码实现验收
