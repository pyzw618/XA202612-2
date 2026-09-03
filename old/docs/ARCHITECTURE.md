# Kylin-MemoryHub 架构可视化

> **数据契约说明（v0.1.0）**：模块间统一事件以 [`memoryhub/adapter/schemas.py`](../memoryhub/adapter/schemas.py) 的 `MemoryEvent`（Schema 1.1）和 [`INTERFACE.md`](INTERFACE.md) 为准；本文中所有「代码事实」均以当前 `main` 分支源码为准（`memoryhub/app.py`、`memoryhub/core/*`、`memoryhub/retrieval/*`、`desktop-client/`、`agent-integration/`）。
>
> **生产栈 vs 开发栈**：默认架构图描绘「端侧生产栈」（麒麟 Embedding SDK + Milvus）；开发/测试栈使用 `MockEmbeddingClient` + `MilvusHybridRetriever(mock=True)` 或 `FAISSVectorEngine`（详见 `memoryhub/storage/vector_engine/__init__.py` 工厂）。`runtime.mode=production` 下强制生产栈，由 `memoryhub/config.py:validate_production_gate()` 与 `validate_production_runtime()` 双层门禁校验。
>
> **统一写入契约**：所有内容写入最终都收敛到 `MemoryWriteService.upsert_memory()`（`memoryhub/core/memory_write.py:98-158`）→ `DomainMemoryWriter` 单事务（`memoryhub/core/domain_writer.py`），下游 SQLite 是事实源，向量/关键词/缓存通过 `ProjectionOutboxWorker`（`memoryhub/storage/projection_outbox.py`）异步投影。`SafetyWriteGate.route()`（`memoryhub/core/safety/gate.py:181-`）是 `ApprovedWrite` 能力的唯一发放点。

---

## 1. 系统整体架构（分层视图）

> **代码事实**（v0.1.0）：应用入口 `memoryhub/app.py:171-866` 的 `create_app()` 注册 **5 个 Router**（`api.py:58` `/api/memory`、`agent_api.py:24` `/api/agent` + `:27` `/api`、`management_api.py:44` `/api/memory` 管理类、`memory_v2_api.py:18` `/api/memory/v2`）。8 个核心子模块：`ingestion / preference / knowledge / conflict / forget / safety / lifecycle / memory`；新增 `fact` 已并入 `knowledge/extract_facts`。检索器**生产唯一装配 `MilvusHybridRetriever`**（`retrieval/milvus_hybrid.py:106-520`），开发/测试模式才用 `HybridRetriever`（`retrieval/hybrid.py:23-308`）。

