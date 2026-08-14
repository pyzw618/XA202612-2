# Core 记忆模块统一化改造记录

> 修改日期：2026-08-14
> 对应方案：`docs/CORE_MEMORY_REFACTOR_PLAN.md`
> 改造原则：保持现有 API、Schema、仓储和 Fact 管线公开方法不变，仅增加内部统一编排能力。

## 本次完成内容

### 1. 新增统一内存核心模块

新增 `memoryhub/core/memory/`：

- `base.py`
  - `MemoryCandidate`：统一的内部候选载体；不替代 `Fact`、`PreferenceMemory`、`KnowledgeMemory`。
  - `MemoryDecision`：统一 `new / update / coexist / duplicate / review / reject` 决策。
  - `BaseMemoryHandler`：固化 `extract → evidence merge → similar match → confidence → decision → apply` 处理顺序，并提供 `process_and_apply()`。
- `confidence.py`
  - `ConfidenceFactors`：`source`、`quality`、`support`、`freshness` 四个标准因子。
  - `UnifiedConfidenceCalculator`：采用方案中的加权平均和弱项保护公式；置信度上限为 `0.95`。
  - 证据支持度使用 1、2、3+ 分档，重复重试不会无限提高置信度。
- `evidence.py`
  - `EvidenceMerger`：兼容字典和既有 Evidence 对象。
  - 优先按 `event_id + evidence_id` 去重；缺少 ID 时按 `source_id + content hash` 去重。
  - 按时间稳定排序、默认最多保留 20 条证据，并提供统一摘要。
- `llm.py`
  - `StructuredLLMAdapter`：直接包装应用级 `BaseLLMClient.generate()` 调用约定，统一 JSON 解析和错误语义，不改变现有 LLM 客户端接口。

### 2. 新增三类 Handler

新增下列内部 Handler，分别复用现有领域对象和写入逻辑：

- `memoryhub/core/fact/handler.py`：复用 `FactMemoryPipeline` 和 `FactIngestionAdapter`；提交前以统一决策控制低置信候选。
- `memoryhub/core/preference/handler.py`：复用 `PreferenceExtractor` 与 `PreferenceUpdater`。
- `memoryhub/core/knowledge/handler.py`：复用 `KnowledgeExtractor` 与 `KnowledgeUpdater`。

这些 Handler 不修改 REST API 输入输出，也不迁移既有存储表。现有生产入口可以分阶段切换到 `process_and_apply()`。

### 3. Fact 事件时间与工具上下文修正

修改 `memoryhub/core/fact/event_adapter.py` 与 `memoryhub/core/fact/pipeline.py`：

- 将 `MemoryEvent.occurred_at` 保存在 Fact proposal metadata。
- 创建 Fact 时优先使用事件发生时间写入 `Fact.observed_at`；仅在事件时间为空时才回退至当前提交时间。
- 在工具调用格式中将调用参数标为“仅上下文，不可作为事实依据”，保留工具返回结果作为可抽取证据。
- 保留 `event_id` 到 Fact proposal metadata，便于统一证据归并和后续审计。

## 兼容性说明

- 未改动 `MemoryEvent`、`PreferenceMemory`、`KnowledgeMemory`、`Fact` 的公共字段。
- 未改动 REST 请求/响应契约。
- 未改动 `FactMemoryPipeline.propose()`、`commit()`、`ingest()` 的签名。
- 未改变已有 repository、索引同步和安全写入服务的公开调用方式。
- 原有偏好、知识置信度实现暂时保留为兼容路径；新增 Handler 使用统一置信度计算器。后续可在完成入口收敛后，将旧计算器改为兼容包装。

## 新增测试

新增 `tests/test_core_memory_unification.py`，覆盖：

1. 证据重试去重与时间排序；
2. 3+ 证据支持度封顶，避免重复证据抬升置信度；
3. `BaseMemoryHandler` 的统一处理链；
4. `StructuredLLMAdapter` 对应用级 `generate()` 契约的调用和 JSON 解析。

## 验证结果

