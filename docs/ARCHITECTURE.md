# Kylin-MemoryHub 架构可视化

---

## 1. 系统整体架构（分层视图）

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
        Hybrid["HybridRetriever<br/>混合检索入口"]
        Vector["VectorSearcher<br/>FAISS 向量检索"]
        Keyword["KeywordSearcher<br/>BM25 关键词检索"]
        Rerank["Reranker<br/>重排序"]
        Cache["SearchCache<br/>LRU 缓存"]
    end

    subgraph L6["第 6 层 · Local Runtime 本地存储"]
        SQLite["SQLite + SQLAlchemy<br/>events · preferences<br/>knowledge · conflicts"]
        FAISS["FAISS Index<br/>向量索引"]
        Evidence["EvidenceStore<br/>证据链 JSONL"]
        KylinSDK["麒麟 Embedding SDK<br/>D-Bus → 本地向量化"]
    end

    subgraph L7["第 7 层 · Evaluation & Console"]
        EvalPref["PreferenceEvaluator"]
        EvalRet["RetrievalEvaluator"]
        EvalConf["ConflictEvaluator"]
        Bench["LatencyBenchmark"]
        Vue["Vue 3 管理界面"]
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

    API --> Hybrid
    Hybrid --> Vector
    Hybrid --> Keyword
    Hybrid --> Rerank
    Hybrid --> Cache

    PrefUpdate --> SQLite
    PrefUpdate --> FAISS
    KnowExtract --> SQLite
    KnowExtract --> FAISS
    SQLite --> Evidence

    Vector --> FAISS
    Keyword --> SQLite
    KylinSDK --> FAISS

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
    Vue --> API

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

```mermaid
flowchart TD
    A["OS Agent 工具调用完成<br/>/ 用户反馈 / 手动配置"] --> B["POST /api/memory/events<br/>WriteEventRequest"]

    B --> C["DataCleaner.clean()<br/>字段校验 · 去重 · 格式化"]
    C --> D["DataNormalizer.normalize()<br/>统一转化为 MemoryEvent"]
    D --> E["QualityScorer.score()<br/>计算 quality_score [0,1]"]
    E --> F["SensitiveDetector.detect()<br/>检测敏感信息等级"]

    F -->|HIGH 敏感| G["❌ 拒绝入库<br/>返回 rejected"]
    F -->|NONE/LOW/MEDIUM| H["SensitiveDetector.mask()<br/>脱敏处理"]
    H --> I["EventRepository.save()<br/>存入 SQLite events 表"]

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

## 3. 检索数据流

```mermaid
flowchart TD
    A["OS Agent 发起检索<br/>POST /api/memory/search"] --> B["SearchRequest<br/>{query, context, top_k}"]

    B --> C["SearchCache.get()<br/>查询缓存"]
    C -->|命中| D["✅ 直接返回缓存结果"]
    C -->|未命中| E["并行启动三路检索"]

    E --> F["VectorSearcher.search()<br/>query → embed → FAISS 近邻搜索"]
    E --> G["KeywordSearcher.search()<br/>query → 分词 → BM25 打分"]
    E --> H["MetadataFilter<br/>scope + status + confidence 过滤"]

    F --> I["vector_results<br/>[{memory_id, vector_score}]"]
    G --> J["keyword_results<br/>[{memory_id, bm25_score}]"]
    H --> K["metadata_results<br/>[{memory_id, match_score}]"]

    I --> L["HybridRetriever._merge_results()<br/>score = 0.6×vector + 0.3×keyword + 0.1×metadata"]
    J --> L
    K --> L

    L --> M["HybridRetriever._filter_by_context()<br/>scope 匹配 · 置信度过滤"]
    M --> N["Reranker.rerank()<br/>相关性 + scope匹配度 + 时间新鲜度"]

    N --> O["取 Top-K 结果"]
    O --> P["SearchCache.set()<br/>写入缓存"]
    O --> Q["格式化为 SearchResponse<br/>分离 preferences 和 knowledge"]

    Q --> R["返回<br/>{preferences, knowledge, latency_ms}"]

    style D fill:#c8e6c9,stroke:#2e7d32
    style R fill:#e3f2fd,stroke:#1565c0
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

    F --> G["并行删除"]

    G --> H["EventRepository.delete_memories()<br/>删除 preferences 表记录"]
    G --> I["VectorStore.batch_delete()<br/>删除 FAISS 向量"]
    G --> J["SearchCache.invalidate()<br/>清除相关缓存"]
    G --> K["EvidenceStore.delete()<br/>删除证据链文件"]

    H --> L["统计删除数量"]
    I --> L
    J --> L
    K --> L

    L --> M["MemoryForgetter.create_audit_log()<br/>生成 ForgetRecord"]
    M --> N["存入 forget_history 表"]

    N --> O["返回 ForgetResponse<br/>{record_id, deleted_count, deleted_ids}"]

    style A fill:#fff3e0,stroke:#e65100
    style O fill:#c8e6c9,stroke:#2e7d32
