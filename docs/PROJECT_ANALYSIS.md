# Kylin-MemoryHub 深入浅出讲解

> **数据契约说明（v0.1.0）**：本文已按当前 `main` 分支源代码全面校正，所有代码事实均以 [`memoryhub/adapter/schemas.py`](../memoryhub/adapter/schemas.py)、[`INTERFACE.md`](INTERFACE.md)、`ARCHITECTURE.md` 为准。早期示例中的 `task_id / content / timestamp / quality_score / sensitive_level / metadata` 字段全部已弃用，禁止继续使用；事件类型从「5 类 `EventType`」改为「**`SourceType` 三类 + `event_type` 开放字符串**」；事实三元组已并入知识链；LLM 仅 `OpenAIClient`（OllamaClient 已移除）；生产栈检索器改为 `MilvusHybridRetriever`，FAISS / BM25 仅 dev/test 降级。

## 一、项目是什么？一句话概括

**Kylin-MemoryHub 是一个"AI Agent 的记忆系统"**——让银河麒麟 OS 上的 AI 助手能"记住"用户的偏好、学到的工作流、沉淀事实知识，并在下次对话时自动复用这些记忆。

打个比方：你第一次让 AI 帮你写周报，它什么都不记得；但你说了一句"以后周报都用 Markdown"，下次它就自动按 Markdown 格式来。这就是 MemoryHub 在背后做的事。

---

## 二、系统架构总览（7 层）

```
┌──────────────────────────────────────────────────────────────┐
│  L1 · OS Agent · Qt 桌面控制台 · OpenCode Plugin · CLI/MCP   │  ← 用户交互入口（agent-integration/ + desktop-client/）
├──────────────────────────────────────────────────────────────┤
│  L2 · FastAPI 5 Router                                        │  ← api.py / agent_api.py / management_api.py / memory_v2_api.py
├──────────────────────────────────────────────────────────────┤
│  L3 · 摄取管线                                                │  ← Cleaner → Normalizer → QualityScorer → SafetyGate
├──────────────────────────────────────────────────────────────┤
│  L4 · 8 大核心模块（Core）                                    │  ← ingestion / preference / knowledge(含 fact) / conflict / forget(含 health) / safety / lifecycle / memory 基元
├──────────────────────────────────────────────────────────────┤
│  L5 · 检索引擎                                                │  ← 生产 MilvusHybridRetriever / dev HybridRetriever + 双层 LRU 缓存
├──────────────────────────────────────────────────────────────┤
│  L6 · 持久化（SQLite 事实源 + 投影）                          │  ← 12 张表 + Milvus / FAISS / Outbox / Compensation / Sync
├──────────────────────────────────────────────────────────────┤
│  L7 · 抽象层 + 评测                                           │  ← KylinEmbedding/OpenAI + safety_rules 声明式规则库 + 6 个评测驱动
└──────────────────────────────────────────────────────────────┘
```

详见 [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) 的 7 层 + 统一写入契约 + 麒麟原生化组件全景图。

---

## 三、核心数据结构（schemas.py — 全系统的"语言"，1781 行）

所有模块之间传递数据都用同一套 Pydantic 模型，这是整个系统的"通用语言"。详细权威定义见 [`INTERFACE.md`](INTERFACE.md)；本节列出核心模型。

### 3.1 MemoryEvent — 统一事件模型（Schema 1.1，`schemas.py:268`）

```python
class MemoryEvent(BaseModel):
    event_id: str                 # 事件唯一 ID
    source_type: SourceType       # TOOL_RESULT / USER_BEHAVIOR / MANUAL_CONFIG
    event_type: str               # 来源内的具体动作，开放字符串
    user_id: str                  # 用户 ID
    session_id: str               # 会话 ID
    turn_id: str                  # 同一轮 Agent 调用链 ID
    scene: str                    # 场景
    task_type: str                # 任务类型
    occurred_at: str              # UTC 时间，格式 YYYY-MM-DDTHH:MM:SSZ
    text: str                     # 抽取摘要文本（替代旧 content）
    payload: dict                 # 来源特有结构化内容（替代旧 content）
    tool_calls: list[ToolCallResult]  # 工具调用明细（替代旧 content.tool_name/output）
    schema_version: Literal["1.0", "1.1"]
    source_hash: str              # canonical SHA-256（normalizer.py:18-163 计算）
    redactions: list[str]
    quality: EventQuality         # 替代旧 quality_score
```

**3 类 SourceType**（替代旧 5 类 EventType）：

| SourceType | 含义 | 适配器 | event_type 示例 |
|---|---|---|---|
| `tool_result` | 工具或 Agent 执行结果 | `core/ingestion/adapters/tool_result_adapter.py:ToolResultAdapter` | `tool_result`、`task_trajectory`、`agent_response` |
| `user_behavior` | 用户操作、消息或显式反馈 | `core/ingestion/adapters/behavior_adapter.py:BehaviorAdapter`（VALID_BEHAVIOR_TYPES = {selection, correction, confirm, message, cancel}） | `user_action`、`user_feedback` |
| `manual_config` | 用户或管理员手动配置（版本化 ManualConfig） | `core/ingestion/adapters/config_adapter.py:ConfigAdapter` | `manual_config` |

旧版 `task_id / source / content / timestamp / quality_score / sensitive_level / metadata` 字段**已全部弃用**，禁止新代码使用；EventType 封闭枚举已替换为 `SourceType` 枚举 + `event_type` 开放字符串。

### 3.2 PreferenceMemory — 偏好记忆（`schemas.py:1392`，7 类 PreferenceType）

```python
class PreferenceMemory(BaseModel):
    memory_id: str                          # "pref_<8位hex>"
    user_id: str
    memory_type: str = "preference"
    preference_type: PreferenceType         # 7 类枚举，见下
    text: str                              # 替代旧 content
    payload: dict                          # 替代旧 content 结构化字段
    scope: SceneScope
    is_global: bool
    confidence: float
    quality_score: float
    extract_source: str
    status: MemoryStatus                   # active / archived / deleted / pending
    level: MemoryLevel                     # short / mid / long
    version: int
    parent_id: str                         # 版本链指针
    root_id: str                           # 版本树根节点
    evidences: list[Evidence]
    tags: list[str]
    extra_payload: dict
    health_score / stability / last_accessed_at / access_count_30d  # 健康度（驱动自动遗忘）
    created_at / updated_at
```

**7 种偏好类型**（PreferenceType 枚举，`schemas.py:62`）：
`OUTPUT_STYLE / TOOL_PREFERENCE / WORKFLOW_PREFERENCE / SAFETY_PREFERENCE / SCENE_PREFERENCE / FORMAT_PREFERENCE / LANGUAGE_PREFERENCE`。

