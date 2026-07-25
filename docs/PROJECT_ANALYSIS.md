# Kylin-MemoryHub 深入浅出讲解

> **当前数据契约说明（2026-07-22）**：本文包含项目早期分析和示例。实际开发请以 [`memoryhub/adapter/schemas.py`](../memoryhub/adapter/schemas.py) 与 [`INTERFACE.md`](INTERFACE.md) 定义的 canonical `MemoryEvent` 为准；早期示例中的 `task_id`、`content`、`timestamp`、`quality_score` 不再是模块间输入输出字段。

## 一、项目是什么？一句话概括

**Kylin-MemoryHub 是一个"AI Agent 的记忆系统"**——让银河麒麟 OS 上的 AI 助手能"记住"用户的偏好、学到的工作流，并在下次对话时自动复用这些记忆。

打个比方：你第一次让 AI 帮你写周报，它什么都不记得；但你说了一句"以后周报都用 Markdown"，下次它就自动按 Markdown 格式来。这就是 MemoryHub 在背后做的事。

---

## 二、系统架构总览（7 层）

```
┌─────────────────────────────────────────────┐
│  第 1 层 · OS Agent / 用户                   │  ← 用户交互入口
├─────────────────────────────────────────────┤
│  第 2 层 · REST API (FastAPI)                │  ← 标准化接口
├─────────────────────────────────────────────┤
│  第 3 层 · 数据接入 (Ingestion)              │  ← 清洗、标准化、质量评分、安全检测
├─────────────────────────────────────────────┤
│  第 4 层 · 记忆核心 (Core)                   │  ← 偏好抽取、知识抽取、冲突处理、生命周期
├─────────────────────────────────────────────┤
│  第 5 层 · 混合检索 (Retrieval)              │  ← 向量+关键词+元数据 → 融合排序
├─────────────────────────────────────────────┤
│  第 6 层 · 本地存储 (Storage)                │  ← SQLite + FAISS + JSONL 证据链
├─────────────────────────────────────────────┤
│  第 7 层 · 评测 & 前端                       │  ← 准确率/延迟评测 + Vue3 管理界面
└─────────────────────────────────────────────┘
```

---

## 三、核心数据结构（schemas.py — 全系统的"语言"）

所有模块之间传递数据都用同一套 Pydantic 模型，这是整个系统的"通用语言"。

### 3.1 MemoryEvent — 统一事件模型（入口）

```python
class MemoryEvent(BaseModel):
    event_id: str           # 唯一 ID，如 "a1b2c3d4e5f6"
    user_id: str            # 用户标识
    session_id: str         # 会话 ID
    task_id: str            # 任务 ID
    event_type: EventType   # 5 种类型之一（见下）
    source: str             # 数据来源，如 "os_agent"
    content: dict           # 事件具体内容（结构随 event_type 变化）
    scene: str              # 场景，如 "office"
    task_type: str          # 任务类型，如 "office.weekly_report"
    quality_score: float    # 质量评分 [0, 1]
    sensitive_level: SensitiveLevel  # 敏感等级
    metadata: dict          # 额外元数据
```

**5 种事件类型**：

| EventType | 含义 | content 示例 |
|-----------|------|-------------|
| `tool_call` | 工具调用结果 | `{"tool_name": "file_search", "input": "...", "output": "..."}` |
| `user_feedback` | 用户显式反馈 | `{"text": "以后都用 Markdown", "feedback_type": "explicit"}` |
| `user_behavior` | 用户隐式行为 | `{"action": "select_template", "target": "markdown", "repeated_count": 3}` |
| `manual_config` | 手动配置 | `{"key": "default_format", "value": "markdown"}` |
| `task_trajectory` | 任务执行轨迹 | 包含完整工具调用链 |

### 3.2 PreferenceMemory — 偏好记忆

```python
class PreferenceMemory(BaseModel):
    memory_id: str            # 如 "pref_a1b2c3d4"
    preference_type: PreferenceType  # 7 种偏好类型
    content: str              # 偏好描述，如 "项目周报默认使用 Markdown"
    scope: SceneScope         # 作用域：scene + task_type + app
    confidence: float         # 置信度 [0, 1]
    status: MemoryStatus      # active / archived / deleted / pending
    level: MemoryLevel        # short / mid / long
    version: int              # 版本号
    parent_id: str            # 前一版本 ID（版本链）
    evidences: list[Evidence] # 证据链
```

**7 种偏好类型**：`OUTPUT_STYLE`(输出风格)、`TOOL_PREFERENCE`(工具选择)、`WORKFLOW_PREF`(操作流程)、`SAFETY_PREF`(安全策略)、`SCENE_PREF`(场景偏好)、`FORMAT_PREF`(格式偏好)、`LANGUAGE_PREF`(语言偏好)

