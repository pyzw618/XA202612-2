# MemoryHub 数据流修复更新记录

> 文件位置：`docs/DATA_FLOW_UPDATE.md`  
> 更新日期：2026-08-03  
> 说明：记录本轮针对数据流审查问题实施的代码修改和验证结果。

## 2026-08-03：事件写入主链、安全与抽取闭环

### 问题

- `/events` 原先仅保存事件，未执行质量、安全和抽取。
- 重复 event_id 会覆盖并重复触发下游；accepted/rejected 不能表达真实决策。
- 抽取记忆没有统一同步 SQLite、向量、BM25、lookup、Evidence 和 cache。

### 修改

- 新增 `memoryhub/core/ingestion/service.py`：质量评分、SafetyWriteGate、幂等/碰撞判断、首次安全事件事务保存和三类记忆抽取编排。
- 新增 `memoryhub/core/memory_write.py`：统一 preference/knowledge 持久化和运行时索引同步。
- `memoryhub/app.py` 装配 Gate、MemoryWriteService、EventIngestionService、PreferenceExtractor/Updater、KnowledgeExtractor 和 EvidenceStore。
- `memoryhub/adapter/api.py` 的 `/events` 改用 EventIngestionService；Gate/基础设施不可用时返回稳定错误。

## 2026-08-03：偏好版本、冲突与完整持久化

### 修改

- 补齐 PreferenceMemory 的 payload、is_global、quality、extract_source、root_id、tags、extra_payload 和健康字段及 SQLite 加法迁移。
- Evidence JSON 改用 JSON mode 序列化。
- PreferenceUpdater 保存 conflict/result_memory_id/resolved_at，建立 parent/root/version，并同步活跃/归档索引。
- ConflictRecord/ConflictRow、仓储、API、控制台增加 user_id；resolve 按用户命中。

## 2026-08-03：检索反馈与遗忘级联

### 修改

- `/search` 与 `/context` 回写 preference/knowledge/facts 的 last_accessed_at 和 access_count_30d。
- Preference/Knowledge Repository 保存并读回健康字段。
- MemoryForgetter 级联删除 EvidenceStore、关联 conflict 与 facts；facts 同步清理共享索引和用户范围内孤立实体。
- 控制台 preference live 表格优先读取 `text`，详情和 conflict 调用传递 user_id。

## 2026-08-03：Normalizer 与质量边界

### 修改

- EventNormalizer 生成完整 Schema 1.1 字段，包括 source_hash、quality、turn_id、tool_calls、redactions。
- normalize_tool_result 生成合法 ToolCallResult。
- QualityScorer freshness 限制在 `[0,1]`。

## 2026-08-03：facts 主事件、检索与遗忘闭环

### 问题

- facts 独立存在，未由 `/events` 的质量与安全入口驱动。
- Fact/Entity 缺少 user_id，归一化、冲突、检索和删除存在跨用户风险。
- facts 未进入主 FAISS/Milvus、BM25、lookup、cache 和 SearchResponse。
- 显式/自动遗忘不处理 facts，健康度不能处理 ISO 时间。
- facts 构造绑定独立远程客户端，归一化索引可能隐式下载模型。

### 修改

- EventIngestionService 增加可注入 fact_ingestion_adapter，仅处理首次通过 quality 与 SafetyWriteGate 的安全事件。
- FactIngestionAdapter 从事件透传 user_id、project_id、来源和质量元数据，并自动 propose/commit。
- Fact、Entity 和 FactStore 增加用户隔离、访问统计、旧库加法迁移和孤立实体清理；S+P 冲突和状态更新按 owner 限定。
- 新增 `memoryhub/core/fact/llm.py`，facts 复用主应用 LLM；无外部 key 可启动，调用失败进入 extraction_failures。
- embedding_index 只加载本地 sentence-transformers 缓存，避免启动时联网下载。
- 新增 `memoryhub/core/fact/index_service.py`，同步 facts 到 FAISS/Milvus、BM25、runtime lookup 和搜索缓存。
- app startup 装配 FactMemoryPipeline/FactStore/FactIndexService/FactIngestionAdapter，加载存量活跃 facts；shutdown 关闭自建 facts 连接。
- SearchResponse 增加 facts；Hybrid/Milvus 检索器增加用户隔离、项目作用域和单值项目事实覆盖全局事实。
- MemoryForgetter 支持 facts ID、关键词和项目范围定位，执行 owner 校验、软删除、索引/cache 清理和孤立实体清理。
- AutoForgetEngine 将 facts 纳入健康度扫描；归档/待审查状态同步移出主检索索引，HealthCalculator 支持 ISO 时间和 observed_at。
- 修复检索器对空 runtime lookup 使用 `or {}` 导致断开共享引用的问题。