**置信度公式**（`core/preference/confidence.py:36-154` + `core/memory/confidence.py:26-71`）：
- 来源权重：`USER_BEHAVIOR=1.0 / MANUAL_CONFIG=0.95 / TOOL_RESULT=0.6 / 未知=0.4`
- 时间衰减：半衰期 14 天
- 统一公式 `0.85 + 0.15·min(source, quality)` 弱链抑制
- evidence_count 桶化：`1 / 2 / 3+ → 0.55 / 0.75 / 0.90`

### 3.3 KnowledgeMemory — 知识记忆（`schemas.py:1445`，**4 类**含 FACT）

```python
class KnowledgeMemory(BaseModel):
    memory_id: str
    user_id: str
    memory_type: str = "knowledge"
    knowledge_type: KnowledgeType          # workflow / case / template / **fact**
    name: str
    content: str
    steps: list[str]
    tools: list[str]
    template_body: str
    # FACT 三元组（subject / predicate / object_value / object_type）
    subject / predicate / object_value / object_type: str | None
    scope: SceneScope
    confidence: float
    success_count / total_count: int
    status / level
    version / parent_id
    evidences: list[Evidence]
    created_at / updated_at
```

**4 类 KnowledgeType**（`schemas.py:74`）：
| 值 | 含义 | 必填字段 |
|---|---|---|
| `workflow` | 工作流知识 | `name`, `steps`, `tools` |
| `case` | 历史案例 | `name`, `content` |
| `template` | 可复用模板 | `name`, `template_body` |
| **`fact`** | 事实三元组 S-P-O（并入知识链） | `subject`, `predicate`, `object_value` |

**重要架构决策（v0.1.0）**：事实三元组不再独立成类，降格为 `KnowledgeType.FACT`，共用知识链的抽取 / 冲突 / 检索 / 评测，同时保留三元组的精确关系查询能力。这避免了「事实走偏门」成为「统一写入契约」的漏网之鱼。

### 3.4 其他关键模型

- **ConflictRecord**（`schemas.py:1503`）：冲突记录；`decision` 可为 `ConflictDecision`（4 类）或 `KnowledgeConflictResolution`（equivalent/no_conflict/concrete_conflict）
- **ForgetRecord**（`schemas.py:1535`）：遗忘审计；v0.1.0 新增 `deleted_snapshot`（被删记忆快照）字段
- **FactMemory**（`schemas.py:1556`）：事实 S-P-O 视图，与 KnowledgeMemory(FACT) 共享存储
- **ManualConfig**（`schemas.py:178`）：版本化手动配置（`config_id / config_type / payload / version / parent_id / root_id`）
- **Evidence**（`schemas.py:198`）：证据链（`event_id / source_type / weight / decision`）

### 3.5 SceneScope — 场景作用域（贯穿全系统）

```python
class SceneScope(BaseModel):
    scene: str      # 大场景，如 "office", "code", "chat"
    task_type: str  # 任务类型，如 "office.weekly_report"
    app: str        # 来源应用，如 "os_agent"
```

控制"记忆在什么场景下生效"——Markdown 偏好只在"办公-周报"场景生效，不影响"代码"场景。v2 search 还支持 `project` 进一步过滤。

---

## 四、核心功能拆解与数据流

### 功能 1：记忆写入（事件 → 记忆）

**入口**：`POST /api/memory/events`（`adapter/api.py:457-500`）

**v0.1.0 真实数据流**（接 `EventIngestionService.ingest()`，`core/ingestion/service.py:63-132`）：

```
原始数据（工具结果 / 用户行为 / 手动配置 / 多源适配器）
  │
  ▼
DataCleaner.clean()                          ← 字段校验 + 限额校验 + 幂等去重（max_depth/max_text_chars/...）
  │
  ▼
EventNormalizer.normalize()                  ← source/old_alias → source_type；计算 canonical_sha256(source_hash)
  │
  ▼
QualityScorer.score()                        ← 4 维加权：0.30·completeness + 0.30·validity + 0.20·consistency + 0.20·freshness
  │                                            阈值 0.2/0.5；tool 失败 / 部分失败 / 空内容 → REJECTED
  ▼
SensitiveDetector.process(event) + 用户规则 Overlay
  │
  ▼
SafetyWriteGate.route()                       ← 唯一发放 ApprovedWrite 凭据（fail_closed）
  │
  ├── REJECT → ❌ 拒绝入库（仅审计）
  ├── REVIEW → AES-256-GCM 隔离区（ReviewQuarantineStore.put）
  ├── MASK   → 脱敏复检 → ApprovedWrite（脱敏后事件）
  └── ALLOW  → ApprovedWrite（只读安全事件）
        │
        ├── event_type ∈ user_feedback / user_behavior
        │     → ExtractionExecutor.run_preference(event)
        │       → PreferenceMemoryHandler.apply()
        │         → MemoryWriteService.upsert_memory(action=NEW/REINFORCE/...)
        │           → DomainMemoryWriter（单事务：memory + lineage + evidence + outbox）
        │     → ProjectionOutboxWorker.run_once() → Milvus / FAISS / 关键词 / 缓存
        │
        └── event_type ∈ task_trajectory / agent_response
              → ExtractionExecutor.run_knowledge(events)
                → KnowledgeMemoryHandler.apply()
                → 产出 workflow / case / template / **fact**(knowledge_type)
                → 冲突检测 + 合并 → MemoryWriteService.upsert_memory
```

**关键类**（按 v0.1.0 真实代码事实）：
- `DataCleaner` (`core/ingestion/cleaner.py:10-106`)
- `EventNormalizer` (`core/ingestion/normalizer.py:18-163`，含 `_TYPE_MAP`：`tool/chat/manual_config` 旧别名 → `SourceType`)
- `QualityScorer` (`core/ingestion/quality.py:10-118`，4 维加权，已校正权重)
- `SensitiveDetector` (`core/safety/detector.py`) + `SafetyWriteGate` (`core/safety/gate.py:181-`)
- `EventIngestionService` (`core/ingestion/service.py:EventIngestionService:26-236`)
- `ExtractionExecutor` (`core/ingestion/extraction.py:22-241`，含 `execution_key` 幂等 + `ExtractionRetryTask` 重试队列)
- `MemoryWriteService` (`core/memory_write.py:98-158`，单写入口)
- `DomainMemoryWriter` (`core/domain_writer.py`，单事务边界)

### 功能 2：偏好抽取（核心智能）

**入口**：`PreferenceExtractor.extract(event)`（`core/preference/extractor.py:29-46`）

**两阶段抽取 + GVR 循环**：

```
阶段 1：规则抽取（快速、确定性，extractor.py:48-123）
  输出格式正则（markdown/html/...）  → OUTPUT_STYLE
  隐私/安全关键词（覆盖中英文 17+） → SAFETY_PREFERENCE
  工具/工作流/格式/语言 关键词      → 对应 PreferenceType
  is_global 由规则与 LLM 双重保险判定

阶段 2：LLM 抽取（GVR 循环，最多 3 轮，extractor.py:125-253）
  → system prompt + JSON schema
  → output: {implicit_pref / preference_type / action_payload / tags / is_global}
  → 失败反馈修正；3 轮后入死信队列（ExtractionTaskRepository）

合并去重 → 绑定 Evidence → 计算置信度
```