### 3.3 KnowledgeMemory — 知识记忆

```python
class KnowledgeMemory(BaseModel):
    memory_id: str            # 如 "know_x1y2z3"
    knowledge_type: KnowledgeType  # WORKFLOW / CASE / TEMPLATE
    name: str                 # 名称，如 "项目周报生成流程"
    content: str              # 知识描述
    steps: list[str]          # 工作流步骤
    tools: list[str]          # 涉及的工具链
    template_body: str        # 模板正文（仅 TEMPLATE 类型）
    confidence: float         # 置信度
    success_count: int        # 成功复用次数
    total_count: int          # 总调用次数
```

### 3.4 其他关键模型

- **ConflictRecord** — 冲突记录：当新旧偏好矛盾时产生，记录 `old_content` vs `new_content`、`decision`(override/merge/coexist/pending)
- **ForgetRecord** — 遗忘审计日志：记录用户要求"忘掉"了什么
- **Evidence** — 证据链：每条记忆的来源依据（哪个事件产生了这条记忆）

### 3.5 SceneScope — 场景作用域（贯穿全系统）

```python
class SceneScope(BaseModel):
    scene: str      # 大场景，如 "office", "code", "chat"
    task_type: str  # 任务类型，如 "office.weekly_report"
    app: str        # 来源应用，如 "os_agent"
```

这个结构控制着"记忆在什么场景下生效"——你的 Markdown 偏好只在"办公-周报"场景生效，不影响"代码"场景。

---

## 四、核心功能拆解与数据流

### 功能 1：记忆写入（事件 → 记忆）

**入口**：`POST /api/memory/events`

**目标数据流（Safety 边界与强制 Gate 已实现，普通存储/抽取算法仍待实现）**：

```
原始数据
  │
  ▼
DataCleaner.clean()        ← 字段校验、去重、格式化
  │
  ▼
DataNormalizer.normalize() ← 统一转为 MemoryEvent
  │
  ▼
QualityScorer.score()      ← 计算质量评分 [0, 1]
  │
  ▼
SafetyWriteGate             ← process/复检 → 持久审计验链 → 强制动作路由
  │
  ├── REJECT → ❌ 拒绝入库
  ├── REVIEW → AES-256-GCM 隔离复核，不进入普通存储/Embedding/日志
  ├── MASK → 仅以 ApprovedWrite 向受保护 sink 传递复检后的脱敏事件
  └── ALLOW → 仅以 ApprovedWrite 向受保护 sink 传递只读安全事件
        │
        ├── event_type = user_feedback / user_behavior
        │     → PreferenceExtractor.extract()
        │       ├── 规则匹配："以后都用 X" → format_preference
        │       └── LLM 抽取：识别隐式偏好
        │     → ConfidenceCalculator.calculate()
        │     → 质量 >= 0.6？
        │       ├── 否 → 短期记忆
        │       └── 是 → ConflictDetector.check_preference()
        │             ├── 无冲突 → PreferenceUpdater.add() → SQLite + FAISS
        │             └── 有冲突 → ConflictResolver.resolve()
        │                   ├── override → 覆盖旧记忆
        │                   ├── merge → 合并新旧
        │                   ├── coexist → 按不同 scope 保留
        │                   └── pending → 等用户确认
        │
        └── event_type = task_trajectory
              → KnowledgeExtractor.extract_from_trajectory()
                → 提取工作流/案例/模板
              → ConflictDetector.check_knowledge()
              → 存入 SQLite + FAISS
```

**关键类**：
- `DataCleaner` (`core/ingestion/cleaner.py`) — 清洗器
- `DataNormalizer` (`core/ingestion/normalizer.py`) — 标准化器，内含 `FIELD_MAPPINGS` 定义了各数据源的字段映射
- `QualityScorer` (`core/ingestion/quality.py`) — 质量评分器，5 个因子加权：completeness(0.25) + source_reliability(0.25) + execution_success(0.20) + user_feedback_strength(0.20) + parse_confidence(0.10)
- `SensitiveDetector` (`core/safety/detector.py`) — 结构化安全处理接口；等级表示风险，规则和策略决定动作

### 功能 2：偏好抽取（核心智能）

**入口**：`PreferenceExtractor.extract(event)`

**两阶段抽取**：

