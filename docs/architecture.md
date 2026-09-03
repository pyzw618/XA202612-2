# 系统架构

> 本文描述 Kylin MemoryHub 的**当前实现**（vNext 主链路为默认）。所有模块路径以仓库源码为准；vNext 权威规范见 [vnext/spec/](vnext/spec/)，架构决策见 [vnext/design/ADR-vnext-memory-architecture.md](vnext/design/ADR-vnext-memory-architecture.md)。

## 1. 设计原则

1. **SQLite 是唯一事实源**：向量索引、BM25 关键词索引、检索缓存全部是**派生数据**，可随时从 SQLite 重建（`scripts/rebuild_projections.py`）。
2. **Authority 单写者**：任何长期记忆的生产写入必须经过 Canonical Write → Authority 仓储的单事务边界（记忆正文 + 谱系 + 证据 + 投影 Outbox 同事务落库），不存在旁路写路径（由 `tests/test_no_production_write_bypass.py` 守护）。
3. **投影异步化**：写入事务只承诺持久 Outbox；向量/关键词/缓存投影由后台 `ProjectionOutboxWorker` 异步完成，失败进入补偿队列。
4. **安全前置**：所有内容先过安全门禁（检测 → 脱敏 → ALLOW/MASK/REVIEW/REJECT 决策），REVIEW 进隔离区，REJECT 拒绝，全过程哈希链审计。
5. **可灰度、可回滚、可观测**：新旧链路通过五级切流共存，每一步有零容忍门禁与只读回滚；全链路脱敏 Trace 持久化。
6. **端侧轻量化**：本机常驻 FastAPI 服务 + ctypes 直连麒麟 C SDK，无重型中间件依赖；生产检索目标 P95 ≤ 350ms、P99 ≤ 500ms。

## 2. 分层视图

```
┌────────────────────────────────────────────────────────────────────┐
│ 接入层   OS Agent · Qt 桌面控制台 · CLI · MCP · OpenCode 插件 · SDK   │
│          (agent-integration/ · desktop-client/)                     │
├────────────────────────────────────────────────────────────────────┤
│ REST 适配层  memoryhub/adapter/ — FastAPI 6 组 Router               │
│   /api/memory/vnext (vnext_api)      ← vNext 统一入口                │
│   /api/memory       (api)            ← 标准接口（写入默认转发 vNext） │
│   /api/memory       (management_api) ← 后台管理面                    │
│   /api/memory/v2    (memory_v2_api)  ← 谱系/证据/投影溯源只读        │
│   /api/agent · /api (agent_api)      ← Agent 演示适配                │
│   schemas.py / vnext_schemas.py      ← Pydantic DTO（唯一契约）      │
├────────────────────────────────────────────────────────────────────┤
│ vNext 应用层  memoryhub/application/（23 个服务模块）                │
│   写入: event_gateway · canonical_write · formation_worker          │
│         boundary_detector · working_service/reducer · episode_*     │
│         reflection_service · candidate_service · consolidation_*    │
│   读取: retrieval_service · context_service · shadow_read_service   │
│   反馈: feedback_service · evolution_service                        │
│   治理: rollout_service · forget_service · diagnostic_service       │
│         dashboard_service · safety_policy_adapter · formation_shadow│
├────────────────────────────────────────────────────────────────────┤
│ 领域层  memoryhub/domain/（vNext 领域词汇与契约）                    │
│   contracts · candidate · working · episode · long_term · evolution │
│ 领域核心  memoryhub/core/（被 vNext 应用层复用的领域实现）           │
│   ingestion(含 tool_result/behavior/config 三源适配器) · preference │
│   knowledge · conflict · forget · safety · lifecycle · memory 基元  │
│   reflection · memory_write · domain_writer · processing            │
├────────────────────────────────────────────────────────────────────┤
│ 检索通道  memoryhub/retrieval/                                      │
│   intent_router · planner · vector_search · keyword_search          │
│   milvus_hybrid(生产) · hybrid(dev/test) · fusion(RRF) · reranker   │
│   scope_resolver · context_builder · cache(双层 LRU)                │
├────────────────────────────────────────────────────────────────────┤
│ 存储层  memoryhub/storage/                                          │
│   database+models(SQLite/SQLAlchemy 仓储) · authority_repository    │
│   vnext_repositories · memory_metadata(谱系/证据/outbox 仓储)       │
│   projection_outbox(durable worker) · compensation_task · repair    │
│   sync_service(漂移对账) · vector_engine(faiss/milvus/sparse)       │
├────────────────────────────────────────────────────────────────────┤
│ 横切设施                                                            │
│   observability/  脱敏 Trace(五链) · 指标 · 审计存储                 │
│   embedding/      麒麟 SDK(ctypes+DBus,768维) · mock                │
│   llm/            OpenAI 兼容客户端（语义裁决辅助，可降级规则）      │
│   safety_rules/   版本化声明式规则库(builtin-1.0 JSON)              │
│   config.py       dataclass 配置 · 生产双层门禁 · vNext 切流        │
└────────────────────────────────────────────────────────────────────┘
```