**ToolPreferenceMiner（核心创新，统计式确定性挖掘，`tool_miner.py:26-106`）**：

```
对同一 (scene, task_type) 下成功 / 部分成功的工具调用做统计
触发条件：使用次数 ≥ 3 且 成功率 ≥ 0.7 且 为最常用工具
置信度公式：confidence = min(0.95, 0.6 + 0.1·use + 0.2·success_rate)
产出 PreferenceMemory(TOOL_PREFERENCE)，evidence 绑定工具轨迹片段
由 MemoryConsolidator.consolidate_tool_preferences() 在分层流转时定期执行
```

### 功能 3：记忆检索（混合搜索）

**入口**：`POST /api/memory/search`（生产栈由 `MilvusHybridRetriever.search()` 装配）

**生产栈真实流**（`retrieval/milvus_hybrid.py:106-520`）：

```
查询 "项目周报"
  │
  ▼
MilvusHybridRetriever.search(SearchRequest)
  │
  ├── SearchCache.get(version + canonical_json)  → 命中 → 直接返回
  ├── query_vector_cache.get(query)               → 命中 → 复用 768 维向量
  │
  ├── 未命中 → KylinEmbeddingClient.embed(query)  → 768 维稠密向量（超时 250ms）
  ├── build_sparse_vector(query)                  → FNV-1a 稀疏向量（与 C 侧逐位一致）
  ├── engine.hybrid_search(dense, sparse)         → Milvus 内部 RRF 融合
  ├── 元数据后过滤（user_id / status / memory_type）
  ├── SQLite 回表补齐 + 限 20 候选
  ├── Reranker 6 因子加权（原始/相关/scope/置信/新鲜/健康）
  └── format_response → SearchResponse（preferences / knowledge / facts / short_term / mid_term）
       │
       ▼
SearchCache.set（按 index_version 自动失效）
```

**降级路径**（仅 dev/test 模式）：`HybridRetriever`（`retrieval/hybrid.py:23-308`）组合 `VectorSearcher(FAISS)` + `KeywordSearcher(BM25)` + Reranker，公式 `final = vector_w·v_norm + keyword_w·k_norm + metadata_w·m`。

**关键类**：
- `MilvusHybridRetriever` (`retrieval/milvus_hybrid.py`) — 生产唯一
- `HybridRetriever` (`retrieval/hybrid.py`) — dev/test 降级
- `VectorSearcher` (`retrieval/vector_search.py`) — FAISS IndexFlatIP
- `KeywordSearcher` (`retrieval/keyword_search.py`) — rank-bm25 + jieba
- `Reranker` (`retrieval/reranker.py`) — 6 因子加权
- `SearchCache` (`retrieval/cache.py`) — LRU + TTL，按 `index_version` 失效

### 功能 4：精准遗忘（NL / 范围 / ID 三入口）

**入口**：`POST /api/memory/forget/preview` → `POST /api/memory/forget`

**数据流**（`core/forget/forgetter.py:MemoryForgetter:29-598`）：

```
用户说："忘掉我关于周报格式的偏好"
  │
  ▼
MemoryForgetter.parse_intent(instruction)        ← 规则推断 memory_type + jieba/正则关键词 + LLM 补充（forgetter.py:171-241）
  → {memory_type: "preference", target_topic: "周报格式", scope: "office.*"}
  │
  ▼
locate_memories(intent)                          ← 三策略：exact / scope / (keywords + embedding cosine ≥ 0.75)
  │
  ▼
delete_memories(memory_ids)                      ← MemoryWriteService.upsert_memory(SUPERSEDE 软删)
  │
  ▼
create_audit_log()                               ← 写 ForgetRow（含被删记忆快照 deleted_snapshot）

健康度驱动自动遗忘（`core/forget/auto_forget.py:AutoForgetEngine`）：
  health = 0.6·time_decay + 0.4·usage_frequency   ← Ebbinghaus R = e^(-t/S), S = half_life/ln2 · (1 + hits/10)
  阈值：< 0.2 归档 / < 0.4 降级 + 写 epi_dg_* 中期 / < 0.6 待审 / ≥ 0.6 保留
```

### 功能 5：冲突处理（决策矩阵 4 种 + KnowledgeConflictResolution 3 种）

**检测条件**（`core/conflict/detector.py:ConflictDetector:11-145`）：
1. scope 重叠（同一场景/任务类型）
2. type 相同
3. 内容语义矛盾（payload 对比 + LLM 语义判断 + 否定词规则）

**偏好冲突解决策略**（`ConflictDecision`，4 种）：

| 条件 | 决策 | 实现位置 |
|---|---|---|
| scope 不同 | **COEXIST**（按 scope 保留两条） | `resolver.py:apply_coexist` |
| 内容相同 / 显式反馈 → | **MERGE** / **OVERRIDE** | `resolver.py:apply_merge / apply_override:65-95`（override 旧版 ARCHIVED + 新版 active） |
| 隐式低置信矛盾 | **PENDING**（写入 conflicts 表，等用户裁决） | `resolver.py:apply_pending` |

**知识冲突解决**（`KnowledgeConflictResolution`，3 种）：`equivalent / no_conflict / concrete_conflict`；由 LLM 在 `KnowledgeUpdater` 内返回（`core/knowledge/prompts.py:3-51` 约束）。

**统一记忆处理决策**（`MemoryDecision` 枚举，**8 类**，v0.1.0 新增）：`NEW / REINFORCE / REVISE / SUPERSEDE / COEXIST / DUPLICATE / REVIEW / REJECT`，由 `BaseMemoryHandler.decide()` 返回。

### 功能 6：记忆生命周期（三引擎 + 后台调度器）

**三层流转**（`memoryhub/core/lifecycle/`）：

```
新事件写入
    │
    ▼
EventIngestionService._buffer_short_term       ← TTL 24h
    │
    ├── SessionConsolidator                     ← 会话结束 → 中期情景（epi_*）
    │
    ▼
MID（中期）── candidate preferences / recent cases
    │
    ├── MemoryConsolidator                      ← 合并入长期
    │     ├── consolidate_episodes
    │     ├── consolidate_tool_preferences      ← 触发 ToolPreferenceMiner
    │     └── consolidate_workflow_preferences  ← 触发 WorkflowMiner
    │
    ▼
LONG（长期）── stable preferences / workflow / template / fact
    │
    ├── MemoryDegrader                          ← 长期低健康度 → 写 epi_dg_* 中期 + 长期 ARCHIVED
    │
    ▼
AutoForgetEngine                               ← 健康度驱动自动遗忘
  health < 0.2 → 归档 / 0.2-0.4 → 降级 / 0.4-0.6 → 待审 / ≥ 0.6 保留

后台调度：LifecycleScheduler（`scheduler.py:25-104`）每 300s 跑 run_consolidation_cycle()
手动触发：POST /api/memory/lifecycle/{auto-forget, check, consolidate}
```