```
阶段 1：规则抽取（快速、确定性）
  "以后都用 X"        → format_preference
  "默认使用 X"        → tool_preference / format_preference
  "每次都先 Y 再 Z"   → workflow_preference
  "不要记住 X"        → safety_preference

阶段 2：LLM 抽取（慢、灵活）
  → 把事件内容发给 LLM
  → Prompt: "请从以下用户操作中识别隐式偏好..."
  → LLM 返回结构化偏好

合并去重 → 绑定证据链 → 计算置信度
```

**置信度计算** (`ConfidenceCalculator`)：

```
confidence = f(证据数量) × f(来源类型) × f(时间衰减) × f(一致性)

来源类型权重：
  explicit_feedback = 1.0    ← 用户亲口说的，最可信
  manual_config     = 0.95   ← 手动配置
  repeated_behavior = 0.8    ← 重复行为暗示
  tool_result       = 0.6    ← 工具调用结果
  single_behavior   = 0.4    ← 单次行为，最不可信
```

### 功能 3：记忆检索（混合搜索）

**入口**：`POST /api/memory/search`

**三路并行检索**：

```
查询 "项目周报"
    │
    ├── 向量路径 (weight=0.6)
    │     embed(query) → FAISS 近邻搜索 → vector_results
    │
    ├── 关键词路径 (weight=0.3)
    │     jieba 分词 → BM25 打分 → keyword_results
    │
    └── 元数据路径 (weight=0.1)
          scope + status + confidence 过滤 → metadata_results

融合公式：
  final_score = 0.6 × vector_score + 0.3 × keyword_score + 0.1 × metadata_score

  ↓
Reranker 重排序（考虑相关性 + scope 匹配度 + 时间新鲜度）
  ↓
返回 Top-K 结果
```

**关键类**：
- `HybridRetriever` (`retrieval/hybrid.py`) — 混合检索入口
- `VectorSearcher` (`retrieval/vector_search.py`) — FAISS 向量检索
- `KeywordSearcher` (`retrieval/keyword_search.py`) — BM25 关键词检索
- `Reranker` (`retrieval/reranker.py`) — 重排序器
- `SearchCache` (`retrieval/cache.py`) — LRU 缓存，TTL 300 秒

### 功能 4：精准遗忘

**入口**：`POST /api/memory/forget`

**数据流**：

```
用户说："忘掉我关于周报格式的偏好"
    │
    ▼
MemoryForgetter.parse_intent()  ← LLM 解析意图
    → {memory_type: "preference", target_topic: "周报格式", scope: "office.weekly_report"}
    │
    ▼
locate_memories()  ← 在 SQLite 中定位目标记忆
    → ["pref_001", "pref_003"]
    │
    ▼
并行删除：
    ├── SQLite preferences 表
    ├── FAISS 向量索引
    ├── 检索缓存
    └── 证据链 JSONL 文件
    │
    ▼
生成审计日志 → forget_history 表
```

### 功能 5：冲突处理

**检测条件** (`ConflictDetector.check_preference`)：
1. scope 重叠（同一场景/任务类型）
2. preference_type 相同
3. 内容语义矛盾（可 LLM 辅助判断）

**解决策略** (`ConflictResolver.auto_resolve`)：

| 条件 | 决策 |
|------|------|
| 新记忆来源 = explicit_feedback | **OVERRIDE**（覆盖旧的） |
| 新旧内容互补 | **MERGE**（合并） |
| scope 不同 | **COEXIST**（并存） |
| 无法自动判断 | **PENDING**（等用户确认） |

### 功能 6：记忆生命周期

**三级记忆流转**：

```
新事件写入
    │
    ▼
  SHORT（短期）── 低质量/单次事件，任务内临时数据
    │
    ├── 出现次数 ≥ 2 且 quality ≥ 0.4
    ▼
  MID（中期）── 候选偏好/近期案例，可被检索
    │
    ├── 出现次数 ≥ 5 且 confidence ≥ 0.7 且存在 ≥ 3 天
    ▼
  LONG（长期）── 稳定偏好/工作流知识，主要检索来源
    │
    ├── 365 天无更新 → 审查
    ▼
  EXPIRED → 归档，不参与检索
```

**关键阈值**（`LifecycleManager.PROMOTE_THRESHOLDS`）：

```python
"short_to_mid": {"min_occurrences": 2, "min_quality_score": 0.4}
"mid_to_long":  {"min_occurrences": 5, "min_confidence": 0.7, "min_days": 3}
```

---

## 五、存储层设计

### 5.1 SQLite（结构化数据）

5 张表，对应 5 个 ORM 模型：

