# 麒麟 / Milvus 检索链路改造任务清单

> 来源方案：[2026-08-03_kylin_milvus_retrieval_refactor_plan.md](../2026-08-03_kylin_milvus_retrieval_refactor_plan.md)
> 状态：已按最新方案调整
> 创建日期：2026-08-03
> 适用范围：Kylin-MemoryHub 生产检索链路

## 目标与验收标准

### 总体目标

将生产环境检索主链路收敛为：

```text
API -> 银河麒麟 Embedding SDK -> 稀疏向量生成
    -> 麒麟向量引擎 SDK / Milvus HybridSearch（RRF）
    -> 元数据过滤 -> Top-K
```

FAISS 仅允许在 `development`、`test` 环境，或显式启用的故障诊断场景中作为降级后端；不得参与生产部署和性能验收。

### 阶段划分

| 阶段 | 范围 | 验收方式 |
|---|---|---|
| 当前阶段 | 代码实现验收 | 完成可在真实麒麟环境部署、验证和基准测试的生产代码；**不以当前环境无法执行的实机性能数据作为验收条件**。 |
| 后续阶段 | 真实环境性能验收 | 由具备麒麟环境的同学在 10K 条记忆、Top-K=5 条件下验证 P95 ≤ 350ms、P99 ≤ 500ms，并报告 Recall@5、NDCG@10、缓存命中率、Embedding/Milvus 错误率、待同步积压数。 |

### 当前阶段必须交付的验收项

| 验收项 | 说明 |
|---|---|
| 生产启动门禁 | 生产模式下必须校验 `kylin` + `milvus` + 768 维、SO 可加载、禁止 mock/faiss/静默降级 |
| 唯一生产 Retriever | `MilvusHybridRetriever` 为生产唯一检索入口，其余路径不可达 |
| 写入/遗忘一致性 | SQLite 与 Milvus 双写具备失败补偿，无幽灵向量 |
| 超时与错误处理 | Embedding 超时 250ms、Milvus 超时 120ms，生产不静默降级到 FAISS |
| 可观测性埋点 | 检索各阶段耗时、错误率、缓存命中率可通过日志或指标输出 |
| 可交接基准脚本 | 提供真实麒麟环境可直接运行的基准测试脚本，输出后续阶段所需的全部性能指标 |
| 回归测试 | 覆盖生产门禁、降级隔离、同步一致性、超时处理 |

---

## 任务分解

### 阶段一：配置与启动门禁

#### TASK-001：扩展运行时配置模型

- **目标**：在 `memoryhub/config.py` 中新增 `runtime.mode`（`production` / `development` / `test`）与 `runtime.allow_fallback` 配置项。
- **验收标准**：
  - 配置模型支持三种运行模式，默认值为 `development`。
  - `allow_fallback` 在生产模式下默认 `false`，在开发/测试模式下可显式开启。
  - 配置读取失败时给出明确的结构化错误。
- **相关文件**：`memoryhub/config.py`
- **优先级**：P0
- **依赖**：无

#### TASK-002：实现生产环境启动门禁

- **目标**：应用启动时根据 `runtime.mode=production` 执行强制检查。
- **验收标准**：
  - 检查 `embedding.provider=kylin`，且 SDK 输出维度为 768。
  - 检查 `vector_engine.provider=milvus`，且 collection schema 维度为 768。
  - 验证 Embedding `.so` 可加载、会话可初始化。
  - 验证向量引擎 C API `.so` 可加载，并能连接 Milvus。
  - 生产模式下禁止 `mock`、`kylin_mock`、`faiss` 和静默降级；任一不满足则启动失败并返回明确错误码。
- **相关文件**：`memoryhub/config.py`、`memoryhub/app.py`
- **优先级**：P0
- **依赖**：TASK-001

#### TASK-003：更新生产配置示例