```mermaid
graph TB
    subgraph L1["第 1 层 · OS Agent 接入"]
        User["👤 用户"]
        Agent["OS Agent<br/>对话理解 / 任务规划 / 工具调用"]
        Simulator["Agent Simulator<br/>模拟器（演示用）"]
    end

    subgraph L2["第 2 层 · Memory Adapter 标准接口"]
        API["FastAPI REST API<br/>POST /events · /search · /forget<br/>GET /preferences · /knowledge"]
        Schemas["Pydantic Schemas<br/>统一数据结构定义"]
    end

    subgraph L3["第 3 层 · 多源数据接入 Ingestion"]
        Cleaner["DataCleaner<br/>字段校验 · 去重"]
        Normalizer["DataNormalizer<br/>标准化为 MemoryEvent"]
        Quality["QualityScorer<br/>质量评分"]
        Safety["SensitiveDetector<br/>敏感信息检测"]
    end

    subgraph L4["第 4 层 · Memory Core 记忆核心"]
        PrefExtract["PreferenceExtractor<br/>偏好抽取（规则+LLM）"]
        PrefConf["ConfidenceCalculator<br/>置信度计算"]
        PrefUpdate["PreferenceUpdater<br/>版本管理"]
        KnowExtract["KnowledgeExtractor<br/>知识抽取"]
        Template["TemplateBuilder<br/>模板构建"]
        Workflow["WorkflowMiner<br/>工作流挖掘"]
        ConflictDet["ConflictDetector<br/>冲突检测"]
        ConflictRes["ConflictResolver<br/>冲突解决"]
        Forget["MemoryForgetter<br/>精准遗忘"]
        Lifecycle["LifecycleManager<br/>短/中/长期流转"]
    end

    subgraph L5["第 5 层 · Retrieval Engine 混合检索"]
        MilvusHybrid["MilvusHybridRetriever<br/>生产唯一 · RRF 融合"]
        Hybrid["HybridRetriever<br/>dev/test 降级 · FAISS+BM25"]
        Vector["VectorSearcher<br/>FAISS IndexFlatIP"]
        Keyword["KeywordSearcher<br/>rank-bm25 + jieba"]
        Rerank["Reranker<br/>6 因子加权"]
        Cache["SearchCache<br/>LRU+TTL · 索引版本隔离"]
        QueryCache["query_vector_cache<br/>1000 条查询向量 LRU"]
    end

    subgraph L6["第 6 层 · Local Runtime 本地存储 + 麒麟原生"]
        SQLite["SQLite + SQLAlchemy<br/>events · preferences · knowledge<br/>memory_lineage/evidence/outbox<br/>extraction_tasks · short/mid_term"]
        Outbox["ProjectionOutbox<br/>durable · 后台 worker 投影"]
        MilvusSDK["libkysdk-vector-engine-client<br/>C++ → C API 桥接 → Milvus gRPC"]
        KylinSDK["libkylin-coreai-embedding.so<br/>ctypes → DBus → 768 维"]
        Evidence["EvidenceStore<br/>JSONL 证据链"]
    end

    subgraph L7["第 7 层 · Evaluation & Console"]
        EvalPref["PreferenceEvaluator"]
        EvalRet["RetrievalEvaluator"]
        EvalConf["ConflictEvaluator"]
        Bench["LatencyBenchmark"]
        Qt5["Qt 5 桌面客户端<br/>desktop-client"]
    end

    User --> Agent
    User -.-> Simulator
    Agent --> API
    Simulator --> API

    API --> Schemas
    API --> Cleaner
    Cleaner --> Normalizer --> Quality --> Safety

    Safety -->|MemoryEvent| PrefExtract
    Safety -->|MemoryEvent| KnowExtract
    PrefExtract --> PrefConf --> PrefUpdate
    KnowExtract --> Template
    KnowExtract --> Workflow
    PrefUpdate --> ConflictDet
    ConflictDet --> ConflictRes
    ConflictRes --> SQLite

    API --> MilvusHybrid
    MilvusHybrid --> Hybrid
    MilvusHybrid --> Cache
    MilvusHybrid --> QueryCache
    MilvusHybrid --> MilvusSDK
    MilvusHybrid --> KylinSDK
    Hybrid --> Vector
    Hybrid --> Keyword
    Hybrid --> Rerank
    Hybrid --> Cache

    PrefUpdate --> SQLite
    PrefUpdate --> Outbox
    KnowExtract --> SQLite
    KnowExtract --> Outbox
    SQLite --> Outbox
    Outbox --> MilvusSDK
    Outbox --> Vector
    Outbox --> Keyword
    Outbox --> Cache
    SQLite --> Evidence

    API --> Forget
    Forget --> SQLite
    Forget --> FAISS
    Forget --> Cache
    Forget --> Evidence

    Lifecycle --> SQLite

    EvalPref --> API
    EvalRet --> API
    EvalConf --> API
    Bench --> API
    Qt5 --> API

    style L1 fill:#e3f2fd,stroke:#1565c0
    style L2 fill:#e8f5e9,stroke:#2e7d32
    style L3 fill:#fff3e0,stroke:#e65100
    style L4 fill:#fce4ec,stroke:#b71c1c
    style L5 fill:#f3e5f5,stroke:#6a1b9a
    style L6 fill:#e0f2f1,stroke:#00695c
    style L7 fill:#f5f5f5,stroke:#424242
```

---

## 2. 写入数据流（事件 → 记忆）

> 当前 v0.1.0 已完成 Safety 数据/方法契约、版本化规则库、递归扫描、策略执行、
> 用户自定义敏感规则 Overlay、事件脱敏、同快照复检、最小化持久审计、REVIEW
> 加密隔离和强制写入 Gate。
> `POST /api/memory/events` 已接入完整摄取管线（`EventIngestionService`）：
> 幂等去重 → 质量评分 → 安全门禁 → 偏好/知识/事实抽取 → 失败重试队列。
> 所有内容写入（事件、显式偏好/知识、反馈更新）都必须经 `SafetyWriteGate`
> 签发能力后才落到受保护 sink（SQLite / Embedding / 向量 / 证据）。

