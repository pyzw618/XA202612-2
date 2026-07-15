# Kylin-MemoryHub 数据结构与接口规范

> **本文档是多人协作的核心参考，所有模块间的数据交互必须遵循此规范。**
> **修改任何数据结构或接口签名，必须同步更新本文档。**

---

## 目录

1. [核心数据结构](#1-核心数据结构)
2. [枚举类型定义](#2-枚举类型定义)
3. [模块接口规范](#3-模块接口规范)
4. [数据流转图](#4-数据流转图)
5. [REST API 规范](#5-rest-api-规范)
6. [存储层映射](#6-存储层映射)

---

## 1. 核心数据结构

### 1.1 SceneScope — 场景作用域

记忆在什么场景下生效的标识。

```python
class SceneScope(BaseModel):
    scene: str = ""         # 大场景: "office" | "code" | "chat" | "daily"
    task_type: str = ""     # 任务类型: "office.weekly_report" | "code.debug" | ...
    app: str = ""           # 来源应用: "os_agent" | "manual"
```

**说明**: `scene` 是粗粒度分类，`task_type` 是细粒度分类（用 `.` 分隔层级），`app` 标识来源。检索时先匹配 `scene`，再匹配 `task_type`。

---

### 1.2 Evidence — 证据链

记忆的来源依据，每条偏好/知识都绑定一组证据。

```python
class Evidence(BaseModel):
    evidence_id: str        # 唯一 ID，格式: 8 位 UUID 片段
    event_id: str           # 关联的 MemoryEvent.event_id
    content: str            # 证据内容摘要（简洁描述）
    source_type: EventType  # 来源事件类型
    timestamp: datetime     # 证据产生时间
    weight: float = 1.0     # 该证据的权重 [0, 1]
```

---

### 1.3 MemoryEvent — 统一事件模型

**所有多源数据进入系统后的标准格式。** 这是整个系统的输入层核心数据结构。

```python
class MemoryEvent(BaseModel):
    event_id: str           # 唯一 ID，格式: "ev_" + 12 位 UUID 片段
    user_id: str            # 用户 ID，默认 "default"
    session_id: str         # 会话 ID
    task_id: str            # 任务 ID（同一任务的事件共享 task_id）
    event_type: EventType   # 事件类型（见枚举）
    source: str             # 数据来源标识: "os_agent" | "manual" | "import"

    # --- 事件内容 ---
    content: dict           # 事件内容（结构随 event_type 变化，见下方说明）

    # --- 上下文 ---
    scene: str              # 场景
    task_type: str          # 任务类型
    timestamp: datetime     # 事件时间戳

    # --- 质量与安全 ---
    quality_score: float    # 数据质量评分 [0, 1]，由 QualityScorer 计算
    sensitive_level: SensitiveLevel  # 敏感等级
    metadata: dict          # 扩展元数据
```

#### content 字段结构（按 event_type 区分）

| event_type | content 结构 |
|---|---|
| `tool_call` | `{"tool_name": str, "input": str, "output": str, "status": "success"\|"error"}` |
| `user_feedback` | `{"text": str, "feedback_type": "explicit"\|"implicit"}` |
| `user_behavior` | `{"action": str, "target": str, "repeated_count": int}` |
| `manual_config` | `{"key": str, "value": str}` |
| `task_trajectory` | `{"task_name": str, "steps": list[str], "tools": list[str], "result": str}` |

---

### 1.4 PreferenceMemory — 偏好记忆

```python
class PreferenceMemory(BaseModel):
    memory_id: str          # 唯一 ID，格式: "pref_" + 8 位 UUID 片段
    user_id: str            # 用户 ID
    memory_type: str        # 固定值 "preference"
    preference_type: PreferenceType  # 偏好类型（见枚举）

    # --- 偏好内容 ---
    content: str            # 偏好描述文本，如 "项目周报默认使用 Markdown"
    scope: SceneScope       # 生效场景

    # --- 置信度与状态 ---
    confidence: float       # 置信度 [0, 1]
    status: MemoryStatus    # 状态: active / archived / deleted / pending
    level: MemoryLevel      # 记忆层级: short / mid / long

    # --- 版本管理 ---
    version: int            # 版本号，从 1 开始递增
    parent_id: str          # 前一版本的 memory_id（版本链指针）

    # --- 证据链 ---
    evidences: list[Evidence]  # 支持该偏好的证据列表

    # --- 时间戳 ---
    created_at: datetime
    updated_at: datetime
```

**版本链规则**: 每次更新偏好时，旧版本 `status → archived`，新版本 `version = old.version + 1`，`parent_id = old.memory_id`。

---

### 1.5 KnowledgeMemory — 知识记忆

```python
class KnowledgeMemory(BaseModel):
    memory_id: str          # 唯一 ID，格式: "know_" + 8 位 UUID 片段
    user_id: str
    memory_type: str        # 固定值 "knowledge"
    knowledge_type: KnowledgeType  # 知识类型（见枚举）

    # --- 知识内容 ---
    name: str               # 知识名称，如 "项目周报生成流程"
    content: str            # 知识描述文本
    steps: list[str]        # 工作流步骤（WORKFLOW 类型必填）
    tools: list[str]        # 工具链（WORKFLOW 类型必填）
    template_body: str      # 模板正文（TEMPLATE 类型必填）
    scope: SceneScope       # 生效场景

    # --- 质量指标 ---
    confidence: float       # 置信度 [0, 1]
    success_count: int      # 成功复用次数
    total_count: int        # 总调用次数
    status: MemoryStatus
    level: MemoryLevel

    # --- 版本管理 ---
    version: int
    parent_id: str

    # --- 证据链 ---
    evidences: list[Evidence]

    # --- 时间戳 ---
    created_at: datetime
    updated_at: datetime
```

#### knowledge_type 与必填字段对照

| knowledge_type | 必填字段 | 说明 |
|---|---|---|
| `workflow` | `name`, `steps`, `tools` | 工作流知识 |
| `case` | `name`, `content` | 历史案例 |
| `template` | `name`, `template_body` | 可复用模板 |

---

### 1.6 ConflictRecord — 冲突记录

```python
class ConflictRecord(BaseModel):
    conflict_id: str        # 唯一 ID，格式: "conf_" + 8 位 UUID 片段
    old_memory_id: str      # 旧记忆 ID
    new_memory_id: str      # 新记忆 ID
    memory_type: str        # "preference" | "knowledge"

    # --- 冲突内容 ---
    old_content: str        # 旧记忆内容摘要
    new_content: str        # 新记忆内容摘要
    conflict_field: str     # 冲突的具体字段

    # --- 处理结果 ---
    decision: ConflictDecision  # 处理决策（见枚举）
    reason: str             # 处理原因说明
    result_memory_id: str   # 处理后产生的新记忆 ID（如有）

    created_at: datetime
    resolved_at: datetime | None
```

---

### 1.7 ForgetRecord — 遗忘记录

```python
class ForgetRecord(BaseModel):
    record_id: str          # 唯一 ID，格式: "forg_" + 8 位 UUID 片段
    user_id: str
    instruction: str        # 用户原始遗忘指令
    target_memory_ids: list[str]   # 被删除的记忆 ID 列表
    target_scope: SceneScope       # 遗忘的场景范围
    deleted_count: int      # 实际删除数量
    created_at: datetime
```

---

## 2. 枚举类型定义

### EventType — 事件类型

| 值 | 含义 | 典型 content |
|---|---|---|
| `tool_call` | 工具调用结果 | `{tool_name, input, output, status}` |
| `user_feedback` | 用户显式反馈 | `{text, feedback_type}` |
| `user_behavior` | 用户隐式行为 | `{action, target, repeated_count}` |
| `manual_config` | 手动配置 | `{key, value}` |
| `task_trajectory` | 任务执行轨迹 | `{task_name, steps, tools, result}` |

### PreferenceType — 偏好类型

| 值 | 含义 | 示例 |
|---|---|---|
| `output_style` | 输出风格偏好 | "喜欢 Markdown 输出" |
| `tool_preference` | 工具选择偏好 | "文件任务优先用本地检索" |
| `workflow_preference` | 操作流程偏好 | "生成报告前先列提纲" |
| `safety_preference` | 安全策略偏好 | "不保存 API Key" |
| `scene_preference` | 场景偏好 | "写论文要正式" |
| `format_preference` | 格式偏好 | "周报三段式结构" |
| `language_preference` | 语言偏好 | "默认中文回答" |

### KnowledgeType — 知识类型

| 值 | 含义 |
|---|---|
| `workflow` | 工作流知识 |
| `case` | 历史案例 |
| `template` | 可复用模板 |

### MemoryLevel — 记忆层级

| 值 | 含义 | 生命周期 |
|---|---|---|
| `short` | 短期记忆 | 当前任务内 |
| `mid` | 中期记忆 | 几天到几周 |
| `long` | 长期记忆 | 持久保存 |

### ConflictDecision — 冲突处理决策

| 值 | 含义 |
|---|---|
| `override` | 覆盖旧记忆 |
| `merge` | 合并新旧 |
| `coexist` | 按场景并存 |
| `pending` | 待用户确认 |

### MemoryStatus — 记忆状态

| 值 | 含义 |
|---|---|
| `active` | 活跃（正常检索和使用） |
| `archived` | 已归档（不参与检索，但保留历史） |
| `deleted` | 已删除（逻辑删除） |
| `pending` | 待确认 |

### SensitiveLevel — 敏感等级

| 值 | 含义 |
|---|---|
| `none` | 无敏感信息 |
| `low` | 低敏感（如 IP 地址） |
| `medium` | 中敏感（如手机号、邮箱） |
| `high` | 高敏感（如 API Key、密码、身份证） |

---

## 3. 模块接口规范

### 3.1 Ingestion 模块 — 多源数据接入

```
模块: memoryhub.core.ingestion
负责: 数据清洗、标准化、质量评分
```

#### DataCleaner

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `clean` | `(raw_data: dict) -> dict` | 原始数据字典 | 清洗后数据字典 | 字段校验、去重、格式规范化 |
| `deduplicate` | `(events: list[MemoryEvent]) -> list[MemoryEvent]` | 事件列表 | 去重后列表 | 基于 event_id 和内容 hash 去重 |
| `validate_event` | `(event: MemoryEvent) -> tuple[bool, str]` | 单条事件 | `(合法, 错误信息)` | 校验事件合法性 |

#### DataNormalizer

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `normalize` | `(raw_data: dict, source: str) -> MemoryEvent` | 清洗后数据、来源标识 | 标准化 MemoryEvent | 核心标准化方法 |
| `batch_normalize` | `(raw_data_list: list[dict], source: str) -> list[MemoryEvent]` | 批量数据 | 批量事件 | 批量标准化 |

#### QualityScorer

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `score` | `(event: MemoryEvent) -> float` | 标准化事件 | 质量评分 [0, 1] | 更新 event.quality_score |
| `should_enter_long_term` | `(event: MemoryEvent) -> bool` | 事件 | 是否进入长期记忆 | quality_score >= 0.6 |

---

### 3.2 Preference 模块 — 偏好记忆

```
模块: memoryhub.core.preference
负责: 偏好抽取、置信度计算、版本管理
```

#### PreferenceExtractor

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `extract` | `(event: MemoryEvent) -> list[PreferenceMemory]` | 单条事件 | 候选偏好列表 | 规则 + LLM 抽取 |
| `_rule_extract` | `(event: MemoryEvent) -> list[PreferenceMemory]` | 事件 | 显式偏好列表 | 规则模板匹配 |
| `_llm_extract` | `(event: MemoryEvent) -> list[PreferenceMemory]` | 事件 | 隐式偏好列表 | LLM 辅助抽取 |

#### ConfidenceCalculator

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `calculate` | `(preference: PreferenceMemory) -> float` | 偏好 | 置信度 [0, 1] | 综合计算置信度 |
| `update_confidence` | `(preference: PreferenceMemory, new_event: MemoryEvent) -> float` | 已有偏好、新事件 | 更新后置信度 | 增量更新 |

#### PreferenceUpdater

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `add` | `(preference: PreferenceMemory) -> str` | 新偏好 | memory_id | 新增偏好 |
| `update` | `(old_id: str, new_preference: PreferenceMemory) -> str` | 旧 ID、新内容 | 新版本 memory_id | 生成新版本 |
| `merge` | `(pref_a, pref_b) -> PreferenceMemory` | 两条偏好 | 合并后偏好 | 合并策略 |
| `get_version_chain` | `(memory_id: str) -> list[PreferenceMemory]` | 记忆 ID | 版本链列表 | 从早到晚排序 |

---

### 3.3 Knowledge 模块 — 知识记忆

```
模块: memoryhub.core.knowledge
负责: 知识抽取、模板构建、工作流挖掘
```

#### KnowledgeExtractor

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `extract_from_trajectory` | `(events: list[MemoryEvent]) -> list[KnowledgeMemory]` | 任务事件序列 | 候选知识列表 | 从轨迹中抽取 |
| `extract_workflow` | `(events: list[MemoryEvent]) -> KnowledgeMemory \| None` | 事件序列 | 工作流知识或 None | 提取工作流 |
| `extract_case` | `(events: list[MemoryEvent]) -> KnowledgeMemory \| None` | 事件序列 | 案例知识或 None | 提取案例 |
| `extract_template` | `(events: list[MemoryEvent]) -> KnowledgeMemory \| None` | 事件序列 | 模板知识或 None | 提取模板 |

#### TemplateBuilder

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `build_from_case` | `(case: KnowledgeMemory) -> KnowledgeMemory` | 案例知识 | 模板知识 | 案例→模板 |
| `render_template` | `(template: KnowledgeMemory, variables: dict) -> str` | 模板、变量 | 渲染文本 | 模板渲染 |

#### WorkflowMiner

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `mine` | `(task_groups: list[list[MemoryEvent]]) -> list[KnowledgeMemory]` | 多组任务轨迹 | 工作流知识列表 | 挖掘稳定模式 |

---

### 3.4 Conflict 模块 — 冲突处理

```
模块: memoryhub.core.conflict
负责: 冲突检测、冲突解决
```

#### ConflictDetector

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `check_preference` | `(new_pref: PreferenceMemory, existing: list[PreferenceMemory]) -> ConflictRecord \| None` | 新偏好 + 已有偏好列表 | 冲突记录或 None | 检测偏好冲突 |
| `check_knowledge` | `(new_know: KnowledgeMemory, existing: list[KnowledgeMemory]) -> ConflictRecord \| None` | 新知识 + 已有知识列表 | 冲突记录或 None | 检测知识冲突 |

#### ConflictResolver

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `resolve` | `(conflict: ConflictRecord, old_memory, new_memory) -> ConflictRecord` | 冲突记录 + 新旧记忆 | 更新后冲突记录 | 解决冲突 |
| `auto_resolve` | `(conflict: ConflictRecord) -> ConflictDecision` | 冲突记录 | 建议决策 | 自动判断策略 |
| `manual_resolve` | `(conflict_id: str, decision: ConflictDecision, reason: str) -> ConflictRecord` | 冲突 ID、决策、原因 | 更新后记录 | 手动解决 |

---

### 3.5 Safety 模块 — 安全过滤与遗忘

```
模块: memoryhub.core.safety
负责: 敏感信息检测、精准遗忘
```

#### SensitiveDetector

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `detect` | `(event: MemoryEvent) -> SensitiveLevel` | 事件 | 敏感等级 | 检测敏感信息 |
| `mask` | `(event: MemoryEvent) -> MemoryEvent` | 原始事件 | 脱敏后事件 | 敏感信息脱敏 |
| `should_reject` | `(event: MemoryEvent) -> tuple[bool, str]` | 事件 | `(是否拒绝, 原因)` | 判断是否拒绝入库 |

#### MemoryForgetter

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `execute` | `(request: ForgetRequest) -> ForgetResponse` | 遗忘请求 | 遗忘结果 | 执行精准遗忘 |
| `parse_intent` | `(instruction: str) -> dict` | 自然语言指令 | 意图结构 | LLM 解析意图 |
| `locate_memories` | `(intent: dict, user_id: str) -> list[str]` | 意图、用户 ID | 目标记忆 ID 列表 | 定位目标记忆 |
| `delete_memories` | `(memory_ids: list[str]) -> int` | 记忆 ID 列表 | 删除数量 | 删除记忆+向量+缓存 |

---

### 3.6 Lifecycle 模块 — 记忆生命周期

```
模块: memoryhub.core.lifecycle
负责: 短/中/长期记忆流转管理
```

#### LifecycleManager

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `classify` | `(event: MemoryEvent) -> MemoryLevel` | 事件 | 建议记忆层级 | 新事件分类 |
| `should_promote` | `(memory_id: str, current_level: MemoryLevel) -> bool` | 记忆 ID、当前层级 | 是否应升级 | 检查升级条件 |
| `promote` | `(memory_id: str, from_level: MemoryLevel, to_level: MemoryLevel) -> bool` | 记忆 ID、层级变化 | 是否成功 | 执行升级 |
| `run_lifecycle_check` | `() -> dict` | 无 | `{promoted, expired, checked}` | 定时检查 |

---

### 3.7 Retrieval 模块 — 混合检索

```
模块: memoryhub.retrieval
负责: 向量检索、关键词检索、重排序、缓存
```

#### HybridRetriever

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `search` | `(request: SearchRequest) -> SearchResponse` | 检索请求 | 检索响应 | 混合检索入口 |

#### VectorSearcher

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `add` | `(memory_id: str, vector: list[float]) -> None` | 记忆 ID、向量 | 无 | 添加向量 |
| `search` | `(query_vector: list[float], top_k: int) -> list[SearchResult]` | 查询向量、K 值 | 结果列表 | 向量检索 |
| `delete` | `(memory_id: str) -> bool` | 记忆 ID | 是否成功 | 删除向量 |

#### KeywordSearcher

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `build_index` | `(documents: list[tuple[str, str, str]]) -> None` | 文档列表 | 无 | 构建 BM25 索引 |
| `search` | `(query: str, top_k: int) -> list[SearchResult]` | 查询文本、K 值 | 结果列表 | 关键词检索 |

#### Reranker

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `rerank` | `(results: list[SearchResult], request: SearchRequest) -> list[SearchResult]` | 融合结果、请求 | 重排序结果 | 二次排序 |

#### SearchCache

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `get` | `(request: SearchRequest) -> SearchResponse \| None` | 请求 | 缓存结果或 None | 查询缓存 |
| `set` | `(request: SearchRequest, response: SearchResponse) -> None` | 请求、响应 | 无 | 写入缓存 |
| `invalidate` | `(memory_id: str) -> None` | 记忆 ID | 无 | 使缓存失效 |

---

### 3.8 Storage 层 — 持久化

```
模块: memoryhub.storage
负责: SQLite ORM、FAISS 向量索引、证据链存储
```

#### Database

| 方法 | 签名 | 说明 |
|---|---|---|
| `init_schema` | `() -> None` | 创建所有表 |
| `session` | `() -> Session` | 获取数据库会话 |

#### Repository 接口（统一模式）

所有 Repository 遵循以下模式：

```python
class XxxRepository:
    def save(self, row) -> None: ...           # 保存单条
    def batch_save(self, rows: list) -> int: ... # 批量保存
    def get_by_id(self, id: str) -> ...: ...    # 按 ID 查询
    def get_by_xxx(self, ...) -> list: ...      # 按条件查询
    def update_xxx(self, id: str, ...) -> None: ...  # 更新
```

具体 Repository: `EventRepository`, `PreferenceRepository`, `KnowledgeRepository`, `ConflictRepository`, `ForgetRepository`

#### VectorStore

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `init_index` | `(index_type: str) -> None` | 索引类型 | 无 | 初始化 FAISS 索引 |
| `add` | `(memory_id: str, vector: list[float]) -> None` | ID、向量 | 无 | 添加向量 |
| `search` | `(query_vector: list[float], top_k: int) -> list[tuple[str, float]]` | 查询向量 | `[(ID, 分数)]` | 向量检索 |
| `delete` | `(memory_id: str) -> bool` | ID | 是否成功 | 删除向量 |
| `save` / `load` | `() -> None` | 无 | 无 | 持久化/加载 |

#### EvidenceStore

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `save` | `(memory_id: str, evidence: Evidence) -> None` | 记忆 ID、证据 | 无 | 追加证据 |
| `load` | `(memory_id: str) -> list[Evidence]` | 记忆 ID | 证据列表 | 加载证据 |
| `delete` | `(memory_id: str) -> bool` | 记忆 ID | 是否成功 | 删除证据 |

---

### 3.9 LLM / Embedding 抽象层

```
模块: memoryhub.llm, memoryhub.embedding
负责: 统一接口抽象，支持多种后端
```

#### BaseLLMClient

| 方法 | 签名 | 说明 |
|---|---|---|
| `generate` | `(prompt: str, system_prompt: str, **kwargs) -> LLMResponse` | 生成文本 |
| `generate_json` | `(prompt: str, schema: dict, system_prompt: str) -> dict` | 生成结构化 JSON |
| `is_available` | `() -> bool` | 检查服务可用性 |

**LLMResponse 结构**: `{content: str, model: str, tokens_used: int, latency_ms: float}`

#### BaseEmbeddingClient

| 方法 | 签名 | 说明 |
|---|---|---|
| `embed` | `(text: str) -> list[float]` | 文本→向量 |
| `batch_embed` | `(texts: list[str]) -> list[list[float]]` | 批量文本→向量 |
| `get_dimension` | `() -> int` | 返回向量维度 |
| `is_available` | `() -> bool` | 检查服务可用性 |

---

## 4. 数据流转图

### 4.1 写入流（事件→记忆）

```
OS Agent 工具调用完成
       │
       ▼
┌─────────────────┐
│  POST /events   │   WriteEventRequest.events: list[MemoryEvent]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  DataCleaner    │   raw_data → clean → deduplicate → validate
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ DataNormalizer  │   raw_data → normalize → MemoryEvent
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ QualityScorer   │   MemoryEvent → score → 更新 quality_score
└────────┬────────┘
         │
         ├── quality_score < 0.6 ──→ 仅进入短期记忆
         │
         ▼
┌─────────────────┐
│SensitiveDetector│   MemoryEvent → detect → mask
└────────┬────────┘
         │
         ├── sensitive_level == HIGH ──→ 拒绝入库
         │
         ▼
┌─────────────────┐
│ EventRepository │   MemoryEvent → 存入 SQLite events 表
└────────┬────────┘
         │
         ├── event_type == user_feedback / user_behavior
         │         │
         │         ▼
         │  ┌──────────────────────┐
         │  │PreferenceExtractor  │   MemoryEvent → extract → 候选偏好
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ConfidenceCalculator │   候选偏好 → calculate → confidence
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ ConflictDetector    │   新偏好 vs 已有偏好 → 有冲突?
         │  └──────────┬───────────┘
         │             │
         │             ├── 有冲突 → ConflictResolver → ConflictRecord
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ PreferenceUpdater   │   add/update/merge → PreferenceMemory
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ PreferenceRepository│   存入 SQLite preferences 表
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ Embedding + VectorStore │ 文本→向量→存入 FAISS
         │  └──────────────────────┘
         │
         ├── event_type == task_trajectory
         │         │
         │         ▼
         │  ┌──────────────────────┐
         │  │KnowledgeExtractor   │   事件序列 → extract → 候选知识
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ConflictDetector     │   新知识 vs 已有知识
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │KnowledgeRepository  │   存入 SQLite knowledge 表
         │  └──────────┬───────────┘
         │             │
         │             ▼
         │  ┌──────────────────────┐
         │  │ Embedding + VectorStore │ 文本→向量→存入 FAISS
         │  └──────────────────────┘
         │
         ▼
   ┌──────────────────┐
   │ LifecycleManager │   classify → SHORT / MID / LONG
   └──────────────────┘
```

### 4.2 检索流

```
OS Agent 发起检索请求
       │
       ▼
┌─────────────────┐
│ POST /search    │   SearchRequest {query, context, top_k, ...}
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SearchCache    │   检查缓存 → 命中? → 直接返回
└────────┬────────┘
         │ 未命中
         ▼
┌─────────────────────────────────────────┐
│           HybridRetriever               │
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │VectorSearcher│  │KeywordSearcher│   │
│  │  (FAISS)     │  │  (BM25)      │    │
│  └──────┬───────┘  └──────┬───────┘    │
│         │                  │            │
│         ▼                  ▼            │
│  ┌──────────────────────────────┐      │
│  │      _merge_results          │      │
│  │  vector_weight × vector_score│      │
│  │+ keyword_weight × keyword_scr│      │
│  │+ metadata_weight × metadata  │      │
│  └──────────────┬───────────────┘      │
│                 │                       │
│                 ▼                       │
│  ┌──────────────────────────────┐      │
│  │    _filter_by_context        │      │
│  │  scope 匹配 + 置信度过滤      │      │
│  └──────────────┬───────────────┘      │
│                 │                       │
│                 ▼                       │
│  ┌──────────────────────────────┐      │
│  │        Reranker              │      │
│  │  相关性 + scope + 新鲜度      │      │
│  └──────────────┬───────────────┘      │
│                 │                       │
└─────────────────┼───────────────────────┘
                  │
                  ▼
         ┌─────────────────┐
         │  SearchCache    │   写入缓存
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │ SearchResponse  │   返回 preferences + knowledge + latency_ms
         └─────────────────┘
```

### 4.3 遗忘流

```
用户: "忘掉我关于周报格式的偏好"
       │
       ▼
┌─────────────────┐
│ POST /forget    │   ForgetRequest {instruction, target_scope}
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ MemoryForgetter │
│                 │
│  1. parse_intent│   instruction → LLM → {memory_type, target_topic, scope}
│                 │
│  2. locate      │   intent → 查询 SQLite → 目标 memory_ids
│                 │
│  3. delete      │   memory_ids →
│     - SQLite    │     DELETE FROM preferences/knowledge
│     - FAISS     │     VectorStore.batch_delete
│     - Cache     │     SearchCache.invalidate
│     - Evidence  │     EvidenceStore.delete
│                 │
│  4. audit_log   │   生成 ForgetRecord → 存入 forget_history
│                 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ForgetResponse  │   {record_id, deleted_count, deleted_ids}
└─────────────────┘
```

### 4.4 生命周期流转

```
┌─────────┐    质量评分 < 0.6     ┌─────────┐
│  事件    │ ──────────────────→  │ 短期记忆 │
│(写入时)  │                      │ (SHORT)  │
└─────────┘                      └────┬────┘
                                      │
                              出现次数 ≥ 2
                              quality_score ≥ 0.4
                                      │
                                      ▼
                                ┌─────────┐
                                │ 中期记忆 │
                                │  (MID)  │
                                └────┬────┘
                                      │
                              出现次数 ≥ 5
                              confidence ≥ 0.7
                              存在天数 ≥ 3
                                      │
                                      ▼
                                ┌─────────┐
                                │ 长期记忆 │
                                │  (LONG) │
                                └────┬────┘
                                      │
                              30 天无更新(MID)
                              365 天无更新(LONG)
                                      │
                                      ▼
                                ┌─────────┐
                                │  过期    │
                                │(archived)│
                                └─────────┘
```

---

## 5. REST API 规范

### 5.1 事件写入

```
POST /api/memory/events

请求体 (WriteEventRequest):
{
    "events": [
        {
            "event_id": "ev_abc123def456",
            "user_id": "u001",
            "session_id": "sess_001",
            "task_id": "task_001",
            "event_type": "tool_call",
            "source": "os_agent",
            "content": {
                "tool_name": "file_search",
                "input": "查找项目周报相关文件",
                "output": "找到 3 个项目文档",
                "status": "success"
            },
            "scene": "office",
            "task_type": "office.weekly_report",
            "timestamp": "2026-07-15T10:30:00",
            "quality_score": 0.0,
            "sensitive_level": "none",
            "metadata": {}
        }
    ]
}

响应 (WriteEventResponse):
{
    "accepted": 1,
    "rejected": 0,
    "event_ids": ["ev_abc123def456"]
}
```

### 5.2 记忆检索

```
POST /api/memory/search

请求体 (SearchRequest):
{
    "user_id": "u001",
    "query": "按上次的方式生成项目周报",
    "context": {
        "scene": "office",
        "task_type": "office.weekly_report",
        "app": "os_agent"
    },
    "top_k": 5,
    "memory_types": ["preference", "knowledge"],
    "min_confidence": 0.5
}

响应 (SearchResponse):
{
    "preferences": [
        {
            "memory_id": "pref_001",
            "content": "项目周报默认使用 Markdown 格式",
            "confidence": 0.92,
            "scope": {"scene": "office", "task_type": "office.weekly_report"}
        }
    ],
    "knowledge": [
        {
            "memory_id": "know_001",
            "name": "项目周报生成流程",
            "steps": ["读取日历", "检索文件", "提取进展", "整理风险", "生成报告"],
            "tools": ["calendar", "file_search", "doc_reader", "report_writer"]
        }
    ],
    "latency_ms": 128.5,
    "total_count": 2
}
```

### 5.3 精准遗忘

```
POST /api/memory/forget

请求体 (ForgetRequest):
{
    "user_id": "u001",
    "instruction": "忘掉我关于周报格式的偏好"
}

响应 (ForgetResponse):
{
    "record_id": "forg_xyz789",
    "deleted_count": 1,
    "deleted_ids": ["pref_001"],
    "audit_log": "删除偏好记忆 1 条: 项目周报默认使用 Markdown"
}
```

### 5.4 其他接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/memory/preferences` | 列出偏好（支持 scene/status 过滤） |
| GET | `/api/memory/preferences/{id}` | 获取单条偏好 |
| GET | `/api/memory/preferences/{id}/versions` | 获取版本链 |
| GET | `/api/memory/knowledge` | 列出知识 |
| GET | `/api/memory/knowledge/{id}` | 获取单条知识 |
| GET | `/api/memory/conflicts` | 列出冲突记录 |
| POST | `/api/memory/conflicts/{id}/resolve` | 手动解决冲突 |
| POST | `/api/memory/feedback` | 提交用户反馈 |
| POST | `/api/memory/evaluate/{task_name}` | 运行评测 |
| GET | `/api/memory/evaluate/reports` | 列出评测报告 |

---

## 6. 存储层映射

### 6.1 SQLite 表结构

#### events 表

| 字段 | 类型 | 说明 |
|---|---|---|
| event_id | VARCHAR(32) PK | 事件 ID |
| user_id | VARCHAR(64) INDEX | 用户 ID |
| session_id | VARCHAR(64) | 会话 ID |
| task_id | VARCHAR(64) INDEX | 任务 ID |
| event_type | VARCHAR(32) | 事件类型 |
| source | VARCHAR(64) | 数据来源 |
| content | JSON | 事件内容 |
| scene | VARCHAR(64) INDEX | 场景 |
| task_type | VARCHAR(128) INDEX | 任务类型 |
| timestamp | DATETIME | 时间戳 |
| quality_score | FLOAT | 质量评分 |
| sensitive_level | VARCHAR(16) | 敏感等级 |
| metadata | JSON | 扩展元数据 |

#### preferences 表

| 字段 | 类型 | 说明 |
|---|---|---|
| memory_id | VARCHAR(32) PK | 记忆 ID |
| user_id | VARCHAR(64) INDEX | 用户 ID |
| memory_type | VARCHAR(16) | 固定 "preference" |
| preference_type | VARCHAR(32) | 偏好类型 |
| content | TEXT | 偏好描述 |
| scope_scene | VARCHAR(64) INDEX | 场景 |
| scope_task_type | VARCHAR(128) INDEX | 任务类型 |
| scope_app | VARCHAR(64) | 来源应用 |
| confidence | FLOAT | 置信度 |
| status | VARCHAR(16) INDEX | 状态 |
| level | VARCHAR(16) | 记忆层级 |
| version | INT | 版本号 |
| parent_id | VARCHAR(32) | 前一版本 ID |
| evidences | JSON | 证据链 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

#### knowledge 表

与 preferences 表类似，额外字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| knowledge_type | VARCHAR(32) | 知识类型 |
| name | VARCHAR(256) | 知识名称 |
| steps | JSON | 工作流步骤 |
| tools | JSON | 工具链 |
| template_body | TEXT | 模板正文 |
| success_count | INT | 成功复用次数 |
| total_count | INT | 总调用次数 |

#### conflicts 表

| 字段 | 类型 | 说明 |
|---|---|---|
| conflict_id | VARCHAR(32) PK | 冲突 ID |
| old_memory_id | VARCHAR(32) | 旧记忆 ID |
| new_memory_id | VARCHAR(32) | 新记忆 ID |
| memory_type | VARCHAR(16) | 记忆类型 |
| old_content | TEXT | 旧内容 |
| new_content | TEXT | 新内容 |
| conflict_field | VARCHAR(64) | 冲突字段 |
| decision | VARCHAR(16) | 处理决策 |
| reason | TEXT | 处理原因 |
| result_memory_id | VARCHAR(32) | 结果记忆 ID |
| created_at | DATETIME | 创建时间 |
| resolved_at | DATETIME | 解决时间 |

#### forget_history 表

| 字段 | 类型 | 说明 |
|---|---|---|
| record_id | VARCHAR(32) PK | 记录 ID |
| user_id | VARCHAR(64) INDEX | 用户 ID |
| instruction | TEXT | 遗忘指令 |
| target_memory_ids | JSON | 目标记忆 ID |
| deleted_count | INT | 删除数量 |
| created_at | DATETIME | 创建时间 |

### 6.2 FAISS 索引

- 索引文件: `data/vector_index/faiss.index`
- ID 映射文件: `data/vector_index/id_map.json`
- 向量维度: 1024（与麒麟 embedding SDK 一致）
- 索引类型: 默认 `IndexFlatL2`（小数据量），可选 `IndexIVFFlat` 或 `IndexHNSWFlat`

### 6.3 证据链存储

- 目录: `data/evidence/`
- 文件格式: `{memory_id}.jsonl`
- 每行一个 Evidence JSON 对象

---

## 附录: 检索请求/响应模型

### SearchRequest

```python
class SearchRequest(BaseModel):
    user_id: str = "default"
    query: str = ""                        # 查询文本
    context: SceneScope                    # 场景上下文
    top_k: int = 5                         # 返回数量
    memory_types: list[str] = []           # 过滤: ["preference", "knowledge"]
    min_confidence: float = 0.0            # 最低置信度阈值
```

### SearchResult

```python
class SearchResult(BaseModel):
    memory_id: str         # 记忆 ID
    memory_type: str       # "preference" | "knowledge"
    content: str           # 内容摘要
    score: float           # 综合得分
    source: str            # 来源: "vector" | "keyword" | "metadata"
    metadata: dict         # 附加信息
```

### SearchResponse

```python
class SearchResponse(BaseModel):
    results: list[SearchResult]         # 原始检索结果
    preferences: list[PreferenceMemory] # 匹配的偏好记忆
    knowledge: list[KnowledgeMemory]    # 匹配的知识记忆
    latency_ms: float                   # 检索耗时
    total_count: int                    # 总结果数
```
