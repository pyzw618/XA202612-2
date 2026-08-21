# MemoryHub 数据流修复更新记录

> 文件位置：`docs/tests/0805数据流测试/DATA_FLOW_UPDATE.md`  
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

## 2026-08-04 14:50 +08:00：dev_dataflow 分支数据流回归修复

### 背景

同伴提交（基线合并提交 `5c0a526`，当前审查基线 `095e19f`）补充了数据流相关实现，但没有同步变更说明。本次在 `dev_dataflow` 分支逐项复核代码和运行时装配，确认并修复了以下问题；对外接口、请求/响应结构和主数据流拓扑保持不变。

### 修复内容

1. **生产检索的 owner/status 隔离**：Milvus hybrid search 增加 `user_id`、`status=active` 过滤；回表阶段再次以 runtime lookup/SQLite owner 和状态 fail-closed 校验，防止底层过滤器未生效时跨用户或归档记忆泄漏。
2. **Knowledge 遗忘的 owner 校验与级联状态**：移除重复且不安全的 `KnowledgeRepository.update_status` 实现；遗忘链路传递 `user_id`，并在向量索引级联删除成功后清除 preference/knowledge 的 `pending_index`。
3. **active/inactive pending 补偿分流**：`pending_index=True` 的 active 记忆执行 upsert，archived/deleted 记忆执行 delete，避免已归档记忆被后台补偿重新写回检索索引。状态变更同步进入 pending。
4. **删除失败的 tombstone 与重试边界**：向量删除失败时保留 inactive 状态、`pending_index` 和共享 lookup tombstone，使生产检索优先 fail-closed；删除成功后才移除 lookup 并清除 pending。
5. **Knowledge 索引文本完整化**：统一使用 `MemoryWriteService.index_text()`，索引文本覆盖 name、content、steps、tools、template_body，避免只按标题/正文检索时漏掉知识步骤、工具和模板。
6. **显式写入与主写入统一投影**：`MemorySyncService` 在应用装配中委托现有 `MemoryWriteService`，显式写入、主事件写入和 pending 补偿复用相同的 SQLite、向量/FAISS、BM25、lookup、cache 和 metadata 契约。
7. **development/test 的 BM25/FAISS 装配修复**：提前创建并共享 `KeywordSearcher`，注入 FactIndexService、MemoryWriteService、HybridRetriever 和同步服务，避免显式写入只落 SQLite/FAISS 而不更新 BM25 或 lookup。
8. **空 lookup 引用与 fallback metadata**：保留调用方传入的空字典引用；补齐 status metadata，使启动时的 lookup 投影和 API fallback 与生产写入契约一致。

### 新增回归测试

新增 `tests/test_data_flow_merge_regressions.py`，覆盖 8 个场景：Milvus owner/status fail-closed、共享空 lookup、Knowledge owner 遗忘和索引级联、主写入 pending 清除及完整 knowledge 文本、inactive pending delete 分支、development 显式写入同步 FAISS/BM25/lookup、missing/foreign 删除失败、向量删除失败时 pending 与 tombstone 保留。
同时更新 `tests/test_milvus_hybrid_retriever.py` 的 fake search 契约，使测试明确传递 `user_id` 和 filters。

### 验证结果

未运行 `tests/test_knowledge/test_knowledge_api.py`，因为该测试会真实调用 LLM。其余本轮数据流组合回归结果：

```text
118 passed, 29 warnings
python -m compileall -q memoryhub: passed
```

包含原生 sync/runtime 测试的集合仍有 4 个失败、7 个错误，均被 `embedding.mock_unavailable` 阻塞；仓库缺少 Kylin embedding/Milvus mock 的原生动态库构建产物，并非本轮 Python 修改引入的失败。

### 保留边界

本轮补齐的是 preference/knowledge 运行时投影的 owner 隔离、状态分流和最终一致性补偿；facts、Evidence、审计以及跨事件库/多索引的全局事务补偿协议仍未统一，抽取 retry 仍主要由显式 API 驱动。这些项目已在 `docs/tests/0805数据流测试/DATA_FLOW_REVIEW.md` 的后续优先级中保留。

## 2026-08-04 16:10 +08:00：剩余数据流问题集中修复

### 修改策略