```mermaid
flowchart TD
    A["OS Agent 工具调用完成<br/>/ 用户反馈 / 手动配置"] --> B["POST /api/memory/events<br/>WriteEventRequest"]

    B --> C["DataCleaner.clean()<br/>字段校验 · 去重 · 格式化"]
    C --> D["DataNormalizer.normalize()<br/>统一转化为 MemoryEvent"]
    D --> E["QualityScorer.score()<br/>计算 quality_score [0,1]"]
    E --> Overlay["按 event.user_id 获取不可变用户规则 Overlay<br/>失败关闭 · 每事件固定 detector"]
    Overlay --> F["SensitiveDetector.scan()<br/>组合内置规则与用户内容规则<br/>生成带实例内完整性标签的 SafetyReport"]
    F --> G["SensitiveDetector.decide()<br/>验证报告/策略快照 · 聚合规则动作"]

    G -->|REJECT| Rj["❌ 拒绝入库"]
    G -->|REVIEW| Rev["⏸ 隔离复核<br/>不进入存储/Embedding/普通日志"]
    G -->|MASK| H["SensitiveDetector.sanitize()<br/>按报告精确脱敏"]
    H --> V["同一规则快照复检"]
    V -->|未通过| Rev
    V -->|通过| Pass["递归只读安全事件"]
    G -->|ALLOW| Pass

    Rj --> Audit["build_audit(report, final_decision)<br/>内存安全投影"]
    Rev --> Audit
    Pass --> Audit
    Audit --> Trust["validate_result(event, result)<br/>验证结果 HMAC · 重决策 · 重派生"]
    Trust --> Journal["SafetyAuditLog.append()<br/>最小投影 · 自脱敏 · HMAC 哈希链"]
    Journal --> Gate{"SafetyWriteGate<br/>审计回执有效？"}
    Gate -->|ALLOW / MASK 已复检| Cap["签发 ApprovedWrite<br/>绑定审计记录与安全输出"]
    Cap --> I["受保护内容 sinks<br/>SQLite · Embedding · 向量 · 证据"]
    Gate -->|ALLOW / MASK 最小日志| SafeLog["SafeLogRecord<br/>不含事件正文或用户 ID"]
    Gate -->|REVIEW| QStore["ReviewQuarantineStore<br/>AES-256-GCM 独立隔离"]
    Gate -->|REJECT| Stop["停止普通写入链"]
    QStore --> Stop

    I --> J{"event_type?"}

    J -->|user_feedback<br/>user_behavior| K["PreferenceExtractor.extract()"]
    J -->|task_trajectory| L["KnowledgeExtractor.extract_from_trajectory()"]
    J -->|tool_call<br/>manual_config| M["仅存储事件<br/>等待后续聚合"]

    K --> N["ConfidenceCalculator.calculate()<br/>计算置信度"]
    N --> O{"Quality >= 0.6?"}
    O -->|否| P["→ 短期记忆 (SHORT)"]
    O -->|是| Q["ConflictDetector.check_preference()"]

    Q -->|无冲突| R["PreferenceUpdater.add()<br/>写入 preferences 表"]
    Q -->|有冲突| S["ConflictResolver.resolve()"]
    S -->|override| R
    S -->|merge| T["PreferenceUpdater.merge()"]
    S -->|coexist| U["两条记忆按不同 scope 保留"]
    S -->|pending| V["写入 conflicts 表<br/>等待用户确认"]

    R --> W["Embedding.embed()<br/>文本向量化"]
    W --> X["VectorStore.add()<br/>存入 FAISS 索引"]
    R --> Y["EvidenceStore.save()<br/>保存证据链"]

    L --> Z["KnowledgeExtractor<br/>.extract_workflow / case / template"]
    Z --> AA["ConflictDetector.check_knowledge()"]
    AA -->|无冲突| AB["KnowledgeRepository.save()"]
    AA -->|有冲突| S
    AB --> W

    T --> W
    U --> W

    style G fill:#ffcdd2,stroke:#c62828
    style P fill:#fff9c4,stroke:#f9a825
    style V fill:#fff9c4,stroke:#f9a825
    style R fill:#c8e6c9,stroke:#2e7d32
    style AB fill:#c8e6c9,stroke:#2e7d32
```

---

## 3. 检索数据流（生产栈 MilvusHybridRetriever）

> **代码事实**：生产环境仅装配 `MilvusHybridRetriever`（`memoryhub/retrieval/milvus_hybrid.py:106-520`），由 `memoryhub/app.py:711-738` 在 `runtime.mode=production` 下强制装配；开发/测试模式才使用 `HybridRetriever`（`retrieval/hybrid.py:23-308`，FAISS + BM25 手动加权）。生产检索器在 Milvus 引擎内部完成稠密 + 稀疏的 RRF（Reciprocal Rank Fusion）融合，Python 侧只取 Top-K。

```mermaid
flowchart TD
    A["OS Agent 发起检索<br/>POST /api/memory/search"] --> B["SearchRequest<br/>{query, context, top_k, level}"]

    B --> C["MilvusHybridRetriever.search()<br/>缓存键 = version + canonical_json"]
    C -->|SearchCache 命中| D["✅ 直接返回缓存结果<br/>（结果缓存 LRU+TTL）"]
    C -->|未命中| E["query_vector_cache 检查<br/>1000 条 LRU"]

    E -->|向量命中| F2["直接复用 768 维向量"]
    E -->|未命中| F["KylinEmbeddingClient.embed()<br/>ctypes → DBus → 768 维向量"]

    F --> G["build_sparse_vector(query)<br/>FNV-1a 与 C 侧逐位一致"]
    G --> H["Milvus engine.hybrid_search<br/>(dense, sparse) → RRF 融合"]
    H --> I["metadata 后过滤<br/>user_id / status / memory_type"]
    I --> J["SQLite 回表补齐 + 限 20 候选"]
    J --> K["Reranker 6 因子加权<br/>原始/相关/scope/置信/新鲜/健康"]
    K --> L["format_response → SearchResponse<br/>preferences / knowledge / facts"]
    L --> M["SearchCache.set() 按 index_version 失效"]

    style D fill:#c8e6c9,stroke:#2e7d32
    style M fill:#c8e6c9,stroke:#2e7d32
    style L fill:#e3f2fd,stroke:#1565c0
```

---

## 4. 精准遗忘数据流