**关键阈值**（`core/lifecycle/manager.py:26-31`）：

```python
PROMOTE_THRESHOLDS = {"short_to_mid": {...}, "mid_to_long": {...}}
DEMOTE_THRESHOLDS = {"..."}
HEALTH_ARCHIVE_THRESHOLD = 0.2
```

---

## 五、存储层设计

### 5.1 SQLite（事实源，**12 张表**）

> **v0.1.0 真实表结构**（`memoryhub/storage/database.py:Database.init_schema()` + `models.py`）：

| 表 | ORM 行 | 用途 |
|---|---|---|
| `events` | `EventRow:28` | 原始事件归档 |
| `preferences` | `PreferenceRow:50` | 偏好记忆主表 |
| `knowledge` | `KnowledgeRow:89` | 知识记忆主表（**含 FACT**） |
| `knowledge_versions` | `KnowledgeVersionRow:139` | 不可变快照 |
| `conflicts` | `ConflictRow:154` | 冲突审计 |
| `forget_history` | `ForgetRow:173` | 遗忘审计（含 deleted_snapshot） |
| `memory_lineage` | `MemoryLineageRow:185` | 谱系（v2 API 返回） |
| `memory_evidence` | `MemoryEvidenceRow:210` | 证据链权威存储 |
| `memory_projection_outbox` | `MemoryProjectionOutboxRow:242` | 可靠投影（durable outbox） |
| `extraction_tasks` | `ExtractionTaskRow:268` | 抽取任务（含死信队列） |
| `short_term_memory` | `ShortTermMemoryRow:291` | 工作记忆（TTL 24h） |
| `mid_term_memory` | `MidTermMemoryRow:308` | 中期情景 / epi_* / epi_dg_* |

每张表对应一个 Repository 类（`EventRepository / PreferenceRepository / KnowledgeRepository / ConflictRepository / ForgetRepository / ExtractionTaskRepository / ShortTermMemoryRepository / MidTermMemoryRepository`），封装 CRUD 操作。

### 5.2 向量索引（生产栈 Milvus）

- **生产**：`MilvusVectorEngine`（`storage/vector_engine/milvus_engine.py`）调用 `libkysdk-vector-engine-client-capi.so`（自编译 C API 桥接），连接到 `Milvus gRPC Server :19530`，单 collection `memoryhub`，维度 768，稠密 + 稀疏 RRF 融合
- **开发降级**：`FAISSVectorEngine`（`storage/vector_engine/faiss_engine.py`）包装 `VectorStore`（`storage/vector_store.py:25-302`）；`id_map: dict[int, str]` + `reverse_map: dict[str, int]`；支持 `flat / ivf / hnsw`

### 5.3 证据链 + Outbox

- **新权威**：`MemoryEvidenceRepository`（`storage/memory_metadata.py:136`）持久化到 `memory_evidence` 表
- **旧兼容**：`EvidenceStore.save/load/delete`（`storage/evidence_store.py`）JSONL 格式 `{memory_id}.jsonl`
- **可靠投影**：`ProjectionOutboxWorker`（`storage/projection_outbox.py:25-99`）后台异步把 SQLite 事务提交的内容投影到 Milvus / FAISS / 关键词 / 缓存；崩溃后由 `MemorySyncService.reconcile`（`sync_service.py`）漂移对账 + `PendingIndexCompensationTask`（`compensation_task.py:34-164`）补偿

---

## 六、LLM & Embedding 抽象层

### 6.1 LLM 抽象

```
BaseLLMClient（`llm/base.py:BaseLLMClient:20-75`，抽象基类）
    ├── generate(prompt, system_prompt, **kwargs) → LLMResponse
    ├── generate_json(prompt, schema, system_prompt) → dict
    └── is_available() → bool

仅有一个实现：
    └── OpenAIClient（`llm/openai_client.py:12-48`）
          通过 urllib.request POST /chat/completions（兼容 OpenAI Chat Completions 协议）
          generate_json 追加 response_format={"type":"json_object"} + 去 markdown 包装
          is_available 判定：api_base 非空 + (api_key 有值 或 host 为 localhost/127.0.0.1)
```

> **v0.1.0 变更**：旧版 `OllamaClient` 已移除；`memoryhub/llm/__init__.py` 仅导出 `BaseLLMClient / OpenAIClient / LLMResponse`。

### 6.2 Embedding 抽象

```
BaseEmbeddingClient（`embedding/base.py:BaseEmbeddingClient:12-63`，抽象基类）
    ├── embed(text) → list[float]
    ├── embed_batch(texts) → list[list[float]]
    ├── get_dimension() → int
    └── is_available() → bool

实现（`embedding/__init__.py:30-76` 工厂）：
    ├── KylinEmbeddingClient(use_mock=False)  — 生产：ctypes → libkylin-coreai-embedding.so → DBus → 768 维
    ├── KylinEmbeddingClient(use_mock=True)   — 跨平台 dev：third_party/kylin-mock/build/libkylin-coreai-embedding-mock.{so,dll,dylib}
    └── MockEmbeddingClient                   — dev：SHA256 + 种子确定性 768 维随机向量
```

**生产栈关键参数**（`embedding/kylin_client.py`）：
- 模型：`ensemble-embd_gte-base_uint8-text`
- 维度：**768**（生产硬约束）
- `MAX_QUERY_CHARS = 512`
- 单次超时：`query_timeout_ms = 250`（ThreadPoolExecutor(max_workers=1) + future.timeout）
- 稳定错误码：`embedding.unavailable / dimension_mismatch / timeout / call_failed / sdk_error / backend_error / invalid_text / mock_unavailable`

---

## 七、具体运行示例

> 示例中的事件 JSON 已按 v0.1.0 canonical schema 重写，旧字段 `task_id / content / quality_score / sensitive_level / metadata` 全部移除。

### 示例 1：首次生成周报（无记忆）

```
用户: "帮我整理这周项目进展，生成周报"
  │
  ▼
OS Agent → POST /search {query: "项目周报"}
MemoryHub → 检索 → 无历史记忆 → 返回空
  │
  ▼
OS Agent 自行执行：读日历 → 读文件 → 生成报告
OS Agent → POST /events {4 条 tool_result，每条含完整 tool_calls[]}
MemoryHub → 存入 events 表（4 条）
```

### 示例 2：用户表达偏好 → 记忆形成