| 表名 | ORM 模型 | 用途 |
|------|----------|------|
| `events` | `EventRow` | 原始事件 |
| `preferences` | `PreferenceRow` | 偏好记忆 |
| `knowledge` | `KnowledgeRow` | 知识记忆 |
| `conflicts` | `ConflictRow` | 冲突记录 |
| `forget_history` | `ForgetRow` | 遗忘审计日志 |

每张表对应一个 Repository 类（`EventRepository`, `PreferenceRepository` 等），封装 CRUD 操作。

### 5.2 FAISS（向量索引）

`VectorStore` 管理 FAISS 索引，维护双向映射：
- `id_map: dict[int, str]` — FAISS 内部 ID → memory_id
- `reverse_map: dict[str, int]` — memory_id → FAISS 内部 ID

支持三种索引类型：`flat`（暴力搜索，<10k 数据）、`ivf`（倒排索引）、`hnsw`（HNSW 图索引，大数据量）

### 5.3 JSONL 证据链

`EvidenceStore` 以 JSONL 格式存储证据链，每个 memory_id 对应一个文件，支持追加写入。

---

## 六、LLM & Embedding 抽象层

### 6.1 LLM 抽象

```
BaseLLMClient (抽象基类)
    ├── generate(prompt, system_prompt) → LLMResponse
    ├── generate_json(prompt, schema) → dict
    └── is_available() → bool
        │
        ├── OpenAIClient  — OpenAI 兼容 API
        └── OllamaClient  — Ollama 本地推理
```

### 6.2 Embedding 抽象

```
BaseEmbeddingClient (抽象基类)
    ├── embed(text) → list[float]
    ├── batch_embed(texts) → list[list[float]]
    ├── get_dimension() → int
    └── is_available() → bool
        │
        ├── KylinEmbeddingClient  — 麒麟 SDK（ctypes → .so → D-Bus）
        └── MockClient            — 开发用 Mock
```

---

## 七、具体运行示例

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
OS Agent → POST /events {tool_call × 4}
MemoryHub → 存入 events 表（4 条事件）
```

### 示例 2：用户表达偏好 → 记忆形成

```
用户: "以后周报都用 Markdown，分三部分"
  │
  ▼
OS Agent → POST /events {user_feedback, text="以后周报都用 Markdown"}
  │
  ▼
DataCleaner.clean() → DataNormalizer.normalize() → MemoryEvent
QualityScorer.score() → 0.85 (高质量：显式反馈 + 完整内容)
SensitiveDetector.process() → ALLOW (无敏感信息)
  │
  ▼
PreferenceExtractor.extract()
  → 规则匹配："以后都用 X" → format_preference
  → content = "周报使用 Markdown，分三部分"
  → scope = {scene: "office", task_type: "office.weekly_report"}
  │
  ▼
ConfidenceCalculator.calculate()
  → 来源 = explicit_feedback (权重 1.0)
  → evidence_count = 1
  → confidence = 0.92
  │
  ▼
ConflictDetector.check_preference() → 无冲突（首次）
PreferenceUpdater.add() → 写入 preferences 表
Embedding.embed() → 向量化 → 存入 FAISS
EvidenceStore.save() → 保存证据链
```

### 示例 3：复用记忆

```
用户: "按上次的方式生成这周周报"
  │
  ▼
OS Agent → POST /search {query: "项目周报", context: {scene: "office"}}
  │
  ▼
HybridRetriever.search():
  ├── VectorSearcher: embed("项目周报") → FAISS 搜索 → [pref_001: 0.92]
  ├── KeywordSearcher: "项目"+"周报" → BM25 → [pref_001: 0.85]
  └── MetadataFilter: scene=office → [pref_001: 1.0]
  │
  ▼
融合: final = 0.6×0.92 + 0.3×0.85 + 0.1×1.0 = 0.907
Reranker → 确认排序
  │
  ▼
返回: {preferences: ["Markdown 三段式周报"], knowledge: ["周报生成流程"]}
  │
  ▼
OS Agent 自动按偏好执行 → 输出 Markdown 三段式周报 ✅
```

### 示例 4：偏好冲突 → 自动覆盖

```
用户: "以后周报改成 Word"
  │
  ▼
POST /events {user_feedback, text="以后周报改成 Word"}
  │
  ▼
PreferenceExtractor → format_preference = "周报使用 Word"
  │
  ▼
ConflictDetector.check_preference():
  已有: pref_001 {content: "周报使用 Markdown", scope: office.weekly_report}
  新的: pref_002 {content: "周报使用 Word", scope: office.weekly_report}
  → scope 重叠 + type 相同 + 内容矛盾 → 冲突！
  │
  ▼
ConflictResolver.resolve():
  新记忆来源 = explicit_feedback → 决策: OVERRIDE
  │
  ▼