应用组装在 `memoryhub/app.py:create_app()`（模块级 `app = create_app()`），lifespan 中启动后台组件：MemoryService、FormationWorker、抽取重试任务、生命周期调度器、Projection Outbox Worker、投影补偿任务、Rollout 控制器与持久化 Trace/指标存储。

## 3. 写入链路（Formation）

```
事件源（工具结果/用户行为/手动配置）
  → 源适配器 core/ingestion/adapters/*（结构化、字段校验）
  → 清洗 Cleaner → 标准化 Normalizer（MemoryEvent, Schema 1.1, source_hash 幂等）
  → 质量评分 QualityScorer → 安全门禁 SafetyWriteGate（ALLOW/MASK 放行；REVIEW 隔离；REJECT 拒绝）
  → EventGateway（application/event_gateway.py，租户/策略校验）
  → CanonicalWriteService（application/canonical_write.py）
      ├─ BoundaryDetector：会话/任务边界检测，驱动工作记忆归约
      ├─ WorkingReducer → 工作记忆（短期）
      ├─ EpisodeService/Enricher → 情景记忆（中期）
      └─ 可重试 extraction task（持久化任务状态，支持 /tasks/{id}/resume）
  → FormationWorker（reflection → candidate → consolidation）
      ├─ ReflectionService：结构化反思（LLM，schema 约束）
      ├─ CandidateService：候选记忆 + 证据幂等落库
      └─ ConsolidationService：证据阈值满足后经 Authority 单写者固化为长期记忆
```

- `vnext.formation_mode` 控制形成链姿态：`shadow`（只观察）/ `candidate-only`（产候选不固化）/ `authority`（默认，沉淀到长期 Authority）。
- 标准写入口 `POST /api/memory/events` 与 `/sources/*` 在 `vnext.events_default=true`（默认）时路由到 vNext canonical write（`adapter/api.py:_should_use_canonical_write`）。
- 决策面统一为 8 动作（new/update/duplicate/coexist/reject/review 等，`core/memory/base.py`），冲突消解矩阵在 `core/conflict/`。

## 4. 读取链路（Retrieval & Context）

```
查询 → IntentRouter（意图识别：任务历史/偏好/知识等模式）
     → RetrievalPlanner（通道选择与预算规划）
     → 通道执行器：working / episode / vector / keyword / metadata / authority
         · 生产向量通道：MilvusHybridRetriever（稠密+稀疏，RRF 融合）
         · dev/test 降级：HybridRetriever（FAISS IndexFlatIP + rank-bm25/jieba）
     → ReciprocalRankFusion → VNextReranker（多因子加权：相关度/置信度/新鲜度…）
     → ScopeResolver（scene/task_type/project 作用域与租户隔离）
     → BudgetManager（上下文预算裁剪）
     → ContextPayload（/context 装配返回）
```

- 缓存：查询向量 LRU 缓存 + 检索结果 LRU+TTL 缓存（索引版本隔离）。
- `vnext.mode` 决定读路径姿态：`vnext`（默认，直接返回 RetrievalService 结果）/ `canary`（稳定哈希按 `canary_percent` 分流）/ `dual-read`（双读对比，返回 legacy 结果）/ `shadow`（legacy 结果 + vNext 旁路观察）/ `legacy`（回滚）。

## 5. 反馈与演化（记忆越用越准）