```mermaid
flowchart TD
    A["用户: 忘掉我关于周报格式的偏好"] --> B["POST /api/memory/forget<br/>ForgetRequest {instruction}"]

    B --> C["MemoryForgetter.parse_intent()<br/>LLM 解析遗忘意图"]

    C --> D["输出:<br/>{memory_type: preference,<br/> target_topic: 周报格式,<br/> scope: office.weekly_report}"]

    D --> E["MemoryForgetter.locate_memories()<br/>查询 SQLite 定位目标记忆"]
    E --> F["目标: pref_001, pref_003"]

    F --> G["并行清理"]

    G --> H["MemoryWriteService.upsert_memory<br/>SUPERSEDE 软删 + 谱系"]
    G --> I["MilvusHybridRetriever.index_version++<br/>向量投影自动失效"]
    G --> J["SearchCache.clear()"]
    G --> K["MemoryEvidenceRepository 删证据链"]

    H --> L["统计删除数量"]
    I --> L
    J --> L
    K --> L

    L --> M["MemoryForgetter.create_audit_log()<br/>生成 ForgetRecord"]
    M --> N["存入 forget_history 表<br/>（含被删记忆快照）"]

    N --> O["返回 ForgetResponse<br/>{record_id, deleted_count, deleted_ids}"]

    style A fill:#fff3e0,stroke:#e65100
    style O fill:#c8e6c9,stroke:#2e7d32
```

---

## 5. 记忆生命周期流转（三引擎 + Scheduler）

> **代码事实**：v0.1.0 已实现**三引擎 + 后台调度器**架构（`memoryhub/core/lifecycle/`）：`SessionConsolidator`（短期 → 中期）、`MemoryConsolidator`（中期 → 长期，含 `consolidate_tool_preferences()` 触发 `ToolPreferenceMiner`）、`MemoryDegrader`（长期低健康度 → 中期情景 `epi_dg_*`）。`LifecycleScheduler`（`scheduler.py:25-104`）后台线程每 300s 跑 `run_consolidation_cycle()`。手动触发入口 `POST /api/memory/lifecycle/{auto-forget,check,consolidate}`（`memoryhub/adapter/management_api.py:669-772`）。
>
> 健康度公式（`core/forget/health.py:54-75`）：`health = 0.6·time_decay + 0.4·usage_frequency`，上限 = confidence；艾宾浩斯 `R = e^(-t/S)`，其中 `S = half_life/ln2 · (1 + hits/10)`（复习强化）。`AutoForgetEngine` 阈值常量（`core/forget/auto_forget.py:20-22`）：`ARCHIVE_THRESHOLD=0.2` / `DEMOTE_THRESHOLD=0.4` / `REVIEW_THRESHOLD=0.6`。

```mermaid
stateDiagram-v2
    [*] --> SHORT: 新事件写入<br/>EventIngestionService._buffer_short_term<br/>TTL 24h

    SHORT --> MID: SessionConsolidator<br/>会话结束聚合
    SHORT --> [*]: 任务结束未被引用

    MID --> LONG: MemoryConsolidator<br/>consolidate_episodes<br/>consolidate_tool_preferences<br/>consolidate_workflow_preferences

    MID --> MID: 长期低健康度 →<br/>MemoryDegrader 写 epi_dg_* 情景<br/>+ 长期 ARCHIVED

    LONG --> EXPIRED: AutoForgetEngine<br/>health < 0.2 归档
    LONG --> LONG: feedback confirm →<br/>hits +1 → S 复习强化

    EXPIRED --> [*]: archived · 不参与检索<br/>保留审计和回溯

    note right of SHORT
        短期工作记忆
        - 当前会话/任务内
        - 不参与跨任务检索
    end note

    note right of MID
        中期情景
        - 候选偏好 / 近期案例
        - 可被检索，置信度较低
    end note

    note right of LONG
        长期记忆
        - 稳定偏好 / 工作流 / 模板 / 事实
        - 主要检索来源
    end note

    note right of EXPIRED
        自动遗忘
        - 健康度 < 0.2 自动归档
        - 0.2 ≤ h < 0.4 降级为中期
        - 0.4 ≤ h < 0.6 待审查
    end note
```

---

## 6. 模块依赖关系（v0.1.0 真实拓扑）

> **代码事实**：v0.1.0 在 `memoryhub/core/` 下有 **8 个核心子模块**：`ingestion / preference / knowledge / conflict / forget / safety / lifecycle / memory`（`memory` 是共享基元：BaseMemoryHandler / UnifiedConfidenceCalculator / EvidenceMerger / StructuredLLMAdapter / freshness_score）。`memoryhub/retrieval/` 拆分为生产检索器 `milvus_hybrid.py` + 降级 `hybrid.py`。`storage/vector_engine/` 拆分为 `faiss_engine / milvus_engine / _milvus_ctypes / sparse`（FNV-1a 稀疏向量）。