按协作约定，本轮先集中完成剩余问题修改，再统一执行编译和测试；未运行会真实调用 LLM 的 `tests/test_knowledge/test_knowledge_api.py`。

### 修改内容

1. **facts 投影补偿闭环**
   - facts 表增加 `pending_index`、`index_version` 及兼容迁移；新写入和状态变化先标记 pending。
   - `FactIndexService` 统一 active upsert 与 inactive delete，覆盖 Milvus/FAISS、BM25、lookup 和 cache；成功后才清除 pending。
   - 后台 `PendingIndexCompensationTask` 同时扫描 preference、knowledge 和 facts。
   - 删除失败时保留 inactive fact tombstone 和 pending，防止旧投影重新可见。

2. **facts 管理、Evidence 和冲突审计**
   - 新增 `fact_evidence`、`fact_conflicts` 持久化表，事实提交时幂等记录来源 Evidence 和冲突裁决。
   - 新增 facts 列表、详情、Evidence、冲突列表和 owner-scoped 删除 API。
   - 显式遗忘级联删除事实 Evidence/冲突，并在投影成功后清除 facts pending。

3. **抽取 retry 后台调度和指标**
   - 新增可配置 `ExtractionRetryTask`，支持启动/停止、批量限制、周期扫描和运行指标。
   - `claim_due` 改为带 due 条件的原子 UPDATE，多个 worker 不再无条件领取同一任务。
   - lifespan 启停 worker，并增加只返回计数/稳定错误码的指标接口。

4. **knowledge 合并配置、冲突审计和离线评测**
   - 新增 `KnowledgeMergeConfig`，可配置 name/content/steps 权重、等价阈值和歧义阈值。
   - 等价候选继续原位演进；位于歧义区间的知识分别保存并写入 owner-scoped `ConflictRecord`。
   - 新增 `evaluation/knowledge_merge_cases.json` 和离线评测 helper。

5. **冲突子系统清理**
   - `core/conflict/detector.py` 和 `resolver.py` 的 `NotImplementedError` 已全部替换为确定性 owner/scope 检测、语义冲突判断、override/merge/coexist/pending 策略和可选持久化。
   - `ConflictRepository.save` 改为按 `conflict_id` 幂等更新，避免重试产生主键冲突。

6. **console、Simulator 和 lifespan**
   - console 的 PreferenceMemory、mock 偏好数据和表格读取统一使用后端标准字段 `text`。
   - Simulator 补齐 Schema 1.1 的 source_hash、quality、payload/tool_calls，并生成同 session 的 input → tool → completed 有序轨迹。
   - FastAPI 从 `on_event` 迁移到 lifespan；后台抽取 retry、pending 补偿和资源释放统一由 lifespan 管理。

7. **删除链路的 Evidence/conflict 补偿**
   - preference/knowledge 的 `deleted` 状态在 pending 补偿成功时也会幂等删除 Evidence 和关联 conflict；归档状态仍保留 Evidence。
   - facts 删除同步清理 fact Evidence/conflict 和孤立实体。

### 新增测试

新增 `tests/test_remaining_data_flow_regressions.py`，覆盖：

- retry worker 指标；
- facts 投影失败保留 pending 并成功补偿；
- knowledge 歧义候选写入 owner-scoped conflict；
- conflict owner/scope 边界；
- Simulator 完整有序轨迹；
- FastAPI lifespan 装配。

### 统一验证

```text
python -m compileall -q memoryhub console: passed
环境无关测试集合: 529 passed, 5 skipped, 1 deselected
新增/数据流/facts/knowledge/retry/app 组合回归: 99 passed, 1 skipped
git diff --check: passed
```

完整测试仍会被仓库缺失的 Kylin embedding 和 Milvus mock DLL 阻塞；最新完整尝试为 `527 passed, 5 skipped, 14 failed, 28 errors`，失败集中在 native mock/benchmark/milvus-mock 集合和依赖该 mock 的稳定超时用例，不是本轮 Python 数据流实现回归。

### 剩余架构边界

- 系统已有三类记忆的最终一致性投影补偿，但事件库、安全审计日志和各记忆库之间仍不是一个全局 ACID 事务；安全审计保持 append-only 和 fail-closed，不参与遗忘物理删除。
- knowledge 当前仍使用规则化字符串/步骤集合相似度，尚未引入 embedding 聚类、多语言语义模型和大规模离线阈值标定。
- retry 指标当前为进程内快照，尚未持久化到监控系统；SQLite 条件 claim 可保护共享数据库任务，但还未提供跨节点租约指标和告警。