- **目标**：将 `config.example.yaml` 生产示例默认调整为 `kylin + milvus + 768`。
- **验收标准**：
  - `config.example.yaml` 中 `runtime.mode` 为 `production`，`allow_fallback` 为 `false`。
  - `embedding.provider=kylin`，`dimension=768`，`query_timeout_ms=250`。
  - `vector_engine.provider=milvus`，`dimension=768`，`search_timeout_ms=120`。
  - 包含检索链路延迟预算相关配置：`target_p95_ms=350`、`target_p99_ms=500`。
- **相关文件**：`config.example.yaml`
- **优先级**：P0
- **依赖**：TASK-001

---

### 阶段二：收敛生产检索链路到 MilvusHybridRetriever

#### TASK-004：完善 MilvusHybridRetriever 生产路径

- **目标**：使 `MilvusHybridRetriever` 成为生产环境唯一 Retriever，完成完整检索步骤。
- **验收标准**：
  - 规范化查询并限制至 512 字符。
  - 查询结果缓存命中时直接返回。
  - 查询向量缓存命中时复用 768 维向量，否则调用常驻的银河麒麟 Embedding SDK 会话。
  - 用与 C API 一致的 FNV-1a 规则构造稀疏向量。
  - 调用 Milvus `HybridSearch`，由引擎执行稠密、稀疏与 RRF 融合。
  - 召回 `top_k * candidate_multiplier` 个候选。
  - 按 `memory_type`、`scope`、`confidence` 过滤，回表 SQLite 补齐记忆详情。
  - 返回 Top-K，并以索引版本号作为缓存键的一部分。
  - 不再构建 `KeywordSearcher`、`HybridRetriever` 或 `VectorStore`。
  - 普通重排默认关闭；如保留，仅能对前 20 个候选执行无模型规则重排。
- **相关文件**：`memoryhub/retrieval/milvus_hybrid.py`
- **优先级**：P0
- **依赖**：TASK-002

#### TASK-005：应用层装配生产仅 Milvus Retriever

- **目标**：`memoryhub/app.py` 在生产模式下仅装配 `MilvusHybridRetriever`，并注入所需仓储。
- **验收标准**：
  - 生产模式下启动时仅初始化 `MilvusHybridRetriever`。
  - 注入 SQLite 仓储、Milvus 向量引擎、Embedding 客户端、缓存等依赖。
  - 启动健康检查包含 Embedding SDK 和 Milvus 向量引擎连接状态。
- **相关文件**：`memoryhub/app.py`
- **优先级**：P0
- **依赖**：TASK-002、TASK-004

---

### 阶段三：端侧存储与向量引擎改造

#### TASK-006：Milvus 向量引擎 schema 与超时改造

- **目标**：在 `memoryhub/storage/vector_engine/milvus_engine.py` 中完成 schema 校验、超时、过滤和批量 upsert。
- **验收标准**：
  - collection schema 维度固定为 768，启动时校验。
  - 支持稠密向量、稀疏向量及 scalar fields：`user_id`、`status`、`memory_type`、scope、confidence。
  - `search_timeout_ms=120` 生效，超时返回稳定错误码。
  - 支持批量 upsert，失败时记录待同步状态。
- **相关文件**：`memoryhub/storage/vector_engine/milvus_engine.py`
- **优先级**：P0
- **依赖**：TASK-002

#### TASK-007：Embedding SDK 客户端改造

- **目标**：在 `memoryhub/embedding/kylin_client.py` 中实现常驻 session、线程安全、输入限制和稳定错误码。
- **验收标准**：
  - 应用生命周期内维持一个常驻的银河麒麟 Embedding SDK 会话。
  - 线程安全：并发调用不崩溃、不泄漏资源。
  - 输入长度限制在 512 字符以内，超长时截断或报错。
  - `query_timeout_ms=250` 生效，超时返回稳定错误码。
  - 输出维度固定为 768。
- **相关文件**：`memoryhub/embedding/kylin_client.py`
- **优先级**：P0
- **依赖**：TASK-002

#### TASK-008：端侧存储一致性设计落地