## 2026-08-03：抽取失败持久化重试与死信

### 问题

- preference、knowledge、facts 抽取失败只累计进程内计数，服务重启后无法恢复。
- 失败状态没有 owner 隔离、退避时间、尝试次数、死信或可查询状态。
- 若直接重放原始请求，可能绕过 SafetyWriteGate 后的安全事件边界。
- preference/knowledge 默认随机 ID，使失败后的重复执行可能产生重复记忆版本。

### 修改

- 新增 `ExtractionTask` 契约和 SQLite `extraction_tasks` 表；任务使用 extractor + event ID 集合生成幂等键。
- 新增 `ExtractionTaskRepository`，支持幂等 enqueue、到期 claim、运行租约恢复、指数退避、成功、死信、owner 查询和死信重置。
- 任务只保存安全事件引用及稳定 `extraction.*` 错误码，不保存事件正文、prompt、API key 或异常原文；非法错误码统一降级为 `extraction.internal_error`。
- 新增 `ExtractionExecutor`，统一首次执行与重试执行；preference/knowledge 的默认随机 ID 被映射为与任务输入和内容相关的稳定 ID，已显式指定的测试/业务 ID 保持不变。
- 新增 `ExtractionRetryService`，重试时只从 `EventRepository` 回读已经通过 quality 与 SafetyWriteGate 并持久化的安全事件，同时验证 owner 和事件集合。
- `EventIngestionService` 在三类抽取失败时幂等入队，事件接收不会回滚；同时增加同一请求批次内的 event ID 幂等检查。
- `/events` 响应新增 `extraction_failures`、`retry_tasks_enqueued`、`retry_queue_failures`。
- 新增任务查询、到期任务显式执行和死信重置 API；当前未启动隐式后台线程，避免测试和嵌入式应用产生不可控 worker。

### 验证

- 新增 `tests/test_extraction_retry.py`，覆盖 preference/knowledge/facts 失败入队、安全事件重放、成功重试、稳定 ID 幂等、半成功写入恢复、指数退避、死信、owner 隔离和缺失事件终止。
- 相关回归结果：`107 passed, 1 skipped, 57 warnings`。

## 新增/扩展测试

`tests/test_extraction_retry.py`、`tests/test_data_flow_regressions.py` 与 `tests/test_fact` 覆盖：

1. Gate MASK/REVIEW、quality reject、event_id/source_hash 幂等和碰撞；
2. preference/knowledge/facts 仅首次安全事件抽取；
3. facts 跨用户检索隔离、访问统计和项目覆盖；
4. facts 显式遗忘 owner 校验及共享索引级联；
5. facts 自动遗忘归档并移出 runtime lookup；
6. facts 旧 SQLite 迁移、作用域冲突和无外部 key 初始化；
7. preference 版本/冲突、Evidence/conflict 遗忘级联、Normalizer Schema 1.1；
8. conflict user_id 隔离和主搜索 API 回归；
9. 三类抽取失败入队、安全事件重放、指数退避、死信、用户隔离及幂等重试。

综合验证：

```text
107 passed, 1 skipped, 57 warnings
python -m compileall -q memoryhub console: passed
git diff --check: passed
```

## 明确未处理

- `tests/test_knowledge/test_knowledge_api.py`：按用户要求暂不运行；本轮未修改该用户已有改动。
- 抽取失败的持久化重试、死信和显式可观测 API 已完成；受控后台调度与并发 worker 原子 claim 尚未实现。
- 跨存储全局事务补偿、facts 独立管理/冲突审计/Evidence API、Simulator、FastAPI lifespan 迁移仍待后续处理。

## 2026-08-03 23:18 +08:00：knowledge 内部实现与算法重构

### 约束

- 保持现有 HTTP API、Pydantic/ORM 对外契约和构造接口不变。
- 保持“安全事件 → knowledge 抽取 → 统一写入/索引 → 检索/反馈/遗忘”的数据流拓扑不变。
- `SafetyWriteGate` 继续失败关闭；首次执行和重试都只读取已通过 Gate 并持久化的安全事件。
- 未运行、未修改 `tests/test_knowledge/test_knowledge_api.py` 的用户原有内容。