```mermaid
graph LR
    subgraph 入口层
        APP["app.py:171-866<br/>create_app() + lifespan"]
        API["adapter/api.py<br/>/api/memory"]
        Agent["adapter/agent_api.py<br/>/api/agent + /api"]
        Mgmt["adapter/management_api.py<br/>/api/memory 管理类"]
        V2["adapter/memory_v2_api.py<br/>/api/memory/v2"]
    end

    subgraph 数据结构层
        Schemas["adapter/schemas.py 1781 行<br/>⭐ 所有模块共享"]
        USchemas["adapter/user_rule_schemas.py"]
    end

    subgraph 核心逻辑层（8 模块）
        Ingestion["core/ingestion/<br/>+ adapters/"]
        Preference["core/preference/"]
        Knowledge["core/knowledge/<br/>（含 fact）"]
        Conflict["core/conflict/"]
        Forget["core/forget/<br/>（含 health）"]
        Safety["core/safety/<br/>（含 gate）"]
        Lifecycle["core/lifecycle/"]
        Memory["core/memory/<br/>（基元）"]
    end

    subgraph 检索层
        MilvusHybrid["retrieval/milvus_hybrid.py<br/>生产唯一"]
        Hybrid["retrieval/hybrid.py<br/>dev/test 降级"]
        VS["vector_search.py / keyword_search.py<br/>reranker.py / cache.py"]
    end

    subgraph 存储层
        DB["storage/database.py + models.py<br/>12 张表 + 8 个 Repository"]
        VEng["storage/vector_engine/<br/>milvus_engine / faiss_engine"]
        Sync["sync_service + projection_outbox +<br/>compensation_task"]
        Meta["memory_metadata.py<br/>lineage/evidence/outbox"]
    end

    subgraph 抽象层
        LLM["llm/openai_client.py"]
        Embed["embedding/kylin_client.py<br/>+ mock_client.py"]
        Rules["safety_rules/<br/>声明式规则库"]
    end

    APP --> API & Agent & Mgmt & V2
    APP --> DB & VEng & Embed & LLM & Rules

    API & Agent & Mgmt & V2 --> Schemas
    API --> Ingestion & Preference & Knowledge & Conflict & Forget & Safety & Lifecycle
    Mgmt --> DB & Forget & Lifecycle & Safety & Sync
    V2 --> Meta

    Ingestion --> Schemas & Safety & Rules
    Preference --> Schemas & Memory & Conflict & DB & Embed & LLM
    Knowledge --> Schemas & Memory & Conflict & DB & Embed & LLM
    Conflict --> Schemas & Memory & LLM
    Forget --> Schemas & Memory & DB
    Safety --> Schemas & Memory & LLM & Rules & DB
    Lifecycle --> DB & Memory & Sync

    MilvusHybrid --> Hybrid & VS & DB & Embed & VEng & Meta
    Hybrid --> VS & DB & Embed

    style Schemas fill:#ffcdd2,stroke:#c62828,stroke-width:3px
    style MilvusHybrid fill:#a29bfe,color:#fff
```

---

## 7. 麒麟 Embedding SDK 调用链

```mermaid
sequenceDiagram
    participant App as MemoryHub
    participant PyClient as KylinEmbeddingClient<br/>(Python)
    participant CT as ctypes 封装
    participant SO as libkylin-coreai-embedding.so<br/>(C 动态库)
    participant DBus as D-Bus
    participant Service as 麒麟 Embedding 服务

    App->>PyClient: embed("项目周报生成流程")
    PyClient->>CT: 调用 C 函数
    CT->>SO: text_embedding(session, text, &result)
    SO->>DBus: 发送向量化请求
    DBus->>Service: 调用本地 embedding 模型
    Service-->>DBus: 返回 float* 向量数据
    DBus-->>SO: 返回 EmbeddingResult
    SO-->>CT: 返回 result 指针
    CT->>CT: embedding_result_get_vector_data(result)<br/>embedding_result_get_vector_length(result)
    CT-->>PyClient: float[] 向量
    PyClient->>CT: embedding_result_destroy(&result)
    CT-->>PyClient: 资源释放完成
    PyClient-->>App: list[float] 向量

    Note over App,Service: 同步调用，单次约 10-100ms
```

---

## 8. 混合检索融合策略

```mermaid
flowchart LR
    Q["查询文本"] --> V["向量路径"]
    Q --> K["关键词路径"]
    Q --> M["元数据路径"]

    subgraph V["向量路径 (weight=0.6)"]
        V1["embed(query)"] --> V2["FAISS.search()"] --> V3["vector_results"]
    end

    subgraph K["关键词路径 (weight=0.3)"]
        K1["jieba.cut(query)"] --> K2["BM25.get_scores()"] --> K3["keyword_results"]
    end

    subgraph M["元数据路径 (weight=0.1)"]
        M1["scope 过滤"] --> M2["status 过滤"] --> M3["metadata_results"]
    end

    V3 --> Merge["按 memory_id 合并<br/>final = 0.6×V + 0.3×K + 0.1×M"]
    K3 --> Merge
    M3 --> Merge

    Merge --> Filter["scope 匹配<br/>confidence ≥ 阈值"]
    Filter --> Rerank["Reranker 重排序<br/>+相关性 +scope匹配 +新鲜度"]
    Rerank --> TopK["取 Top-K"]

    style V fill:#e3f2fd,stroke:#1565c0
    style K fill:#fff3e0,stroke:#e65100
    style M fill:#e8f5e9,stroke:#2e7d32
```

---

## 9. 偏好抽取决策流程