```
使用信号（feedback_service.py，5 类）
  INCLUDED / REFERENCED / ACTION_INFLUENCED / OUTCOME / CORRECTION
  → 脱敏归因（只存记忆 ID 哈希与 Trace 元数据，不存正文）
  → 效用提案（确定性、非权威，不直接改 Authority）
  → EvolutionService 演化决策（domain/evolution.py）
      REINFORCE（强化置信）/ REVISE（修订）/ SUPERSEDE（新版替代）
      / COEXIST（并存）/ REVIEW（人工复核）
  → 演化状态机：ACTIVE / DORMANT / SUPERSEDED / ARCHIVED / DELETED
```

入口：`POST /api/memory/vnext/feedback`、`POST /api/memory/feedback`。

## 6. 记忆分层与生命周期

| 层 | 存储 | 机制 |
|---|---|---|
| 短期（工作记忆） | working 表 + vNext working 仓储 | TTL 默认 24h（`memory_tier.short_ttl_hours`），事件流实时归约 |
| 中期（情景记忆） | short/mid_term 表 + episode 仓储 | 会话汇总（session_consolidator），边界检测驱动 |
| 长期（偏好/知识） | preferences / knowledge + Authority | 证据阈值固化，版本链，不可变快照 |

- `LifecycleScheduler` 周期（默认 300s）驱动 consolidation 与降级：长期记忆健康度低于阈值（默认 0.3）降级为中期情景（`core/lifecycle/degrader.py`）。
- 自动遗忘引擎（`core/forget/auto_forget.py`）按艾宾浩斯遗忘曲线与健康度执行衰减；手动精准遗忘见 §8。

## 7. 安全架构

```
内容 → SensitiveDetector（声明式规则库 safety_rules/data/builtin-1.0.json，14 条内置规则）
     → SafetyPolicy 决策：ALLOW / MASK（脱敏幂等）/ REVIEW / REJECT
     → REVIEW → 隔离区（AES-256 加密，quarantine）→ 人工放行/删除
     → 全过程 → 审计日志（HMAC 哈希链，防篡改，可校验）
     + 用户自定义规则（user_rules，加密存储，可含 forget 类）
```

- `SafetyWriteGate.route()` 是 `ApprovedWrite` 能力的唯一发放点（`core/safety/gate.py`）。
- vNext 链路中由 `application/safety_policy_adapter.py` 前置执行；`vnext.policy_required=true`（生产强制）时任何写入不得绕过 Policy，`allow_policy_bypass` 生产必须为 false。
- 三把独立密钥（审计 HMAC / 隔离区加密 / 用户规则加密）首次启动自动生成并保存到 `<db目录>/security/safety-keys.json`（POSIX 0700/0600），详见 [configuration.md](configuration.md)。

## 8. 精准遗忘

- 入口：`POST /api/memory/vnext/forget`（自然语言指令）与 `POST /api/memory/forget`。
- 流程：LLM 意图结构化解析（规则兜底）→ 定位（精确 ID / scope / 关键词 / 向量语义）→ `POST /forget/preview` 可先预览影响面 → 执行删除（正文 + 谱系 + 证据 + 向量/关键词/缓存投影级联清理）→ `GET /forget/{record_id}` 查询状态。
- 遗忘动作强制采集 Trace（仅存受影响 ID 的哈希），`GET /api/memory/forget/history` 可审计。

## 9. 灰度切流与回滚

`RolloutController`（`application/rollout_service.py`）固化五级切流：

```
legacy/0% → canary/5% → canary/25% → canary/50% → vnext/100%
```

- 不允许跳级；每级需满足观察窗口（`observation_window_requests`）且**零容忍**：无 Policy 泄漏、无跨租户结果、无 Forget 残留、无观察错误，方可 `POST /rollout/advance`。
- 回滚是只读开关（`POST /rollout/rollback`），回滚窗口 `rollback_window_minutes`（默认 60）；CUTOVER/ROLLBACK 均产生审计记录。
- Shadow 对照：`formation_shadow.py`（写路径旁路观察）与 `shadow_read_service.py`（读路径双读对比），均不写 Authority 正文/状态；对比报告由 `evaluation/run_vnext_shadow.py` 产出。
- 规范细节：[vnext/spec/VNEXT_ROLLOUT.md](vnext/spec/VNEXT_ROLLOUT.md)、[VNEXT_MIGRATION.md](vnext/spec/VNEXT_MIGRATION.md)。

## 10. 可观测性