## 2026-08-04：补偿指标与收尾核验

- 修复 `PendingIndexCompensationTask` 指标只统计 preference/knowledge、忽略 facts 失败的问题；现在会合并三类投影的成功/失败数量，并在 facts 投影异常时继续完成本轮统计。
- 为补偿任务指标快照增加线程锁，避免后台 worker 与 metrics API 并发读取时出现不一致；补齐 `last_run_at`、`last_duration_ms` 和稳定错误标记。
- 清理 API 中未使用的 `FactMemory` 导入，并更新抽取任务接口说明，使其反映已启用的后台 retry worker。
- 新增回归测试覆盖 facts 投影失败计数；数据流相关组合回归更新为 `99 passed, 1 skipped`。

## 2026-08-04：Knowledge 提取、置信度与版本更新优化

### 提取流程

- 对输入事件先做安全模型归一化、质量阈值过滤和 `event_id` 去重；重复事件保留质量更高的版本，避免重复证据污染知识统计。
- 按 `user_id + session_id + task_type` 隔离轨迹，避免调用方误传多个会话时发生跨用户/跨任务知识串联。
- 步骤去重改为规范化 key 去重，减少中英文标点、编号格式差异造成的重复步骤。
- 保留规则优先、LLM 兜底的既有接口和数据流，不改变 `KnowledgeExtractor` 的公开方法。

### 置信因子算法

新增 `memoryhub/core/knowledge/confidence.py`，将置信度拆为事件质量、完成度、结构完整性、证据覆盖、结果明确度和工具链一致性六个因子；通过加权分数和最弱因子惩罚，避免单个高质量字段掩盖失败工具调用或证据不足。

Knowledge 合并时不再使用简单的 confidence 平均值，而是结合既有/新增置信度、成功/总调用的 Beta 风格可靠性估计、支持次数和独立证据数量进行平滑更新。模板置信度也基于案例置信度、步骤泛化程度和证据量重新计算。

### 版本更新

- KnowledgeUpdater 对完全重复输入执行 no-op，不再无意义地写库、递增版本或触发索引同步。
- 只有出现新增证据或语义字段变化时才递增 version。
- KnowledgeRepository 新增 `knowledge_versions` 不可变快照表；当当前版本演进时先保存旧版本，支持通过 `get_version_history()` 读取版本链。
- 修复模板更新的自引用 `parent_id`，模板版本现在指向产生它的案例 ID，而不是指向自身。

### 验证

```text
knowledge/data-flow/optimization 回归: 27 passed
新增 Knowledge 优化测试: 4 passed
python -m compileall -q memoryhub: passed
ruff check 新增 confidence/test 代码: passed
```
## 2026-08-04：补齐 Knowledge 结构化 LLM 兜底

### 现状核验

原 Knowledge 流程已经存在三处 LLM 兜底：

- 目标过长或缺失时调用 `_llm_summarize_goal()`；
- 结构化步骤不足两条时调用 `_llm_extract_steps()`；
- 模板步骤过多时由 `TemplateBuilder` 调用 LLM 做泛化和去重。

但原流程存在一个缺口：当轨迹缺少 result、goal 或多个结构化字段时，`extract_from_trajectory()` 可能在进入统一提取前直接返回空结果，无法使用 LLM 补全。

### 本次修改

- `KnowledgeExtractor` 新增统一的结构化 LLM enrichment 兜底。
- 当轨迹缺少目标、步骤不足或缺少结果时，调用一次 `generate_json()`，请求补全：
  - `goal`
  - `steps`
  - `tools`
  - `result`
- LLM 返回内容只写入当前安全事件的 payload 副本，不修改原始事件，不改变事件库数据流。
- `extract_from_trajectory()`、`extract_workflow()`、`extract_case()` 统一经过该兜底路径。
- LLM 调用异常返回稳定错误码 `knowledge.enrichment_llm_failed`，非法 JSON 返回 `knowledge.enrichment_invalid`，可继续进入既有 extraction retry/dead-letter 链路。
- LLM 仅在轨迹确实缺少结构化信息时触发，完整结构化轨迹不会额外调用 LLM。