pref_001.status → archived
pref_002.version = 2, parent_id = "pref_001"
写入 conflicts 表记录
```

### 示例 5：精准遗忘

```
用户: "忘掉我关于周报格式的偏好"
  │
  ▼
POST /forget {instruction: "忘掉我关于周报格式的偏好"}
  │
  ▼
MemoryForgetter.parse_intent() → LLM 解析:
  {memory_type: "preference", target_topic: "周报格式", scope: "office.*"}
  │
  ▼
locate_memories() → 查询 SQLite → ["pref_002"]
  │
  ▼
并行删除:
  ├── preferences 表 DELETE
  ├── FAISS 向量 DELETE
  ├── SearchCache.invalidate("pref_002")
  └── evidence/pref_002.jsonl DELETE
  │
  ▼
生成审计日志 → forget_history 表
返回: {deleted_count: 1, deleted_ids: ["pref_002"]}
```

### 示例 6：知识记忆形成（工作流挖掘）

```
用户第 3 次执行"生成周报"任务，每次工具调用链一致：
  日历查询 → 文件收集 → 数据整理 → 报告生成
  │
  ▼
KnowledgeExtractor.extract_from_trajectory(事件序列)
  → 识别任务目标: "生成项目周报"
  → 提取工具链: ["calendar_query", "file_search", "data整理", "report_gen"]
  → 提取步骤: ["1.查日历", "2.收集文件", "3.整理数据", "4.生成报告"]
  │
  ▼
WorkflowMiner.mine(3 组同类轨迹)
  → 对齐步骤 → 提取公共模式 → 稳定度 = 1.0 (3/3 次一致)
  │
  ▼
生成 KnowledgeMemory:
  knowledge_type = WORKFLOW
  name = "项目周报生成流程"
  steps = ["查日历", "收集文件", "整理数据", "生成报告"]
  tools = ["calendar_query", "file_search", "data整理", "report_gen"]
  confidence = 0.95
  │
  ▼
存入 SQLite + FAISS → 后续检索可复用
```

---

## 八、配置系统（config.py）

```
AppConfig
├── StorageConfig      # db_path, vector_index_path, evidence_path
├── RetrievalConfig    # vector_weight=0.6, keyword_weight=0.3, metadata_weight=0.1
├── LLMConfig          # provider="openai"|"ollama", model="qwen2:1.5b"
├── EmbeddingConfig    # provider="kylin"|"mock", dimension=1024
└── SafetyConfig       # 版本化规则集选择/兼容 SensitiveRule + SafetyPolicy
```

---

## 九、设计亮点总结

1. **事件驱动**：所有数据以 `MemoryEvent` 为统一入口，不同来源的数据先标准化再处理
2. **规则+LLM 双引擎**：偏好抽取先用快速规则匹配，匹配不上再调 LLM，兼顾效率和覆盖率
3. **三级记忆生命周期**：短期→中期→长期的自然淘汰机制，避免记忆无限膨胀
4. **混合检索**：向量(语义) + 关键词(精确) + 元数据(过滤) 三路融合，兼顾召回率和精确度
5. **冲突自动处理**：显式反馈自动覆盖，互补内容自动合并，无法判断的才问用户
6. **精准遗忘**：自然语言驱动，LLM 解析意图后定位并删除，同时生成审计日志
7. **证据链可追溯**：每条记忆都绑定产生它的原始事件，支持溯源和审计
8. **完全本地化**：SQLite + FAISS + 本地 LLM/Embedding，数据不出设备

---

## 十、原始数据到底是什么

原始数据的来源只有一个：**OS Agent（银河麒麟的操作系统智能体）**。它在帮用户做事的过程中，把每一步操作都记录下来，以 JSON 格式 POST 到 MemoryHub 的 `/api/memory/events` 接口。

### 10.1 五种原始数据的具体样子

#### 1. `tool_call` — 工具调用结果

OS Agent 每调用一个工具（搜索文件、读日历、写文档等），就产生一条：

```json
{
  "event_type": "tool_call",
  "source": "os_agent",
  "session_id": "sess_001",
  "task_id": "task_weekly_report_001",
  "content": {
    "tool_name": "file_search",
    "input": "查找项目周报相关文件",
    "output": "找到 3 个项目文档: 项目进展.md, 风险清单.md, 里程碑.md",
    "status": "success"
  },
  "scene": "office",
  "task_type": "office.weekly_report"
}
```

#### 2. `user_feedback` — 用户显式反馈

用户直接说的话，通常是偏好表达或纠正：

```json
{
  "event_type": "user_feedback",
  "content": {
    "text": "以后周报都用 Markdown，分三部分",
    "feedback_type": "explicit"
  },
  "scene": "office",
  "task_type": "office.weekly_report"
}
```

#### 3. `user_behavior` — 用户隐式行为

用户没说话，但行为暗示了偏好（比如反复选同一个模板）：

```json
{
  "event_type": "user_behavior",
  "content": {
    "action": "select_template",
    "target": "markdown_three_section",
    "repeated_count": 3
  },
  "scene": "office",
  "task_type": "office.weekly_report"
}
```

#### 4. `manual_config` — 手动配置

用户在设置界面手动设的选项：

```json
{
  "event_type": "manual_config",
  "content": {
    "key": "default_report_format",
    "value": "markdown"
  },
  "scene": "office"
}
```

#### 5. `task_trajectory` — 任务执行轨迹

一次完整任务的所有步骤和工具调用链，是最"大"的一条数据：

```json
{
  "event_type": "task_trajectory",
  "content": {
    "task_name": "生成项目周报",
    "steps": [
      "1. 查询本周日历事件",
      "2. 搜索项目相关文件",
      "3. 读取文件内容提取进展",
      "4. 整理风险和里程碑",
      "5. 生成 Markdown 周报"
    ],
    "tools": ["calendar_query", "file_search", "doc_reader", "report_writer"],
    "result": "成功生成周报"
  },
  "scene": "office",
  "task_type": "office.weekly_report"
}
```

### 10.2 数据从哪来

```
用户对 OS Agent 说话
       │
       ▼