```
用户: "以后周报都用 Markdown，分三部分"
  │
  ▼
OS Agent → POST /events {source_type: USER_BEHAVIOR, event_type: user_feedback, text="以后周报都用 Markdown，分三部分"}
  │
  ▼
EventIngestionService.ingest()
  → DataCleaner.clean() → EventNormalizer.normalize() → MemoryEvent
  → QualityScorer.score() → 0.85 (高质量：显式反馈 + 完整内容)
  → SafetyWriteGate.route() → ALLOW → ApprovedWrite
  │
  ▼
ExtractionExecutor.run_preference(event)
  → PreferenceMemoryHandler.apply()
  → PreferenceExtractor.extract()
    → _rule_extract: 命中 "以后都用 X" 格式正则 → FORMAT_PREFERENCE
    → text = "周报使用 Markdown，分三部分"
    → scope = {scene: "office", task_type: "office.weekly_report"}
  │
  ▼
UnifiedConfidenceCalculator.calculate()
  → SOURCE_WEIGHTS[USER_BEHAVIOR] = 1.0
  → evidence_count = 1 → support 桶化 0.55
  → time_decay 14 天半衰期
  → confidence = 0.92
  │
  ▼
ConflictDetector.check_preference() → 无冲突（首次）
MemoryWriteService.upsert_memory(MemoryDecision.NEW)
  → DomainMemoryWriter：单事务 (memory + lineage + evidence + outbox)
  → ProjectionOutboxWorker：插入 Milvus 稠密 + 稀疏向量 + BM25 关键词
```

### 示例 3：复用记忆

```
用户: "按上次的方式生成这周周报"
  │
  ▼
OS Agent → POST /search {query: "项目周报", context: {scene: "office", task_type: "office.weekly_report"}}
  │
  ▼
MilvusHybridRetriever.search(SearchRequest)
  ├── SearchCache.get("version:canonical") → 命中 → 直接返回
  │     或
  ├── engine.hybrid_search(embed(query), build_sparse_vector(query)) → RRF 融合 → [pref_001, know_001]
  ├── SQLite 回表补齐 → SearchCache.set
  │
  ▼
返回: SearchResponse {preferences: [Markdown 三段式], knowledge: [周报生成流程], latency_ms: 28.5, index_version: 17}
  │
  ▼
OS Agent 自动按偏好执行 → 输出 Markdown 三段式周报 ✅
```

### 示例 4：偏好冲突 → 自动覆盖

```
用户: "以后周报改成 Word"
  │
  ▼
POST /events {USER_BEHAVIOR, text="以后周报改成 Word"}
  │
  ▼
PreferenceExtractor → FORMAT_PREFERENCE = "周报使用 Word"
  │
  ▼
ConflictDetector.check_preference():
  已有: pref_001 {text: "周报使用 Markdown", scope: office.weekly_report}
  新的: pref_xxx {text: "周报使用 Word", scope: office.weekly_report}
  → scope 重叠 + type 相同 + 内容矛盾 → 冲突！
  │
  ▼
ConflictResolver.auto_resolve()：
  source_type = USER_BEHAVIOR + 显式反馈 → OVERRIDE
  │
  ▼
MemoryWriteService.upsert_memory(MemoryDecision.SUPERSEDE)
  → pref_001.status → archived（保留 lineage.parent_id）
  → pref_002.version = 2, parent_id = "pref_001"
  → 写入 conflicts 表 + lineage 表
```

### 示例 5：精准遗忘

```
用户: "忘掉我关于周报格式的偏好"
  │
  ▼
POST /forget/preview {instruction: "忘掉我关于周报格式的偏好"}
  → MemoryForgetter.parse_intent → {memory_type: "preference", target_topic: "周报格式", scope: "office.*"}
  → locate_memories → 候选 ["pref_002"]
  → 返回 preview 给 UI
  │
  ▼
用户确认 → POST /forget {instruction: "...", target_memory_ids: ["pref_002"], cascade: true}
  │
  ▼
MemoryForgetter.delete_memories
  → MemoryWriteService.upsert_memory(MemoryDecision.SUPERSEDE)（软删）
  → MilvusHybridRetriever.index_version++（向量投影自动失效）
  → SearchCache.clear()
  → MemoryEvidenceRepository 删除证据
  │
  ▼
create_audit_log → 写 ForgetRow（含 deleted_snapshot）
返回: {record_id, deleted_count: 1, deleted_ids: ["pref_002"]}
```

### 示例 6：知识记忆形成（工作流挖掘）

```
用户第 3 次执行"生成周报"任务，每次工具调用链一致：
  日历查询 → 文件收集 → 数据整理 → 报告生成
  │
  ▼
MemoryConsolidator.consolidate_workflow_preferences(events)
  → WorkflowMiner.mine(3 组轨迹) [LCS + LLM 双引擎]
    → min_pattern_steps=2 / min_anchor_ratio=0.3 / min_stability=0.6
    → 对齐步骤 → 稳定度 1.0 (3/3 一致)
  │
  ▼
KnowledgeExtractor._build_workflow
  → name = "项目周报生成流程"
  → steps = ["查日历", "收集文件", "整理数据", "生成报告"]
  → tools = ["calendar_query", "file_search", "doc_reader", "report_writer"]
  → confidence = 0.95（6 因子加权）
  │
  ▼
MemoryWriteService.upsert_memory(NEW) → DomainMemoryWriter → 存入 SQLite + 投影 Milvus
  → 后续 /search {query: "项目周报"} 自动召回
```

### 示例 7：事实三元组（FACT 并入知识链）

```
用户提供："我们公司的 CEO 是张三，成立于 2010 年"
  │
  ▼
KnowledgeExtractor.extract_facts(events)
  → single_value 谓词（ceo / 成立于 / 负责人 / 总部 / 位于 / owner / headquarters / founder）
  → 抽出 RawTriple: (我们公司, ceo, 张三) + (我们公司, 成立于, 2010)
  │
  ▼
EntityNormalizer + PredicateNormalizer
  → 实体去重 / 谓词匹配 seed ontology (predicate_ontology.json ~85 谓词)
  → 提案 FactCandidate
  │
  ▼
UserRuleService 裁决（或系统自动）
  → POST /api/memory/knowledge {knowledge_type: fact, subject, predicate, object_value}
  → 写入 knowledge 表（subject / predicate / object_value 列）
  → MemoryWriteReceipt 返回
  │
  ▼
后续 /search {query: "CEO"} 自动召回 fact_xxx
```

---

## 八、配置系统（`memoryhub/config.py`）

> 完整字段、YAML/环境变量对照、生产门禁详见 [`CONFIGURATION.md`](CONFIGURATION.md)。

```
AppConfig（`config.py:load_config()` dataclass）
├── runtime.mode / allow_fallback          ← 生产硬门禁
├── storage.db_path / vector_index_path / evidence_path
├── retrieval.default_top_k / target_p95_ms / target_p99_ms / vector_weight / keyword_weight / ...
├── llm.api_base / api_key / model / temperature / max_tokens
├── embedding.provider / dimension / model_name / so_path / query_timeout_ms
├── vector_engine.provider / app_id / host / port / collection / dimension / search_timeout_ms
└── safety.rule_set_id / rule_set_version / policy / key_store / audit / quarantine / user_rules
    └── 扫描预算：max_depth=64 / max_field_chars=65536 / max_scan_bytes=2MiB / ...
```