```

---

## 5. 记忆生命周期流转

```mermaid
stateDiagram-v2
    [*] --> SHORT: 新事件写入<br/>quality_score < 0.6

    SHORT --> MID: 条件满足<br/>出现次数 ≥ 2<br/>quality_score ≥ 0.4
    SHORT --> [*]: 任务结束<br/>未被引用

    MID --> LONG: 条件满足<br/>出现次数 ≥ 5<br/>confidence ≥ 0.7<br/>存在天数 ≥ 3
    MID --> EXPIRED: 30 天无更新

    LONG --> EXPIRED: 365 天无更新<br/>触发审查

    EXPIRED --> [*]: 归档 archived

    note right of SHORT
        短期记忆
        - 当前任务内的临时数据
        - 不参与跨任务检索
    end note

    note right of MID
        中期记忆
        - 候选偏好 / 近期案例
        - 可被检索，但置信度较低
    end note

    note right of LONG
        长期记忆
        - 稳定偏好 / 工作流知识 / 模板
        - 主要检索来源
    end note

    note right of EXPIRED
        过期记忆
        - 不参与检索
        - 保留用于审计和回溯
    end note
```

---

## 6. 模块依赖关系

```mermaid
graph LR
    subgraph 入口层
        APP["app.py"]
        API["adapter/api.py"]
    end

    subgraph 数据结构层
        Schemas["adapter/schemas.py<br/>⭐ 所有模块共享"]
    end

    subgraph 核心逻辑层
        Ingestion["core/ingestion/"]
        Preference["core/preference/"]
        Knowledge["core/knowledge/"]
        Conflict["core/conflict/"]
        Safety["core/safety/"]
        Lifecycle["core/lifecycle/"]
    end

    subgraph 检索层
        Retrieval["retrieval/"]
    end

    subgraph 存储层
        Storage["storage/"]
        Vector["storage/vector_store"]
    end

    subgraph 抽象层
        LLM["llm/"]
        Embedding["embedding/"]
    end

    APP --> API
    APP --> Storage
    APP --> LLM
    APP --> Embedding

    API --> Schemas
    API --> Ingestion
    API --> Preference
    API --> Knowledge
    API --> Conflict
    API --> Safety
    API --> Retrieval

    Ingestion --> Schemas
    Ingestion --> Safety
    Preference --> Schemas
    Preference --> LLM
    Preference --> Conflict
    Preference --> Storage
    Preference --> Vector
    Preference --> Embedding
    Knowledge --> Schemas
    Knowledge --> LLM
    Knowledge --> Conflict
    Knowledge --> Storage
    Knowledge --> Vector
    Knowledge --> Embedding
    Conflict --> Schemas
    Conflict --> LLM
    Safety --> Schemas
    Safety --> LLM
    Lifecycle --> Storage
    Retrieval --> Schemas
    Retrieval --> Vector
    Retrieval --> Storage
    Retrieval --> Embedding

    style Schemas fill:#ffcdd2,stroke:#c62828,stroke-width:3px
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

```mermaid
graph LR
    subgraph Vue3前端
        P1["📊 Dashboard<br/>总览"]
        P2["❤️ Preferences<br/>偏好管理"]
        P3["📚 Knowledge<br/>知识管理"]
        P4["⚡ Conflicts<br/>冲突处理"]
        P5["🔍 Retrieval<br/>检索测试"]
        P6["📈 Evaluation<br/>评测报告"]
    end

    subgraph REST API
        A1["GET /preferences"]
        A2["GET /knowledge"]
        A3["GET /conflicts"]
        A4["POST /search"]
        A5["POST /evaluate"]
        A6["POST /forget"]
        A7["POST /feedback"]
    end

    P1 --> A1
    P1 --> A2
    P1 --> A3
    P2 --> A1
    P2 --> A7
    P2 --> A6
    P3 --> A2
    P4 --> A3
    P4 --> A7
    P5 --> A4
    P5 --> A6
    P6 --> A5
```