```mermaid
flowchart TD
    E["MemoryEvent<br/>event_type = user_feedback<br/>content.text = '以后都用 Markdown 写周报'"] --> R{"规则匹配"}

    R -->|匹配成功| R1["规则模板:<br/>'以后都用 X' → format_preference<br/>content = 'X'"]
    R -->|未匹配| L["LLM 抽取"]

    L --> L1["Prompt:<br/>请从以下用户反馈中<br/>识别隐式偏好..."]
    L1 --> L2["LLM 返回:<br/>{type: format_preference,<br/> content: '周报使用 Markdown'}"]

    R1 --> Merge["合并去重"]
    L2 --> Merge

    Merge --> Type["classify_type()<br/>确定偏好类型"]
    Type --> Scope["_detect_scene()<br/>确定 scope"]
    Scope --> Evidence["_build_evidence()<br/>绑定证据链"]
    Evidence --> Conf["ConfidenceCalculator.calculate()"]

    Conf --> ConfRule["因子计算:<br/>证据数量 × 来源权重<br/>× 时间衰减 × 一致性"]
    ConfRule --> Score["confidence = 0.92"]

    Score --> Check["ConflictDetector.check_preference()"]
    Check -->|无冲突| Add["PreferenceUpdater.add()<br/>✅ 写入偏好记忆"]
    Check -->|有冲突| Resolve["ConflictResolver.resolve()"]

    style Add fill:#c8e6c9,stroke:#2e7d32
    style Resolve fill:#fff9c4,stroke:#f9a825
```

---

## 10. 端到端演示场景（周报生成）

```mermaid
sequenceDiagram
    actor User as 👤 用户
    participant Agent as OS Agent
    participant Hub as MemoryHub
    participant DB as SQLite + FAISS

    Note over User,DB: === 第一次：用户生成周报 ===

    User->>Agent: 帮我整理这周项目进展，生成周报
    Agent->>Hub: POST /search {query: "项目周报"}
    Hub->>DB: 检索偏好和知识
    DB-->>Hub: 无历史记忆
    Hub-->>Agent: SearchResponse {空}
    Agent->>Agent: 模拟执行: 日历→文件→报告
    Agent->>Hub: POST /events {tool_call 事件×4}
    Hub->>DB: 存储事件

    User->>Agent: 以后周报都用 Markdown，分三部分
    Agent->>Hub: POST /events {user_feedback}
    Hub->>Hub: PreferenceExtractor → 规则匹配
    Hub->>Hub: "以后都用 X" → format_preference
    Hub->>DB: 写入偏好 pref_001 (confidence=0.92)
    Hub->>DB: 存入 FAISS 向量

    Note over User,DB: === 第二次：复用记忆 ===

    User->>Agent: 按上次的方式生成这周周报
    Agent->>Hub: POST /search {query: "项目周报"}
    Hub->>DB: 向量+关键词+元数据混合检索
    DB-->>Hub: [pref_001, know_001]
    Hub-->>Agent: {preferences: Markdown三段式,<br/>knowledge: 周报生成流程}
    Agent->>Agent: 自动按偏好执行
    Agent-->>User: ✅ Markdown 三段式周报

    Note over User,DB: === 冲突场景 ===

    User->>Agent: 以后周报改成 Word
    Agent->>Hub: POST /events {user_feedback}
    Hub->>Hub: 检测到冲突: Markdown vs Word
    Hub->>Hub: 显式反馈 → 自动 override
    Hub->>DB: pref_001 → archived<br/>pref_002 active (version=2)
```

---

## 11. 前端页面与 API 对应关系

前端实现为 **Qt 5 原生桌面客户端**（`desktop-client/`），按当前 `main` 分支真实代码（`MainWindow.cpp:337-365` 注册 `registerPage(key, group, title, page)`）落地，共 **26 个 pageKey，6 大组**：

- **总览 / 内置终端**：`dashboard` / `terminal`（共 2）
- **记忆管理**：`mem/preference` / `mem/knowledge` / `mem/fact` / `mem/tiers`（共 4）
- **检索与冲突**：`search` / `conflicts` / `projections`（共 3）
- **遗忘与生命周期**：`forget/precise|pending|archived|recycle|health|history|settings`（共 7，全部在 `pages/ForgetPages.cpp`）
- **安全中心**：`safety/overview|user-rules|audit|quarantine`（共 4，全部在 `pages/SafetyPages.cpp`）
- **系统设置**：`settings/status|llm|config|demo`（共 4，全部在 `pages/SettingsPages.cpp`）

复用组件 12 个（`widgets/`）：`PageHeader / StatCard / ScoreRing / StatusTag / JsonViewer / EmptyState / DetailDrawer / MemoryFilterBar / ConfirmDialog / RoundedContainer / PageStateView / ProvenancePanel`。API 客户端 1 个（`api/ApiClient.cpp`，同步 + 异步 + Result 错误码）+ `j::` JSON 工具命名空间。