**生产门禁**（`config.py:validate_production_gate()` :494-547 + `validate_production_runtime()` :550-584）：

| # | 约束 | 违反 |
|---|---|---|
| 1 | `runtime.allow_fallback = false` | `ProductionGateError` |
| 2 | `embedding.provider = "kylin"` | 同上 |
| 3 | `embedding.dimension = 768` | 同上 |
| 4 | `vector_engine.provider = "milvus"`，`app_id` 非空 | 同上 |
| 5 | 运行时 `KylinEmbeddingClient.is_available()=true` 且 `get_dimension()=768`；`MilvusVectorEngine` 已连接 | 同上 |

---

## 九、设计亮点总结

1. **事件驱动**：所有数据以 `MemoryEvent` 为唯一入口，三类 SourceType 归一；不同来源的数据先标准化再处理
2. **规则 + LLM 双引擎 + GVR 循环**：偏好抽取先用快速规则匹配，匹配不上再调 LLM，3 轮反馈修正；失败入死信队列
3. **统计式 ToolPreferenceMiner**（核心创新）：不依赖 LLM 的工具选择偏好挖掘，置信度有数学公式
4. **三引擎 + 后台调度器生命周期**：SessionConsolidator / MemoryConsolidator / MemoryDegrader + LifecycleScheduler；健康度 0.6·time_decay + 0.4·usage_frequency；Ebbinghaus R = e^(-t/S)，S = half_life/ln2 · (1 + hits/10)
5. **生产 Milvus 混合检索 + 双层 LRU**：稠密 768 维 + 稀疏 FNV-1a → Milvus 引擎内部 RRF 融合；SearchCache（结果）+ query_vector_cache（向量）双层 LRU；按 `index_version` 自动失效
6. **8 类 MemoryDecision + 决策矩阵**：避免「后写覆盖前写」式数据丢失；`SUPERSEDE` 显式生成新版本并保留谱系
7. **生产门禁双层校验**：所有非麒麟栈在 production 模式直接 `ProductionGateError` 启动失败
8. **写门禁四处置 + 审计哈希链 + AES-256-GCM 隔离区 + 用户规则 Overlay**：fail_closed 兜底；用户规则密文存储 + 乐观并发
9. **事实并入知识链**：避免「事实走偏门」成为统一写入契约的漏网之鱼
10. **完全本地化**：SQLite + Milvus + 麒麟 Embedding SDK + 本地 LLM（可云），数据不出设备

---

## 十、原始数据到底是什么

### 10.1 三类原始数据（SourceType，v0.1.0）

> **已弃用旧版 5 类 EventType**（tool_call / user_feedback / user_behavior / manual_config / task_trajectory）；
> 当前使用 **3 类 SourceType + `event_type` 开放字符串**。

#### 1. `tool_result` — 工具调用结果

OS Agent 每调用一个工具（搜索文件、读日历、写文档等），产生一条 `source_type=tool_result` 事件，`tool_calls[]` 必须包含完整工具调用链：

```json
{
  "event_id": "ev_001",
  "source_type": "tool_result",
  "event_type": "agent_response",
  "user_id": "u001",
  "session_id": "sess_001",
  "turn_id": "turn_007",
  "occurred_at": "2026-07-22T10:30:00Z",
  "text": "已根据项目文件和本周日程生成周报。",
  "payload": {"response_status": "success"},
  "tool_calls": [
    {
      "call_id": "call_001",
      "tool_name": "file_search",
      "arguments": {"query": "项目周报"},
      "result": {"files": ["weekly-report.docx"]},
      "status": "success",
      "sequence": 1,
      "error": ""
    },
    {
      "call_id": "call_002",
      "tool_name": "calendar_read",
      "arguments": {"range": "this_week"},
      "result": {"events": [{"title": "周会"}]},
      "status": "success",
      "sequence": 2,
      "error": ""
    }
  ],
  "scene": "office",
  "task_type": "office.weekly_report",
  "schema_version": "1.1",
  "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "redactions": [],
  "quality": {"score": 1.0, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}
}
```

#### 2. `user_behavior` — 用户行为（含显式反馈）

`BehaviorAdapter` 的 `VALID_BEHAVIOR_TYPES = {selection, correction, confirm, message, cancel}`：

```json
{
  "event_id": "ev_002",
  "source_type": "user_behavior",
  "event_type": "user_feedback",
  "user_id": "u001",
  "occurred_at": "2026-07-22T10:32:00Z",
  "text": "以后周报都用 Markdown，分三部分",
  "payload": {"action": "feedback", "target": "weekly_report", "feedback_type": "explicit"},
  "scene": "office",
  "task_type": "office.weekly_report",
  "schema_version": "1.1",
  "source_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "quality": {"score": 0.85, "status": "accepted", "completeness": 0.9, "validity": 1.0, "consistency": 1.0, "freshness": 0.8, "issues": []}
}
```

#### 3. `manual_config` — 手动配置（版本化）

```json
{
  "event_id": "ev_003",
  "source_type": "manual_config",
  "event_type": "manual_config",
  "user_id": "u001",
  "occurred_at": "2026-07-22T10:35:00Z",
  "text": "默认周报格式 Markdown",
  "payload": {
    "manual_config": {
      "config_id": "cfg_001",
      "config_type": "report_format",
      "payload": {"format": "markdown"},
      "version": 1,
      "parent_id": null,
      "root_id": "cfg_001"
    }
  },
  "scene": "office",
  "schema_version": "1.1",
  "source_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
}
```

### 10.2 数据从哪来

```
用户对 OS Agent 说话
       │
       ▼
OS Agent 执行任务
  ├── 调用工具 → 产生 source_type=tool_result 事件
  ├── 用户说了偏好 / 反馈 → 产生 source_type=user_behavior 事件
  └── 用户改了设置 → 产生 source_type=manual_config 事件（带版本链）
       │
       ▼
OS Agent 批量 POST 到 MemoryHub
  POST /api/memory/events
  { "events": [event1, event2, ...] }
```

### 10.3 关键字段说明

| 字段 | 含义 | 举例 |
|------|------|------|
| `session_id` | 一次对话的 ID | `sess_001` |
| `turn_id` | 同一轮 Agent 调用链 ID | `turn_007` |
| `scene` | 粗粒度场景 | `office` / `code` / `chat` |
| `task_type` | 细粒度任务类型，用 `.` 分层 | `office.weekly_report` |
| `source_type` | 接入来源大类（3 类枚举） | `tool_result` / `user_behavior` / `manual_config` |

`scene` + `task_type` 构成 `SceneScope`，决定这条数据产生的记忆在什么场景下生效。`v2.search` 还支持 `project` 进一步过滤。