### 验证

```text
Knowledge LLM fallback/data-flow 回归: 13 passed
新增 LLM enrichment 回归: 1 passed
ruff check extractor/test: passed
```

## 2026-08-08：安全事件持久化与规则解析器兼容修复

### 背景

本轮在接入 opencode（见 `opencode-integration/docs/INTEGRATION.md`）时，对
`POST /api/memory/events` 的完整链路做了端到端验证，发现两个与数据流相关的缺陷：
一条通过 SafetyWriteGate 的安全事件（`ALLOW/MASK`）在落库时必然报错；同时内置
安全规则库在 Python 3.10 及更早版本上无法加载。两者均不修改对外接口与数据流拓扑。

### 问题一：Gate 放行的安全事件无法持久化（`TypeError: Object of type _ImmutableMapping is not JSON serializable`）

- **现象**：`POST /api/memory/events` 写入无敏感内容的事件时返回
  `503 {"detail":"event ingestion failed"}`；根因是
  `EventRepository.batch_save` → `_to_row` 抛 `TypeError`。
- **根因**：`SafetyResult.sanitized_event` 是深度只读的 `_SafeMemoryEvent`
  （`memoryhub/adapter/schemas.py`），其 `payload`/`redactions` 被冻结为
  `_ImmutableMapping`/tuple；`EventRepository._to_row`
  （`memoryhub/storage/database.py`）直接把 `event.payload` 交给 SQLAlchemy JSON 列
  序列化。`json.dumps` 不能序列化非 `dict` 的 `Mapping` 子类，因此**每条**
  `ALLOW/MASK` 的干净事件都失败；仓库现有 `/events` 相关测试只覆盖被拒绝的事件，
  未触达该路径，缺陷未被发现。
- **修改**：`EventRepository._to_row` 改为先 `event.model_dump(mode="json")` 投影回
  普通 JSON dict/list 再构造 `EventRow`。这与 `schemas.py` 中“`model_dump()` 仍投影
  为普通 JSON dict/list，保持持久化格式兼容”的既有契约一致，同时兼容普通
  `MemoryEvent` 与 Gate 放行的 `_SafeMemoryEvent`。

### 问题二：内置安全规则库在 Python 3.10 及更早版本无法加载

- **现象**：`load_builtin_rule_set()` 抛
  `RuleLibraryError: Python regex safety parser is unavailable`，
  `memoryhub/app.py` 导入即失败。
- **根因**：`memoryhub/safety_rules/regex_safety.py` 只从
  `re._parser`/`re._constants` 导入解析器。该别名是 Python 3.11 才引入的；Python 3.10
  及更早（含本机 Anaconda 环境）只有 `sre_parse`/`sre_constants`，两个别名导入失败后
  `sre_parser=None`，规则解析门禁按 fail-closed 拒绝全部规则。
- **修改**：`regex_safety.py` 增加兼容回退：优先 `re._parser`/`re._constants`
  （3.11+），导入失败时回退到 `sre_parse`/`sre_constants`（3.10 及更早）；仅当两者
  都不存在时才置 `None` 失败关闭，保留原有的 fail-closed 语义。

### 验证

```text
# 修复后在本机 Python 3.10.20（无任何补丁）上：
内置规则库原生加载: version=1.0, rules=14
POST /api/memory/events（干净事件）: 200 {"accepted":1,"event_ids":[...]}
safety/scanner/contract/ingestion 组合回归: 165 passed
gate/pipeline/audit/dataflow/retry 组合回归: 140 passed, 4 skipped
opencode-integration MCP 集成测试: 8 passed；plugin 单测: passed
```

仍失败项均为既有的环境依赖问题，与本次修改无关（已在历史记录中标注）：Kylin
embedding/Milvus mock 原生 DLL 缺失导致的 `embedding.mock_unavailable` 与
`embedding.unavailable` 类用例。

### 保留说明

`opencode-integration/scripts/memoryhub_compat.py` 中的运行期兼容补丁（`re._parser`
shim 与 `EventRepository.save/batch_save` 归一化）在本次源码修复后不再必需，仅作为
针对旧版本 checkout 的兜底保留；新代码应直接依赖本文件的源码修复。