- **Trace**（`observability/trace_models.py` + `trace_policy.py` + `trace_store.py`）：五条类型化链路 FORMATION / EVOLUTION / RETRIEVAL / FORGET / INFRASTRUCTURE；普通链路确定性采样，高严重级、失败/拒绝与 Forget 链路强制采集并延长保留；**递归校验拒绝任何正文字段入库**（脱敏由模型层强制，非约定）。
- **指标**（`observability/metrics.py`）：写入/检索/形成/反馈计数与延迟，SQLite 持久化，跨重启可查。
- **看板与诊断**：`POST /api/memory/vnext/dashboard/{view}`（explorer / evolution / retrieval / benchmark 四视图）与 `POST /api/memory/vnext/diagnostics`（管理权限）。
- 契约：[vnext/spec/VNEXT_TRACE.md](vnext/spec/VNEXT_TRACE.md)。

## 11. 存储与投影

| 存储 | 内容 | 角色 |
|---|---|---|
| SQLite（`storage/database.py` + `models.py`） | events、preferences、knowledge、memory_lineage、memory_evidence、projection_outbox、extraction_tasks、short/mid_term、vNext Authority/候选/工作/情景/演化/Trace/指标表 | **事实源** |
| Authority 仓储（`authority_repository.py`） | vNext 长期记忆权威信封（租户/scope/版本/证据约束） | 单写者 |
| Milvus（生产，`vector_engine/milvus_engine.py`，麒麟 C API + app_id）或 FAISS（开发，`faiss_engine.py`） | 稠密向量 + 稀疏向量（`sparse.py`） | 派生投影 |
| BM25 关键词索引（rank-bm25 + jieba） | 关键词检索 | 派生投影 |
| LRU 缓存 | 查询向量、检索结果 | 派生 |

- 投影一致性：durable Outbox（同事务写入）→ 后台 Worker 投影 → 失败补偿任务（`compensation_task.py`）→ 漂移对账（`sync_service.py`）→ 修复工具（`storage/repair.py`、`scripts/repair_projections.py`、`scripts/rebuild_projections.py`）。
- 表结构与 Schema 权威：[vnext/spec/VNEXT_STORAGE_SCHEMA.md](vnext/spec/VNEXT_STORAGE_SCHEMA.md)。

## 12. Embedding 与 LLM

- **Embedding**（`embedding/`）：生产使用麒麟 `kylin-coreai-embedding` C SDK（ctypes 加载 `.so`，DBus 连接后端服务，模型 `ensemble-embd_gte-base_uint8-text`，固定 **768 维**，维度不符直接失败关闭）；开发使用 `MockEmbeddingClient`（确定性向量）或 `kylin_mock`（third_party 内与真实 SDK 同符号的 mock 动态库，可跑通 ctypes 链路）。运行时契约：[reference/kylin-embedding-runtime-contract.md](reference/kylin-embedding-runtime-contract.md)。
- **LLM**（`llm/openai_client.py`）：云端 OpenAI 兼容接口（默认 dashscope/qwen-flash），用于抽取、冲突裁决、遗忘意图解析等语义决策；LLM 不可用时全部有确定性规则兜底，写入链路不因 LLM 阻塞（`llm.fact_extraction_timeout_seconds` 限制增强步骤耗时）。
- **生产双层门禁**（`config.py`）：`validate_production_gate()` 静态校验（provider=kylin/milvus、768 维、禁 fallback、vNext policy_required/authority_single_writer 强制），`validate_production_runtime()` 在客户端/引擎构造后动态校验（.so 加载、连通性）；违规抛 `ProductionGateError` 拒绝启动。

## 13. 双轨说明（legacy 与 vNext）

- **vNext 是默认主线**：`vnext.mode=vnext`、`formation_mode=authority`、`events_default=true`。
- **legacy 链路保留**用于回滚与对照：`core/` + `retrieval/hybrid|milvus_hybrid` + `adapter/api.py` 的原有行为在 `legacy/shadow/dual-read/canary` 模式下仍可显式启用；`allow_legacy_read_fallback` 保留兼容读回滚窗口，但**不允许出现第二个 Authority 写者**。
- `core/` 不是废弃层：它是 vNext 应用层复用的领域实现（抽取、冲突、安全、生命周期），两轨共享同一套安全门禁与写入原语。
- 历史演进过程（旧核心重构 Phase A–I、vNext B01–B18/S6 执行记录）归档于 `old/docs/`，仅供追溯。