OS Agent 执行任务
  ├── 调用工具 → 产生 tool_call 事件
  ├── 用户说了句偏好 → 产生 user_feedback 事件
  ├── 用户反复选同一个选项 → 产生 user_behavior 事件
  ├── 用户改了设置 → 产生 manual_config 事件
  └── 任务完成 → 汇总产生 task_trajectory 事件
       │
       ▼
OS Agent 批量 POST 到 MemoryHub
  POST /api/memory/events
  { "events": [event1, event2, event3, ...] }
```

### 10.3 关键字段说明

| 字段 | 含义 | 举例 |
|------|------|------|
| `session_id` | 一次对话的 ID | `sess_001` |
| `task_id` | 一次任务的 ID，同一任务的多个事件共享 | `task_weekly_report_001` |
| `scene` | 粗粒度场景 | `office` / `code` / `chat` |
| `task_type` | 细粒度任务类型，用 `.` 分层 | `office.weekly_report` |
| `source` | 数据来源 | `os_agent` / `manual` / `import` |

`scene` + `task_type` 构成了 `SceneScope`，决定了这条数据产生的记忆在什么场景下生效。

---

## 十一、Agent 如何调用 MemoryHub

MemoryHub 是一个**独立的 HTTP 服务**（FastAPI），OS Agent 通过 REST API 调用它。整个调用模式就三步：**做之前查记忆、做完后写记忆、需要时忘记忆**。

### 11.1 三种核心调用模式

#### 模式 1：做事之前 — 查记忆

Agent 收到用户任务后，**先问 MemoryHub "关于这件事我记得什么"**，然后根据记忆决定怎么做。

```
用户: "按上次的方式生成周报"
  │
  ▼
OS Agent 收到任务
  │
  ▼
POST http://localhost:8000/api/memory/search
{
  "query": "项目周报",
  "context": {"scene": "office", "task_type": "office.weekly_report"},
  "top_k": 5
}
  │
  ▼
MemoryHub 返回 SearchResponse
{
  "preferences": [
    {"memory_id": "pref_001", "content": "周报使用 Markdown，分三部分", "confidence": 0.92}
  ],
  "knowledge": [
    {"memory_id": "know_001", "name": "周报生成流程", "steps": ["查日历", "收集文件", "整理数据", "生成报告"]}
  ],
  "latency_ms": 45.2
}
  │
  ▼
OS Agent 读取记忆 → 自动按 Markdown 三段式 + 流程步骤执行
```

还有一个 `/context` 接口，返回的是**可以直接拼进 prompt 的文本**，Agent 可以直接注入到 LLM 的上下文里：

```
POST /api/memory/context
  → 返回: "用户偏好：周报使用 Markdown，分三部分。
           参考流程：1.查日历 2.收集文件 3.整理数据 4.生成报告"
```

#### 模式 2：做完之后 — 写记忆

Agent 执行完任务后，把这次做了什么写回 MemoryHub，让系统学习。

```
OS Agent 完成任务
  │
  ▼