- **目标**：明确 SQLite 作为唯一事实源、Milvus 作为可重建检索投影的存储分工。
- **验收标准**：
  - 偏好、知识、事实、版本、范围、状态写入 SQLite。
  - 稠密和稀疏向量索引写入 Milvus。
  - 高频过滤字段在 Milvus scalar fields 中可过滤。
  - 正文和大字段保留在 SQLite，Milvus 仅保留检索必要的短文本或摘要。
  - 查询向量、热查询结果放入进程内 LRU 缓存。
- **相关文件**：`memoryhub/storage/`、`memoryhub/retrieval/milvus_hybrid.py`
- **优先级**：P1
- **依赖**：TASK-006

---

### 阶段四：写入、删除与一致性链路

#### TASK-009：安全写入门与同步链路

- **目标**：在 `memoryhub/adapter/api.py` 中实现写入/遗忘的 SQLite-Milvus 同步与补偿。
- **验收标准**：
  - 写入流程：`SafetyWriteGate -> SQLite 事务写入 -> Embedding / sparse vector -> Milvus upsert -> 标记 index_version -> 失效检索缓存`。
  - SQLite 成功而 Milvus 失败：标记 `pending_index`，由重试任务补偿；该条记忆不参与检索。
  - Milvus 成功而 SQLite 失败：执行向量删除或记录补偿任务，避免幽灵向量。
  - 遗忘流程：先将 SQLite 标记为 `deleted`，再删除 Milvus 记录，最后失效缓存。
  - 启动时仅校验与修复待同步记录；禁止每次启动全量 embedding 和重复插入。
- **相关文件**：`memoryhub/adapter/api.py`、`memoryhub/storage/`、`memoryhub/retrieval/milvus_hybrid.py`
- **优先级**：P0
- **依赖**：TASK-006、TASK-007

#### TASK-010：待同步补偿任务

- **目标**：实现 `pending_index` 记录的异步补偿机制。
- **验收标准**：
  - 定时扫描 SQLite 中 `pending_index` 记录。
  - 补偿成功后将记录标记为已同步，并失效相关缓存。
  - 补偿失败时记录日志和指标，支持告警。
- **相关文件**：`memoryhub/adapter/api.py`、`memoryhub/storage/`
- **优先级**：P1
- **依赖**：TASK-009

---

### 阶段五：可观测性与延迟预算

#### TASK-011：检索链路分段耗时指标

- **目标**：在 `MilvusHybridRetriever` 中埋入各阶段耗时指标，并支持由实机基准采集。
- **验收标准**：
  - 记录请求校验、缓存键构造耗时。
  - 记录银河麒麟 Embedding SDK 耗时。
  - 记录稀疏向量构造耗时。
  - 记录 Milvus HybridSearch 耗时。
  - 记录过滤、SQLite 回表、序列化耗时。
  - 汇总总耗时，并对比 P95/P99 预算。
  - 指标输出格式便于基准脚本直接解析（日志、指标端点或结构化文件）。
- **相关文件**：`memoryhub/retrieval/milvus_hybrid.py`
- **优先级**：P1
- **依赖**：TASK-004

#### TASK-012：超时与降级告警

- **目标**：SDK 推理超过 250ms、Milvus 查询超过 120ms 时按环境策略处理。
- **验收标准**：
  - 生产模式返回稳定的超时/不可用错误，不得静默返回 FAISS 结果。
  - 开发/测试模式在明确记录结构化告警后，可按 `allow_fallback` 启用降级。
  - 告警信息包含阶段、耗时、超时阈值。
- **相关文件**：`memoryhub/retrieval/milvus_hybrid.py`、`memoryhub/embedding/kylin_client.py`、`memoryhub/storage/vector_engine/milvus_engine.py`
- **优先级**：P1
- **依赖**：TASK-004、TASK-006、TASK-007

---

### 阶段六：FAISS 降级路径隔离

#### TASK-013：隔离 FAISS 为开发降级路径