---

## 十一、Agent 如何调用 MemoryHub

MemoryHub 是一个**独立的 HTTP 服务**（FastAPI，5 Router），OS Agent 通过 REST API 调用它。整个调用模式就三步：**做之前查记忆、做完后写记忆、需要时忘记忆**。

### 11.1 接入层架构

```
OS Agent (opencode / Claude Code / 自研) → MCP server (8 工具) → REST :8099
                                  └→ CLI (memoryhub 命令) → REST :8099
                                  └→ OpenCode Plugin (3 custom tools + 5 commands + 1 skill + 3 hooks) → CLI
Qt 桌面控制台 (26 pageKey) → REST :8099（管理接口）
```

详见 [`agent-integration/docs/CONTRACT.md`](../agent-integration/docs/CONTRACT.md) 与 [`agent-integration/docs/TECHNICAL.md`](../agent-integration/docs/TECHNICAL.md)。

### 11.2 三种核心调用模式

#### 模式 1：做事之前 — 查记忆

Agent 收到用户任务后，**先问 MemoryHub "关于这件事我记得什么"**，然后根据记忆决定怎么做。

```
用户: "按上次的方式生成周报"
  │
  ▼
OS Agent 收到任务
  │
  ▼
POST /api/memory/search
{
  "query": "项目周报",
  "context": {"scene": "office", "task_type": "office.weekly_report"},
  "top_k": 5,
  "level": "long",
  "session_id": "sess_001"
}
  │
  ▼
MemoryHub 返回 SearchResponse
{
  "preferences": [{"memory_id": "pref_001", "text": "周报使用 Markdown，分三部分", "confidence": 0.92, "memory_level": "long"}],
  "knowledge": [{"memory_id": "know_001", "name": "周报生成流程", "steps": [...]}],
  "short_term": [...],
  "mid_term": [...],
  "latency_ms": 28.5,
  "index_version": 17
}
  │
  ▼
OS Agent 读取记忆 → 自动按 Markdown 三段式 + 流程步骤执行
```

`POST /api/memory/context` 返回**可以直接拼进 prompt 的文本**：

```
POST /api/memory/context → 返回: "用户偏好：周报使用 Markdown...
                            参考流程：1.查日历 2.收集文件 3.整理数据 4.生成报告"
```

#### 模式 2：做完之后 — 写记忆

```
OS Agent 完成任务
  │
  ▼
POST /api/memory/events {events: [tool_call_1, tool_call_2, user_feedback]}
  │
  ▼
EventIngestionService.ingest()
  → 幂等去重 → 质量评分 → 安全门禁 → 偏好/知识/FACT 抽取 → MemoryWriteService.upsert_memory
  │
  ▼
返回: WriteEventResponse {accepted: 3, rejected: 0, event_ids: [...]}
```

#### 模式 3：用户说"忘掉" — 精准遗忘

```
用户: "忘掉我关于周报格式的偏好"
  │
  ▼
OS Agent → POST /api/memory/forget/preview {instruction: "..."}
  → preview 返回候选 → 用户确认
  │
  ▼
POST /api/memory/forget {instruction: "...", target_memory_ids: [...], cascade: true}
  │
  ▼
MemoryForgetter.execute
  → MemoryWriteService.upsert_memory(SUPERSEDE) → 软删 + 谱系
  → 投影自动失效
  → write ForgetRow 审计
  │
  ▼
返回: {record_id, deleted_count: 1, deleted_ids: [...]}
```

#### 补充模式：用户反馈

```
POST /api/memory/feedback
{
  "memory_id": "pref_001",
  "feedback_text": "确认，就是这个格式",
  "action": "confirm"   // "update" | "confirm" | "reject"
}
```

`confirm` 触发艾宾浩斯复习强化（S = half_life/ln2 · (1 + hits/10)）+ 健康度刷新。

### 11.3 MCP 8 工具（v0.1.0 实际清单）

| # | MCP 工具 | 用途 |
|---|---|---|
| 1 | `memoryhub_health` | 服务可达性 |
| 2 | `memoryhub_search` | 检索（支持 level / common 过滤） |
| 3 | `memoryhub_get_context` | prompt-ready 上下文 |
| 4 | `memoryhub_write_event` | 写入 1..N MemoryEvent |
| 5 | `memoryhub_remember` | 写偏好 / 知识（preference / workflow / case / template / fact） |
| 6 | `memoryhub_forget` | 精准遗忘（preview / confirm / cascade） |
| 7 | `memoryhub_feedback` | confirm / reject / update |
| 8 | `memoryhub_knowledge_fact_propose` | 提交事实三元组 |

CLI 17+ 子命令（`agent-integration/memoryhub_cli/cli.py`）：`search / context / event / remember / update / forget [--preview] / list / get / provenance / projection list|replay / feedback / review / resolve / decide / knowledge fact propose / export / import / status / service / completion`。

### 11.4 Agent 调用的核心 4 + 2 个接口

| 接口 | 方法 | 何时调 | 作用 |
|---|---|---|---|
| `/api/memory/search` | POST | 做事之前 | 检索相关记忆 |
| `/api/memory/context` | POST | 做事之前 | 获取可注入 prompt 的记忆文本 |
| `/api/memory/events` | POST | 做完之后 | 写入事件，触发记忆学习 |
| `/api/memory/forget` | POST | 用户要求遗忘 | 精准删除 |
| `/api/memory/feedback` | POST | 用户确认/拒绝/修改 | 艾宾浩斯复习强化 |
| `/api/memory/health` | GET | 健康探测 | 连通性检查 |

其余接口（`management_api.py` 提供的状态流转/健康度/审计/隔离区/系统状态/v2 谱系等）是**管理接口**，供 Qt 5 桌面客户端（`desktop-client/`，26 pageKey）或用户手动操作使用，不是 Agent 日常调用的。

`AgentSimulator`（`adapter/simulator.py:OSAgentSimulator:19-178`）是**模拟真实 Agent 行为的测试工具**，给前端 demo / 烟囱测试生成 `MemoryEvent`。

---

## 十二、源码推荐阅读顺序

### 第一阶段：基础层（先懂"语言"和"骨架"）

```
1. memoryhub/adapter/schemas.py (1781 行)  ← 最重要，全系统的数据结构定义
2. memoryhub/config.py                     ← 配置 + validate_production_gate + validate_production_runtime
3. memoryhub/app.py:171-866                ← 入口 create_app()，注册 5 个 Router
4. memoryhub/adapter/api.py                ← 标准 REST 路由
```

**为什么先读这些**：`schemas.py` 是所有模块的"通用语言"，不理解它就读不懂任何核心逻辑。`app.py` 的 5 个 Router 注册（`memory_v2_api.py:18` + `agent_api.py:24/27` + `management_api.py:44`）告诉你系统对外暴露的所有面。

---