POST http://localhost:8000/api/memory/events
{
  "events": [
    {
      "event_type": "tool_call",
      "task_id": "task_001",
      "content": {"tool_name": "calendar_query", "input": "本周日历", "output": "3个会议", "status": "success"},
      "scene": "office", "task_type": "office.weekly_report"
    },
    {
      "event_type": "tool_call",
      "task_id": "task_001",
      "content": {"tool_name": "file_search", "input": "项目文件", "output": "5个文档", "status": "success"},
      "scene": "office", "task_type": "office.weekly_report"
    },
    {
      "event_type": "user_feedback",
      "content": {"text": "以后都用 Markdown", "feedback_type": "explicit"},
      "scene": "office", "task_type": "office.weekly_report"
    }
  ]
}
  │
  ▼
MemoryHub 接收 → 清洗 → 标准化 → 质量评分 → 安全检测
  → 偏好抽取 → 冲突检测 → 存储
  │
  ▼
返回: {"accepted": 3, "rejected": 0, "event_ids": ["ev_abc", "ev_def", "ev_ghi"]}
```

#### 模式 3：用户说"忘掉" — 精准遗忘

```
用户: "忘掉我关于周报格式的偏好"
  │
  ▼
OS Agent → POST http://localhost:8000/api/memory/forget
{
  "instruction": "忘掉我关于周报格式的偏好"
}
  │
  ▼
MemoryHub 解析意图 → 定位记忆 → 删除 → 审计
  │
  ▼
返回: {"deleted_count": 1, "deleted_ids": ["pref_001"]}
```

#### 补充模式：用户反馈

用户对某条已有记忆表达意见（确认、拒绝、修改）：

```
POST /api/memory/feedback
{
  "memory_id": "pref_001",
  "feedback_text": "确认，就是这个格式",
  "action": "confirm"   // "update" | "confirm" | "reject"
}
```

### 11.2 完整的 Agent 调用时序

```
┌──────────┐                    ┌──────────────┐                    ┌──────────────┐
│  用户     │                    │  OS Agent    │                    │  MemoryHub   │
└────┬─────┘                    └──────┬───────┘                    └──────┬───────┘
     │                                 │                                   │
     │  "帮我按上次方式生成周报"         │                                   │
     │────────────────────────────────→│                                   │
     │                                 │                                   │
     │                                 │  ① POST /search                   │
     │                                 │  {query:"周报", context:office}    │
     │                                 │──────────────────────────────────→│
     │                                 │                                   │
     │                                 │  SearchResponse                   │
     │                                 │  {preferences:[Markdown偏好],      │
     │                                 │   knowledge:[周报流程]}            │
     │                                 │←──────────────────────────────────│
     │                                 │                                   │
     │                                 │  ② 按记忆执行任务                  │
     │                                 │  (查日历→收集文件→整理→生成Markdown)│
     │                                 │                                   │
     │  Markdown 周报                  │                                   │
     │←────────────────────────────────│                                   │
     │                                 │                                   │
     │  "以后周报都用Word"              │                                   │
     │────────────────────────────────→│                                   │
     │                                 │                                   │
     │                                 │  ③ POST /events                   │
     │                                 │  {events:[user_feedback事件]}      │
     │                                 │──────────────────────────────────→│
     │                                 │                                   │
     │                                 │  {accepted:1}                     │
     │                                 │←──────────────────────────────────│
     │                                 │                                   │
     │                                 │  (MemoryHub 内部自动处理：          │
     │                                 │   偏好抽取→冲突检测→覆盖旧记忆)     │
     │                                 │                                   │
```

### 11.3 Agent 调用的 4 个核心接口

| 接口 | 方法 | Agent 什么时候调 | 作用 |
|------|------|----------------|------|
| `/api/memory/search` | POST | 做事之前 | 检索相关记忆 |
| `/api/memory/context` | POST | 做事之前 | 获取可注入 prompt 的记忆文本 |
| `/api/memory/events` | POST | 做完之后 | 写入事件，触发记忆学习 |
| `/api/memory/forget` | POST | 用户要求遗忘时 | 精准删除特定记忆 |

其余接口（`/preferences`, `/knowledge`, `/conflicts`, `/feedback`）是**管理接口**，供前端 Vue3 管理界面或用户手动操作使用，不是 Agent 日常调用的。

`AgentSimulator`（`adapter/simulator.py`）就是一个**模拟真实 Agent 行为的测试工具**，它内部调用 `memory_adapter`（即上面 4 个接口的客户端），模拟完整的"查记忆→做事→写记忆"流程。

---

## 十二、源码推荐阅读顺序

### 第一阶段：基础层（先懂"语言"和"骨架"）

```
1. memoryhub/adapter/schemas.py      ← 最重要，全系统的数据结构定义
2. memoryhub/config.py               ← 配置，了解系统有哪些可调参数
3. memoryhub/app.py                  ← 入口，了解 FastAPI 如何组装
4. memoryhub/adapter/api.py          ← REST 路由，了解系统对外暴露哪些接口
```

**为什么先读这些**：`schemas.py` 是所有模块的"通用语言"，不理解它就读不懂任何核心逻辑。`api.py` 定义了全部接口，是理解数据流的"地图"。

---

### 第二阶段：数据接入层（理解数据怎么"进来"）

```
5. memoryhub/core/ingestion/cleaner.py      ← 清洗
6. memoryhub/core/ingestion/normalizer.py   ← 标准化
7. memoryhub/core/ingestion/quality.py      ← 质量评分
8. memoryhub/core/safety/detector.py        ← 敏感信息检测
```

**阅读线索**：一条原始数据如何一步步变成标准的 `MemoryEvent`。

---

### 第三阶段：记忆核心（系统的"大脑"）

```
 9. memoryhub/core/preference/extractor.py    ← 偏好抽取（规则+LLM）