### 已核验问题

- 同一 session 分多次调用 `/events` 时，旧实现只抽取本次请求中的新增事件，会把一条轨迹拆成多组 workflow/case/template。
- 普通 `user_note` 等安全事件可能因宽松规则被误生成为 case/template。
- Schema 1.1 的 `MemoryEvent.tool_calls` 没有进入 knowledge 工具链。
- knowledge 缺少语义去重、原位演进和重试幂等，重复轨迹会产生重复记录或重复计数/Evidence。
- LLM 必需路径异常可能被内部 fallback 吞掉，无法进入既有 extraction retry/dead-letter 链。
- scene 查询把空 task_type 当成严格等值条件；名称搜索和使用计数缺少可选 owner 限制。
- knowledge 索引文本遗漏 steps、tools、template_body。
- LifecycleManager/AutoForgetEngine 只改 Repository，归档后的 knowledge 仍可能留在向量/BM25/lookup/cache。
- `/feedback` 只处理 preference，knowledge 的确认、修订、拒绝无法复用现有反馈链路。

### 修改

- 重写 `KnowledgeExtractor` 内部算法：
  - 事件按 `occurred_at → turn_id → event_id` 确定性排序；
  - 增加知识信号准入与轨迹完成态判断，失败、取消、超时、运行中轨迹不产出知识；
  - workflow 至少需要 2 个有效步骤；case 需要完成结果且存在步骤或工具；template 只从至少 2 步的 case 生成；
  - payload 与 Gate 处理后的安全 text 共同用于目标、结果和 Evidence 摘要；
  - 标准 tool_calls 按 sequence 读取，只纳入 success/partial 工具；
  - 从最新事件逆序提取结果，Evidence ID 按事件和摘要确定性生成；
  - LLM 实际被需要且调用失败时抛出稳定 `KnowledgeExtractionError`。
- 新增 `KnowledgeUpdater`：在相同 owner/type/兼容 scope 内，综合名称、内容和步骤相似度寻找等价 active knowledge；合并步骤、工具和 Evidence 并原位增加 version；证据集合不重叠时才增加 total_count/success_count 并调整 confidence，同一 session 轨迹跨请求补全只演进版本而不重复计数。
- `ExtractionExecutor.run_knowledge` 改为生成稳定语义 ID 并调用 `KnowledgeUpdater.add`，不再直接写入随机/批次绑定 ID。
- `EventRepository` 新增内部 `get_trajectory(user_id, session_id, task_type)`；`EventIngestionService` 在事件安全落库后加载完整轨迹；无 session_id 时保持只处理当前分组。
- `ExtractionRetryService` 以任务中的安全 anchor 事件重新加载当前完整轨迹，避免旧失败任务用过期事件集合覆盖新演进结果。
- `KnowledgeRepository.get_by_scope` 将空 scene/task_type 解释为“不限制”；`search_by_name`、`increment_usage` 增加向后兼容的可选 `user_id`。
- `MemoryWriteService.index_text` 统一包含 name、content、steps、tools、template_body；startup 与 API fallback 复用相同契约。
- `MemoryWriteService` 对 EvidenceStore 改为重写当前去重集合，使半成功重试和原位演进幂等。
- startup 在 preference/knowledge repository 上关联现有统一写服务；LifecycleManager 和 AutoForgetEngine 在不改变构造接口的情况下自动使用它同步 SQLite、向量/BM25、lookup 和 cache。
- 非 active 状态从运行时索引移除但保留持久化 Evidence；只有显式级联删除才删除 Evidence。
- 保持 `/feedback` 请求/响应接口不变，内部兼容 KnowledgeMemory：confirm 更新使用成功统计，update 更新内容与版本，reject 归档并移出运行时索引。
- 恢复反馈改造过程中被边界替换误删的 `_get_forgetter`，并按当前 MemoryForgetter 构造契约注入完整存储/索引依赖。

### 新增测试

新增 `tests/test_knowledge/test_knowledge_data_flow.py`，覆盖：