### 第二阶段：数据接入层（理解数据怎么"进来"）

```
5. memoryhub/core/ingestion/cleaner.py      ← 清洗（限额校验 + 幂等去重）
6. memoryhub/core/ingestion/normalizer.py   ← 标准化（_TYPE_MAP 旧别名 → SourceType；canonical_sha256）
7. memoryhub/core/ingestion/quality.py      ← 质量评分（4 维加权 + 阈值门控）
8. memoryhub/core/ingestion/service.py      ← EventIngestionService（主入口）
9. memoryhub/core/ingestion/adapters/{tool_result,behavior,config}_adapter.py  ← 三类源适配器
10. memoryhub/core/safety/{detector,gate,key_store,audit_log,quarantine,user_rules}.py  ← 安全子系统
```

**阅读线索**：一条原始数据如何一步步变成标准的 `MemoryEvent`，过安全门禁后被受控地落到受保护 sink。

---

### 第三阶段：记忆核心（系统的"大脑"）

```
11. memoryhub/core/preference/{extractor,confidence,updater,handler,tool_miner}.py   ← 偏好（含 ToolPreferenceMiner 核心创新）
12. memoryhub/core/knowledge/{extractor,confidence,updater,handler,template_builder,workflow_miner,prompts,evaluation}.py  ← 知识（含 FACT）
13. memoryhub/core/conflict/{detector,resolver}.py
14. memoryhub/core/forget/{forgetter,auto_forget,health,rules}.py                     ← 精准遗忘 + 健康度
15. memoryhub/core/lifecycle/{manager,session_consolidator,memory_consolidator,degrader,scheduler}.py  ← 三引擎 + 调度
16. memoryhub/core/memory/{base,confidence,evidence,freshness,llm}.py                 ← 共享基元（BaseMemoryHandler / UnifiedConfidenceCalculator / EvidenceMerger / StructuredLLMAdapter）
17. memoryhub/core/memory_write.py           ← MemoryWriteService 单写入口
18. memoryhub/core/domain_writer.py          ← DomainMemoryWriter 单事务边界
```

**阅读线索**：偏好抽取是核心中的核心，读懂它再看知识抽取会很顺畅。冲突处理是偏好抽取的"下游"，生命周期是"长期维护"。

---

### 第四阶段：检索层（理解数据怎么"出去"）

```
19. memoryhub/retrieval/milvus_hybrid.py     ← MilvusHybridRetriever（生产唯一装配）
20. memoryhub/retrieval/hybrid.py            ← HybridRetriever（dev/test 降级）
21. memoryhub/retrieval/{vector_search,keyword_search,reranker,cache}.py  ← 子模块
```

**阅读线索**：从 `milvus_hybrid.py` 入手（双层 LRU + RRF 融合 + 错误码体系），再对照 `hybrid.py` 看降级路径差异。

---

### 第五阶段：存储层（理解数据怎么"落地"）

```
22. memoryhub/storage/database.py          ← Database + 8 个 Repository
23. memoryhub/storage/models.py             ← 12 张表的 ORM
24. memoryhub/storage/vector_engine/{base,faiss_engine,milvus_engine,_milvus_ctypes,sparse}.py  ← 向量引擎
25. memoryhub/storage/memory_metadata.py    ← MemoryLineageRepository + MemoryEvidenceRepository + MemoryProjectionOutboxRepository
26. memoryhub/storage/projection_outbox.py   ← ProjectionOutboxWorker
27. memoryhub/storage/{sync_service,compensation_task,evidence_store}.py  ← 同步与补偿
```

---

### 第六阶段：抽象层（可插拔的后端实现）

```
28. memoryhub/llm/base.py                   ← BaseLLMClient 抽象接口
29. memoryhub/llm/openai_client.py           ← OpenAI 实现（urllib 直连）
30. memoryhub/embedding/base.py              ← BaseEmbeddingClient 抽象接口
31. memoryhub/embedding/kylin_client.py      ← 麒麟 SDK 实现（ctypes → .so → DBus）
32. memoryhub/embedding/mock_client.py       ← Mock 实现
33. memoryhub/safety_rules/{models,loader,components,paths,regex_safety,versions}.py  ← 声明式规则库
```

---

### 第七阶段：辅助模块

```
34. memoryhub/adapter/{agent_api,management_api,memory_v2_api,simulator,user_rule_schemas}.py  ← 其余 4 个 Router + 模拟器
35. memoryhub/adapter/service.py             ← MemoryService 最小垂直切片（集成测试）
36. evaluation/metrics/{retrieval_eval,latency_benchmark,preference_eval,conflict_eval,full_chain_benchmark}.py
37. evaluation/run_*.py                      ← 6 个评测驱动（retrieval / latency / milvus / milvus_mock / http / validate）
38. agent-integration/{memoryhub_cli,memoryhub_mcp,memoryhub_client,plugin/opencode}/  ← 三件套
```

---

### 速查：按问题找文件

| 想了解什么 | 直接读 |
|-----------|--------|
| 数据结构长什么样 | `schemas.py` + [`INTERFACE.md`](INTERFACE.md) |
| 一个请求从进来到出去的全流程 | `app.py` → `api.py` → `service.py:EventIngestionService` → `extraction.py` → `milvus_hybrid.py` |
| 偏好怎么从用户话里提取出来 | `preference/extractor.py` + `preference/tool_miner.py`（统计式） |
| 检索怎么融合稠密 + 稀疏 | `retrieval/milvus_hybrid.py`（生产）+ `retrieval/hybrid.py`（降级） |
| 冲突怎么自动解决 | `conflict/resolver.py`（4 种决策） + `knowledge/updater.py`（3 种 KnowledgeConflictResolution） |
| 记忆怎么从短期变成长期 | `lifecycle/{session_consolidator,memory_consolidator,degrader,scheduler}.py` |
| 怎么"忘掉"一条记忆 | `core/forget/forgetter.py` + `core/forget/auto_forget.py` + `core/forget/health.py` |
| 数据怎么存到磁盘 | `storage/database.py` + `storage/models.py` + `storage/vector_engine/` |
| 安全门禁怎么工作 | `core/safety/gate.py` + `core/safety/{detector,audit_log,quarantine,user_rules}.py` |
| 写入怎么保证可靠 | `core/memory_write.py` + `core/domain_writer.py` + `storage/projection_outbox.py` |
| 麒麟原生化怎么落地 | `embedding/kylin_client.py` + `storage/vector_engine/milvus_engine.py` + `packaging/linux/build-deb.sh` + `third_party/libkysdk-vector-engine-client-nile-sp2/` |
| Qt 桌面控制台 26 页面 | `desktop-client/src/pages/` + `desktop-client/src/MainWindow.cpp:337-365` |
| Agent 怎么接入 | `agent-integration/docs/CONTRACT.md` + `agent-integration/memoryhub_mcp/tools.py` + `agent-integration/memoryhub_cli/cli.py` |