执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_core_memory_unification.py tests\test_preference_functionality.py tests\test_ingestion_schema.py tests\test_knowledge\test_knowledge_optimization.py
```

结果：`31 passed`。

## 后续建议

1. 在 `ExtractionExecutor` 中按 Feature Flag 或分类型逐步启用三个 Handler，保证 ID 生成和幂等逻辑与现有路径完全一致后再切换默认入口。
2. 将 `preference/confidence.py`、`knowledge/confidence.py` 收敛为对 `UnifiedConfidenceCalculator` 的兼容包装，并保留旧方法名。
3. 将 Fact 的 `TripleExtractor`、实体/谓词归一化及冲突裁决逐步改为直接依赖 `StructuredLLMAdapter`，随后删除事实子模块内的 OpenAI Chat Completions 兼容层。
4. 基于真实数据决定是否需要把 `evidence_summary` 写入 metadata；本次未改表、未迁移历史证据。

---

## 第二轮接入记录（2026-08-14）

本轮完成了首轮遗留项的主链路接入：

1. **Handler 已接入正式抽取执行器**：`ExtractionExecutor` 现在可接收并优先使用 Fact、Preference、Knowledge Handler；应用初始化会构造并传入这些 Handler。原有 extractor/updater 参数仍保留，作为兼容回退。
2. **统一证据合并进入旧写入路径**：`PreferenceUpdater` 与 `KnowledgeUpdater` 的证据合并改为复用 `EvidenceMerger`，确保非 Handler 调用同样具备稳定去重、排序和条数上限。
3. **Fact 时间回退可审计**：`FactMemoryPipeline` 优先使用 proposal 的 `occurred_at`；无事件时间时用提交时间，并在 `source_id` 添加 `recorded_at_fallback:` 前缀。
4. **Fact 三元组提取接入应用级 LLM 调用**：传入实现 `generate()` 的应用 LLM client 时，`TripleExtractor` 直接通过 `StructuredLLMAdapter` 调用，不依赖事实模块的模型或端点配置。
5. **工具参数污染约束落地**：工具调用格式将调用参数标明为仅上下文、不可作为事实依据。

新增/扩展测试覆盖：

- 应用级 LLM client 的 Fact 三元组提取；
- Fact 的事件时间优先级与 `recorded_at_fallback` 标记；
- 原有统一 Handler、证据去重和置信度封顶测试。

本轮验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_core_memory_unification.py tests\test_fact tests\test_data_flow_regressions.py tests\test_knowledge\test_knowledge_data_flow.py tests\test_api_acceptance.py tests\test_competition_api.py
```

验证结果：`105 passed, 2 skipped`。

---

## 第三轮收敛记录（2026-08-14）

本轮完成剩余的内部逻辑收敛：

1. `Preference` 旧 `ConfidenceCalculator` 已保留公开方法名，但 `calculate()` 现在先通过 `EvidenceMerger` 整理证据，再委托 `UnifiedConfidenceCalculator` 计算最终分数。
2. `KnowledgeConfidenceCalculator` 的抽取、合并和模板评分方法已改为把既有领域因子映射到四个统一因子后调用 `UnifiedConfidenceCalculator`。
3. Fact 的实体归一化、谓词归一化和别名生成在传入应用级 LLM client 时，已改为使用 `StructuredLLMAdapter`；历史 Chat Completions 兼容分支仅作为未传入应用级 client 时的降级路径。
4. Fact 冲突裁决同样优先通过 `StructuredLLMAdapter` 执行结构化 JSON 校验和调用；无应用级 client 时维持兼容降级行为。

验证范围包括 Fact、偏好和知识模块的相关单元测试与静态检查。

---

## 第四轮跨模块联动优化（2026-08-14）

本轮将记忆生命周期与检索、遗忘和索引投影联动：

1. 新增 `memoryhub/core/memory/freshness.py`，提供统一的时间解析与 `[0, 1]` 新鲜度计算；Fact、Preference、Knowledge 的半衰期分别为 30、60、90 天。
2. `Reranker` 现在将融合分数、相关性、scope、confidence、freshness 与 health 共同用于排序，并在检索 metadata 中保留各分项，便于审计。
3. `MemoryWriteService` 和 `FactIndexService` 索引 metadata 补充质量、时间和证据数量，使检索重排可以使用写入链路产生的生命周期信息。
4. `AutoForgetEngine` 支持注入 `MemoryWriteService`；偏好与知识被归档、待审或降级时，数据库、向量/关键词索引、运行时 lookup 与缓存通过同一写入服务同步更新，避免遗忘后仍被检索到的投影残留。
5. 管理端自动遗忘 API 已传递应用级 `memory_write_service`。

新增测试覆盖统一 freshness 的范围、按记忆类型的半衰期差异，以及重排写入 confidence/freshness/rerank 审计分数。

---

## 第五轮更新决策优化（2026-08-14）

本轮调整三类记忆的“相似输入”处理顺序，优先保留既有语义与证据链：

1. **Preference**：候选匹配改为同时要求偏好类型、scope 和结构化 `target` 可比较，避免仅凭同类型/同场景拿到任意旧偏好。决策顺序改为先判断内容一致或兼容，再判断显式冲突；相同 target/value 的复合输入会原地补充 evidence、更新 confidence，而不覆盖原偏好文本或创建错误版本。
2. **Knowledge**：语义未变化但新增独立 evidence 时，保留当前活跃知识的语义内容与稳定 ID，仅合并证据、更新支持统计和 revision；语义发生变化时创建后继版本，设置 `parent_id`，归档旧版本后写入新版本。
3. **Fact**：同一主体/谓词/客体的重复事实不再丢弃新来源；新来源 evidence 会绑定到保留的既有 Fact。真实冲突仍按照原有冲突裁决创建/保留对应事实状态。

新增回归测试覆盖“相似但包含额外内容”的偏好输入不会覆盖原偏好，以及重复 Fact 会在保留事实上新增 evidence。