- **目标**：将 FAISS 相关模块标记为开发/测试环境专用，生产配置不可达。
- **验收标准**：
  - 生产模式下启动门禁拒绝 `faiss` provider。
  - FAISS 相关代码路径添加明确的环境检查与日志说明。
  - 文档注明 FAISS 仅用于 `development`、`test` 或显式诊断场景。
- **相关文件**：FAISS 相关模块、`memoryhub/config.py`、`memoryhub/app.py`
- **优先级**：P1
- **依赖**：TASK-002

---

### 阶段七：测试与基准验收

#### TASK-014：可交接的真实麒麟基准脚本

- **目标**：提供可在真实麒麟环境直接运行的基准测试脚本，输出后续阶段所需的全部性能指标。
- **验收标准**：
  - 脚本支持在真实麒麟设备上运行 10K 条记忆、Top-K=5 的完整检索基准。
  - 输出完整检索链路 P95/P99 延迟。
  - 输出 Recall@5、NDCG@10。
  - 输出缓存命中率、Embedding/Milvus 错误率、待同步积压数。
  - 脚本包含环境检查、依赖说明、运行命令和结果解读文档，便于不具备本模块背景的同学独立执行。
  - 当前阶段不要求在本地实机跑出性能数据，但必须保证脚本在真实麒麟环境可运行、指标可采集。
- **相关文件**：`evaluation/run_milvus_kylin_benchmark.py`、`evaluation/run_milvus_mock_benchmark.py`
- **优先级**：P0
- **依赖**：TASK-004、TASK-006、TASK-007、TASK-009、TASK-011

#### TASK-015：故障、降级与一致性回归测试

- **目标**：补齐故障注入与一致性回归测试。
- **验收标准**：
  - 生产模式无法选中 FAISS 或 Mock 的单元/集成测试。
  - SQLite 成功 / Milvus 失败的补偿链路测试。
  - Milvus 成功 / SQLite 失败的回滚/补偿测试。
  - Embedding 超时、Milvus 超时的错误处理测试。
  - 遗忘流程一致性测试。
- **相关文件**：`tests/`、`evaluation/`
- **优先级**：P1
- **依赖**：TASK-002、TASK-009、TASK-012

---

## 实施顺序

1. **阶段一**：TASK-001 -> TASK-002 -> TASK-003
2. **阶段二**：TASK-004 -> TASK-005
3. **阶段三**：TASK-006、TASK-007 并行 -> TASK-008
4. **阶段四**：TASK-009 -> TASK-010
5. **阶段五**：TASK-011、TASK-012 并行
6. **阶段六**：TASK-013
7. **阶段七**：TASK-014、TASK-015 并行

---

## 风险与待决策事项

| 风险/事项 | 描述 | 建议处理人 | 状态 |
|---|---|---|---|
| 麒麟实机可用性 | 真实麒麟设备是否已就绪，直接影响 TASK-014 的现场验证；当前阶段以脚本可交接为目标 | 运维/硬件负责人 | 待确认 |
| SDK 超时阈值 | Embedding 250ms / Milvus 120ms 是否需根据实机数据调整 | 算法/后端负责人 | 后续阶段验证 |
| 缓存失效策略 | index_version 变更时缓存失效粒度（全局/按用户/按 collection） | 后端负责人 | 待设计 |
| 重排是否保留 | 普通重排默认关闭，是否完全移除相关代码 | 后端负责人 | 待决策 |
| 补偿任务调度 | 使用独立线程、进程还是外部定时任务触发补偿 | 后端负责人 | 待设计 |

---

## 附录：延迟预算（供后续真实环境验证）

| 阶段 | P95 预算 |
|---|---:|
| 请求校验、缓存键 | 5ms |
| 银河麒麟 Embedding SDK | 180ms |
| 稀疏向量构造 | 10ms |
| Milvus HybridSearch | 100ms |
| 过滤、SQLite 回表、序列化 | 35ms |
| 调度预留 | 20ms |
| **合计** | **350ms** |