```mermaid
graph LR
    subgraph Qt5 桌面客户端（26 pageKey）
        P1["📊 总览 Dashboard"]
        P2["🧠 偏好 / 知识 / 事实 / 分层"]
        P3["🔍 检索测试 / 冲突中心 / 投影恢复"]
        P4["🗑 遗忘与生命周期（7 页）"]
        P5["🛡 安全中心（4 页）"]
        P6["⚙ 系统设置（4 页）"]
        P0["💻 内置 opencode 终端"]
    end

    subgraph REST API（5 Router）
        A1["GET /api/memory/preferences|knowledge|facts"]
        A2["POST /api/memory/search | /context"]
        A3["GET /api/memory/conflicts; POST .../resolve"]
        A4["POST /api/memory/forget[/preview]; GET .../history"]
        A5["PATCH /api/memory/memories/{id}/status; POST .../delete"]
        A6["GET /api/memory/memories/health"]
        A7["CRUD /api/memory/safety/user-rules"]
        A8["GET /api/memory/safety/audit-logs[/verify]"]
        A9["GET /api/memory/system/status | /config"]
        A10["GET /api/memory/safety/quarantine[/...]"]
        A11["POST /api/memory/lifecycle/{auto-forget,check,consolidate}"]
        A12["GET /api/memory/v2/memories/{id}/{lineage,evidence,audit}"]
        A13["GET /api/memory/short-term | /mid-term"]
        A14["GET /api/memory/extraction/tasks[/metrics]"]
    end

    P1 --> A1 & A6
    P2 --> A1 & A5 & A14
    P3 --> A2 & A3 & A12
    P4 --> A4 & A5 & A6 & A11 & A13
    P5 --> A7 & A8 & A10
    P6 --> A9
    P0 --> AgentSide["OS Agent / opencode 进程"]
    AgentSide --> A1 & A2
```

用户规则接口（`A7`）必须携带 `X-MemoryHub-User` 请求头；matcher 仅在创建或替换时
发送，读取响应不包含 matcher，数据库只存 AES-256-GCM 密文。其余管理类接口（审计
验链、隔离区放行、批量状态流转、健康度、生命周期触发）由 `management_api.py`
提供，详见 `desktop-client/README.md` 与接口文档。

---

## 12. 麒麟系统原生化（生产栈全景）

> **本章与《技术报告》第 9 章配套**；这里是图层面，最详细的代码事实见 `docs/MemoryHub_技术报告.md` §5 与 `docs/技术报告_框架_v1.docx` 第 9 章。

```mermaid
graph TB
    subgraph App["MemoryHub Python 进程（memoryhub/app.py）"]
        PY["FastAPI / 业务代码"]
        ECLI["KylinEmbeddingClient<br/>(ctypes)"]
        VENG["MilvusVectorEngine<br/>+ _MilvusCAPI"]
    end

    subgraph SDK["麒麟系统预装 .so"]
        EMB["libkylin-coreai-embedding.so<br/>C API"]
        VEC["libkysdk-vector-engine-client.so<br/>C++ SDK"]
    end

    subgraph Bridge["自编译 C API 桥接层"]
        CAPI["libkysdk-vector-engine-client-capi.so<br/>third_party/libkysdk-vector-engine-client-nile-sp2/<br/>capi/c_api_bridge.cpp"]
    end

    subgraph Daemon["麒麟系统服务"]
        DBus["D-Bus System Bus<br/>text_embedding 服务"]
        Milvus["Milvus gRPC Server<br/>:19530"]
    end

    PY --> ECLI
    PY --> VENG
    ECLI -->|ctypes.CDLL| EMB
    EMB -->|create/init/init_model/embed| DBus
    VENG -->|ctypes.CDLL| CAPI
    CAPI -->|包装 C++| VEC
    VEC -->|gRPC :19530| Milvus

    style EMB fill:#ffeaa7,stroke:#d35400
    style VEC fill:#ffeaa7,stroke:#d35400
    style CAPI fill:#fab1a0,stroke:#e17055
    style DBus fill:#74b9ff,color:#fff
    style Milvus fill:#74b9ff,color:#fff
```

**生产栈硬约束**（`memoryhub/config.py:494-584` 双层校验）：

| # | 约束 | 违规行为 |
|---|---|---|
| 1 | `runtime.allow_fallback = false` | ProductionGateError |
| 2 | `embedding.provider = "kylin"`（禁止 mock / kylin_mock / auto） | 同上 |
| 3 | `embedding.dimension = 768` | 同上 |
| 4 | `vector_engine.provider = "milvus"`，`app_id` 非空 | 同上 |
| 5 | 运行时 `KylinEmbeddingClient.is_available()=true` 且 `get_dimension()=768`；`MilvusVectorEngine` 已连接且未关闭 | 同上 |

**端到端延迟预算**（`config.yaml retrieval.target_p95_ms / target_p99_ms`）：350ms / 500ms。`KylinEmbeddingClient` 单次超时 250ms；`MilvusVectorEngine` 单次超时 120ms。

**运行时契约部署前自检**：`scripts/check_kylin_embedding_runtime.py`（输出 `kylin_runtime_check.json`）逐项确认 8 条契约；`scripts/verify_kylin_environment.py` 验证开发栈 mock SDK。

---

## 13. Agent 接入三件套（CLI / MCP / OpenCode Plugin）