1. 普通安全事件不产出 knowledge；
2. 跨请求完整轨迹只保留一组演进后的 workflow/case/template；
3. 标准 tool_calls 进入工具链；
4. 相同 Evidence 重试不重复累计，新增 Evidence 只演进一次；
5. scene 可选过滤、名称搜索和计数 owner 隔离；
6. LLM 必需路径失败进入现有 retry queue；
7. 索引文本覆盖 steps/tools/template，自动归档移出 lookup/BM25 且保留 Evidence；
8. 现有 feedback 接口兼容 knowledge 并保持 owner 边界。

### 验证

```text
tests/test_knowledge/test_knowledge_data_flow.py: 8 passed
knowledge/data-flow/retry 组合回归: 38 passed
排除真实 LLM 测试和缺失 Milvus mock DLL 测试后的项目测试: 451 passed, 5 skipped, 61 warnings
knowledge/ingestion/memory_write 变更文件 ruff check: passed
```

完整测试结果为 `452 passed, 5 skipped`，剩余 `4 failed, 17 errors` 均由 Windows Milvus mock DLL 未编译导致；对应文件为
`third_party/kylin-mock/build/libkysdk-vector-engine-client-capi-mock.dll`。

### 保留边界

- 对外接口和数据流拓扑未改变；本轮调整集中在 knowledge 的准入、排序、抽取、去重、演进、幂等和索引同步算法。
- 当前语义等价判断使用规则化字符串和步骤集合相似度，尚未引入 embedding 聚类、冲突审计或离线阈值评测。
- 无 session_id 的事件无法跨请求重建轨迹，继续按当前请求分组处理。
- 跨 SQLite、Evidence、向量/BM25 的全局事务/补偿协议仍未实现；现有统一写服务和持久化重试提供最终一致性修复路径。

## 2026-08-04：跨存储事务补偿协议（B20 修复）

### 问题

- SQLite、FAISS、Evidence 三个独立存储之间没有事务保证。如果写入 SQLite 成功但 FAISS 失败，已写入 SQLite 的记录无法回滚，产生"幽灵数据"——SQLite 有但 FAISS 搜不到，或 FAISS 搜到但 SQLite 已删除。
- 删除同理：先删 SQLite 再删 FAISS，中间失败会造成两边不一致。
- 现有 `MemoryWriteService` 只是顺序写入，没有补偿逻辑。

### 修改

- 新增 `memoryhub/storage/transaction.py`：`StorageTransaction` 补偿式事务管理器。
  - `on_failure(undo)` 注册回滚操作，按注册的逆序执行。
  - 支持 `with StorageTransaction("name") as tx:` 上下文管理器，异常自动回滚。
  - 回滚本身失败时记录错误日志但不吞掉原始异常。
  - 不是 ACID 事务——补偿是"尽力撤销"，补偿失败意味着需要人工介入或后续一致性检查修复。
- `memoryhub/storage/database.py`：`PreferenceRepository` 和 `KnowledgeRepository` 各增加 `delete_by_id(memory_id) → bool` 方法，用于回滚时物理删除。
- 用法示例：

```python
with StorageTransaction("write_pref") as tx:
    pref_repo.save(memory)
    tx.on_failure(lambda: pref_repo.delete_by_id(memory.memory_id))

    vector_store.add(memory.memory_id, vec)
    tx.on_failure(lambda: vector_store.delete(memory.memory_id))

    evidence_store.save(memory.memory_id, ev)
    tx.on_failure(lambda: evidence_store.delete(memory.memory_id))
```

### 新增测试

新增 `tests/test_storage_transaction.py`，覆盖：

1. 全部成功 → 不触发回滚；
2. FAISS 失败 → SQLite 被回滚；
3. Evidence 失败 → SQLite + FAISS 都被逆序回滚；
4. with 语句中抛异常 → 自动回滚 + 异常透传；
5. with 语句正常退出 → 不回滚；
6. Knowledge 写入中间失败 → Knowledge + FAISS 回滚；
7. 回滚本身失败 → 记录日志但不影响其他回滚继续执行。

### 验证

```text
tests/test_storage_transaction.py: 7 passed
```

### 保留边界

- 补偿不是 ACID 事务——如果在回滚过程中进程崩溃，部分数据可能已不一致。生产环境需要配合 `verify_integrity()` 定期校验和修复。
- 跨存储全局两阶段提交或 Saga 编排仍未实现；当前补偿机制提供单次写入/删除路径的最终一致性。