10. memoryhub/core/preference/confidence.py   ← 置信度计算
11. memoryhub/core/preference/updater.py      ← 偏好更新与版本管理
12. memoryhub/core/conflict/detector.py       ← 冲突检测
13. memoryhub/core/conflict/resolver.py       ← 冲突解决
14. memoryhub/core/knowledge/extractor.py     ← 知识抽取
15. memoryhub/core/knowledge/workflow_miner.py ← 工作流挖掘
16. memoryhub/core/knowledge/template_builder.py ← 模板构建
17. memoryhub/core/lifecycle/manager.py       ← 生命周期管理
18. memoryhub/core/safety/forget.py           ← 精准遗忘
```

**阅读线索**：偏好抽取是核心中的核心，读懂它再看知识抽取会很顺畅。冲突处理是偏好抽取的"下游"，生命周期是"长期维护"。

---

### 第四阶段：检索层（理解数据怎么"出去"）

```
19. memoryhub/retrieval/hybrid.py         ← 混合检索入口
20. memoryhub/retrieval/vector_search.py  ← 向量检索
21. memoryhub/retrieval/keyword_search.py ← 关键词检索
22. memoryhub/retrieval/reranker.py       ← 重排序
23. memoryhub/retrieval/cache.py          ← 缓存
```

**阅读线索**：从 `hybrid.py` 入手，它串联了其他四个模块。

---

### 第五阶段：存储层（理解数据怎么"落地"）

```
24. memoryhub/storage/models.py         ← ORM 模型（5 张表）
25. memoryhub/storage/database.py       ← 数据库引擎 + 各 Repository
26. memoryhub/storage/vector_store.py   ← FAISS 索引管理
27. memoryhub/storage/evidence_store.py ← 证据链 JSONL 存储
```

---

### 第六阶段：抽象层（可插拔的后端实现）

```
28. memoryhub/llm/base.py              ← LLM 抽象接口
29. memoryhub/llm/openai_client.py     ← OpenAI 实现
30. memoryhub/llm/ollama_client.py     ← Ollama 实现
31. memoryhub/embedding/base.py        ← Embedding 抽象接口
32. memoryhub/embedding/kylin_client.py ← 麒麟 SDK 实现
33. memoryhub/embedding/mock_client.py  ← Mock 实现
```

---

### 第七阶段：辅助模块

```
34. memoryhub/adapter/simulator.py      ← Agent 模拟器（演示用）
35. evaluation/metrics/preference_eval.py ← 偏好评测
36. evaluation/metrics/retrieval_eval.py  ← 检索评测
37. evaluation/metrics/conflict_eval.py   ← 冲突评测
38. evaluation/metrics/latency_benchmark.py ← 性能基准
```

---

### 速查：按问题找文件

| 想了解什么 | 直接读 |
|-----------|--------|
| 数据结构长什么样 | `schemas.py` |
| 一个请求从进来到出去的全流程 | `api.py` → `cleaner.py` → `normalizer.py` → `extractor.py` → `hybrid.py` |
| 偏好怎么从用户话里提取出来 | `preference/extractor.py` |
| 检索怎么融合三路结果 | `retrieval/hybrid.py` |
| 冲突怎么自动解决 | `conflict/resolver.py` |
| 记忆怎么从短期变成长期 | `lifecycle/manager.py` |
| 怎么"忘掉"一条记忆 | `safety/forget.py` |
| 数据怎么存到磁盘 | `storage/database.py` + `storage/vector_store.py` |