> **代码事实**：所有接入统一走同一份 REST 契约（`memoryhub/app.py` 5 Router）；CLI 是「记忆能力母语」，MCP / Plugin / 桌面控制台都是 CLI 薄壳或 REST 适配，逻辑零分叉。

```mermaid
graph LR
    subgraph Side["Agent 侧"]
        Agent["OS Agent"]
        OC["opencode"]
        CC["Claude Code"]
        Self["自研 Agent"]
    end

    subgraph Access["agent-integration/ 接入层"]
        CLI["memoryhub CLI<br/>argparse 17+ 子命令<br/>pyproject:memoryhub = memoryhub_cli.cli:main"]
        MCP["memoryhub_mcp<br/>MCP server stdio JSON-RPC<br/>8 工具"]
        Plugin["plugin/opencode/<br/>3 custom tools<br/>5 slash commands<br/>1 skill + 3 hooks"]
    end

    subgraph Backend["MemoryHub 后端"]
        REST["5 Router :8099"]
    end

    Agent --> CLI
    Agent --> MCP
    OC --> Plugin --> CLI
    OC -.可选.-> MCP
    CC --> MCP
    Self --> CLI
    Self --> MCP

    CLI --> REST
    MCP --> REST
    Plugin -.通过 CLI.-> REST
```

**CLI 17+ 子命令**（`agent-integration/memoryhub_cli/cli.py`）：`search / context / event / remember / update / forget [--preview] / list / get / provenance / projection list|replay / feedback / review / resolve / decide / knowledge fact propose / export / import / status / service / completion`。

**MCP 8 工具**（`memoryhub_mcp/tools.py:ToolRegistry._register()`）：
`memoryhub_health / search / get_context / write_event / remember / forget / feedback / knowledge_fact_propose`。

**OpenCode Plugin**（`agent-integration/plugin/opencode/`）：
- 3 custom tools：`memoryhub_search / memoryhub_get_context / memoryhub_remember`（薄壳调 CLI）
- 5 slash commands：`/memoryhub-context / -forget / -remember / -review / -status`
- 1 skill：`memory-awareness/SKILL.md`（agent 按 description 自动发现，判断何时调用记忆）
- 3 hooks：`tool.execute.after`（累积工具轨迹）+ `session.status(idle)` 冲刷 + `session.deleted` 兜底 + `experimental.session.compacting`（注入记忆到压缩期 prompt）

---

## 14. 统一写入契约（最关键工程纪律）

> **代码事实**：`MemoryWriteService.upsert_memory()`（`memoryhub/core/memory_write.py:98-158`）是所有写入来源的唯一收口；`DomainMemoryWriter`（`memoryhub/core/domain_writer.py`）把 `memory + lineage + evidence + outbox` 写在同一 SQL 事务里，要么全成要么全败。`SafetyWriteGate.route()`（`memoryhub/core/safety/gate.py:181-`）是 `ApprovedWrite` 能力的唯一发放点，**fail_closed 兜底**。

```mermaid
flowchart LR
    subgraph Sources["任何写入来源"]
        S1["事件摄取<br/>POST /api/memory/events"]
        S2["显式写 API<br/>POST /api/memory/memories/*"]
        S3["多源适配器<br/>POST /api/memory/sources/{tool_result,behavior,config}"]
        S4["分层流转 / 评测 / 反馈 / 遗忘"]
    end

    Sources --> Gate["SafetyWriteGate.route()<br/>ALLOW/MASK/REVIEW/REJECT<br/>+ HMAC 审计链<br/>fail_closed"]
    Gate --> Writer["DomainMemoryWriter<br/>单事务<br/>memory + lineage + evidence + outbox"]
    Writer --> RC["MemoryWriteReceipt 回执"]
    Writer --> Outbox["ProjectionOutbox<br/>status=pending"]
    Outbox --> Worker["ProjectionOutboxWorker<br/>run_once / replay"]
    Worker --> Proj["向量 / 关键词 / Lookup / 缓存"]
    Worker --> Sync["MemorySyncService.reconcile()<br/>SQLite ↔ Milvus 漂移对账"]

    style Gate fill:#ff7675,color:#fff
    style Writer fill:#fab1a0
    style Proj fill:#74b9ff,color:#fff
```

**4 处置 → sink 路由**（`SafetyWriteGate`）：

| 动作 | SQLite / Embedding / 向量 / 证据 | REVIEW 隔离区 | 持久审计 |
|---|---|---|---|
| `ALLOW` | ✓ ApprovedWrite | ✗ | ✓ |
| `MASK` | ✓ 脱敏后 ApprovedWrite（复检通过） | ✗ | ✓ |
| `REVIEW` | ✗ | ✓ AES-256-GCM 密文 | ✓ |
| `REJECT` | ✗ | ✗ | ✓ |

**Outbox 模式**：写入只到 durable outbox，由后台 `ProjectionOutboxWorker`（`memoryhub/storage/projection_outbox.py:25-99`）异步投影到 Milvus / 关键词 / 缓存；崩溃后由 `MemorySyncService.reconcile()` + `PendingIndexCompensationTask`（`storage/compensation_task.py:34-164`）补偿。`repair_at_startup()` 仅同步历史 `pending_index`，禁止全量重建。
