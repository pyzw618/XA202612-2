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
    source_type: SourceType # 接入来源大类
    timestamp: datetime     # 证据产生时间
    weight: float = 1.0     # 该证据的权重 [0, 1]
```

---

### 1.3 MemoryEvent — 统一事件模型

**所有多源数据完成清洗、标准化和质量评分后的唯一标准格式。** 这是接入模块与存储、偏好抽取、知识沉淀、冲突检测等下游模块之间的共享契约。

```python
class MemoryEvent(BaseModel):
    event_id: str                 # 事件唯一 ID
    source_type: SourceType       # tool_result | user_behavior | manual_config
    event_type: str               # 来源内的具体动作，如 tool_result、user_action
    user_id: str                  # 用户 ID；无法识别时为空并降低质量分
    session_id: str               # 会话或任务链 ID，可为空
    turn_id: str                  # 同一轮 Agent 调用链的关联 ID，可为空
    scene: str                    # 场景，如 office、coding
    task_type: str                # 任务类型，如 weekly_report
    occurred_at: str              # UTC 时间，格式 YYYY-MM-DDTHH:MM:SSZ
    text: str                     # 供偏好/知识抽取使用的摘要文本
    payload: dict                 # 来源特有结构化内容
    tool_calls: list[ToolCallResult] # 工具调用明细，按 sequence 排序
    schema_version: Literal["1.0", "1.1"] # 新事件默认 1.1
    source_hash: str              # 清洗后原始事件的 64 位 SHA-256
    redactions: list[str]         # 脱敏类型，如 api_key、token、email、phone
    quality: EventQuality         # 总分、分项分数、状态和问题列表

class EventQuality(BaseModel):
    score: float                  # 综合质量分 [0, 1]
    status: QualityStatus         # accepted | review | rejected
    completeness: float           # 完整性 [0, 1]
    validity: float               # 合法性 [0, 1]
    consistency: float            # 来源与 tool_calls/payload 一致性 [0, 1]
    freshness: float              # 新鲜度 [0, 1]
    issues: list[str]             # 可审计问题代码

class ToolCallResult(BaseModel):
    call_id: str                  # 单次调用唯一 ID
    tool_name: str                # 工具名，必须保留
    arguments: dict               # 本次调用参数
    result: Any                   # 本次调用的原始结构化结果或文本
    status: ToolCallStatus         # success | error | timeout | cancelled | partial
    sequence: int                 # 同一轮调用顺序，从 1 开始
    error: str                    # 失败原因；成功时为空
```

`MemoryEvent` 顶层禁止未声明字段。工具轨迹使用强类型 `tool_calls`，其他来源特有扩展只能进入 `payload`。`text` 只表示最终回答或摘要，不能用它替代工具结果。只要 `event_type=agent_response`，就必须提供非空 `turn_id`、`text` 和至少一个 `tool_calls` 项；每个工具调用的工具名、参数、结果、状态和顺序都必须保留。

如果系统采用流式写入，可以把每次调用拆成一条 `tool_result` 事件，并使用同一个 `session_id + turn_id` 关联；如果系统在 Agent 回复完成后一次性写入，则把这一轮的所有调用放在同一个 `agent_response` 事件的 `tool_calls` 列表中。

版本兼容规则：`1.0` 仅用于读取历史事件，允许旧工具结果继续保存在 `payload`；新接入输出必须使用 `1.1`，并且所有 `source_type=tool_result` 事件至少包含一个 `tool_calls` 项。

`call_id` 在一条事件内必须唯一；上游没有调用 ID 时，由接入适配器确定性生成。相同工具可以被重复调用，但每次调用必须分别占一个列表项，并拥有独立的 `call_id`、`arguments`、`result` 和 `sequence`。列表必须按 `sequence` 升序排列，不能只保存最后一次调用结果。

#### payload 字段结构（按 source_type 区分）

| source_type | event_type 示例 | payload 典型结构 |
|---|---|---|
| `tool_result` | `tool_result`、`task_trajectory`、`agent_response` | `tool_calls[]` 保存 `tool_name`、`arguments`、`result`、`status`；`payload` 只放聚合元数据 |
| `user_behavior` | `user_action`、`user_feedback` | `{"action": str, "target": str, "value": Any}` |
| `manual_config` | `manual_config` | `{"key": str, "value": Any}` |

#### 多工具调用示例

下面表示同一轮 Agent 先搜索文件、再读取日历，最后基于两个工具结果生成回答。下游不需要从最终回答中反向猜测工具结果。

```json
{
  "event_id": "evt_agent_response_001",
  "source_type": "tool_result",
  "event_type": "agent_response",
  "user_id": "u001",
  "session_id": "session_001",
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
      "arguments": {"range": "2026-07-20/2026-07-26"},
      "result": {"events": [{"title": "周会"}]},
      "status": "success",
      "sequence": 2,
      "error": ""
    }
  ],
  "schema_version": "1.1",
  "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "redactions": [],
  "quality": {
    "score": 1.0,
    "status": "accepted",
    "completeness": 1.0,
    "validity": 1.0,
    "consistency": 1.0,
    "freshness": 1.0,
    "issues": []
  }
}
```

#### 从旧版字段迁移

旧格式不再是模块间契约。接入适配器可以读取旧字段，但必须在交给下游之前完成以下转换；`MemoryEvent` 不会静默接受旧字段。

| 旧字段 | 规范字段/处理方式 |
|---|---|
| `source` | 归一为 `source_type`，不能直接传 `os_agent` 等应用名 |
| `content` | 来源结构化内容放入 `payload`；可抽取文本放入 `text` |
| `timestamp` | 转为 UTC 秒精度字符串 `occurred_at` |
| `quality_score` | 转为包含分项、状态和问题的 `quality` 对象 |
| `task_id` | 会话链标识放入 `session_id`，任务分类放入 `task_type` |
| `content.tool_name/output` | 转为 `tool_calls[].tool_name/result`，并补充 `call_id`、`sequence`、`status` |
| `sensitive_level` / `metadata` | 脱敏结果放入 `redactions` 和 `quality.issues`；来源扩展放入 `payload` |

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

### SourceType — 接入来源大类

| 值 | 含义 | payload 一致性要求 |
|---|---|---|
| `tool_result` | 工具或 Agent 执行结果 | 新事件应包含 `tool_calls`，每项必须有 `tool_name` 和独立结果 |
| `user_behavior` | 用户操作、消息或显式反馈 | 应包含 `action`、`target` 或 `value` 之一 |
| `manual_config` | 用户或管理员手动配置 | 应包含配置键或值 |

`event_type` 是开放字符串，不再使用封闭枚举。它描述来源内的具体事件，例如 `tool_result`、`user_action`、`user_feedback`、`task_trajectory`；`source_type` 才是接入路由和质量一致性校验使用的稳定枚举。

### ToolCallStatus — 工具调用状态

| 值 | 含义 |
|---|---|
| `success` | 工具正常返回完整结果 |
| `error` | 工具执行失败，错误信息写入 `error` |
| `timeout` | 工具调用超时 |
| `cancelled` | 工具调用被取消 |
| `partial` | 只获得部分结果 |

### QualityStatus — 接入质量状态

| 值 | 处理策略 |
|---|---|
| `accepted` | `score >= 0.80` 且无硬门槛问题，可进入存储与记忆抽取链路 |
| `review` | `0.60 <= score < 0.80`，或存在缺字段、非法来源/时间等问题，进入复核队列 |
| `rejected` | `score < 0.60`，或同时缺少用户标识且时间非法，仅保留审计记录 |

质量分统一按以下公式计算，不再使用旧版 `source_reliability`、`execution_success` 等因子：

```text
score = 0.40 * completeness
      + 0.30 * validity
      + 0.20 * consistency
      + 0.10 * freshness
```

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
| `normalize` | `(raw_data: dict, source_type: str = "") -> MemoryEvent` | 清洗后数据、来源类型 | 标准化 MemoryEvent | 核心标准化方法 |
| `batch_normalize` | `(raw_data_list: list[dict], source_type: str = "") -> list[MemoryEvent]` | 批量数据 | 批量事件 | 批量标准化 |

#### QualityScorer

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `score` | `(event: MemoryEvent) -> EventQuality` | 标准化事件 | 质量明细 | 按四项分数生成 `event.quality` |
| `should_enter_long_term` | `(event: MemoryEvent) -> bool` | 事件 | 是否进入下游记忆链路 | `quality.status == accepted` |

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
│ QualityScorer   │   MemoryEvent → score → 生成 quality
└────────┬────────┘
         │
         ├── quality.status == review ──→ 进入复核队列，不直接抽取
         │
         ▼
┌─────────────────┐
│ RedactionAudit  │   检查 redactions / quality.issues
└────────┬────────┘
         │ accepted
         ▼
┌─────────────────┐
│ EventRepository │   MemoryEvent → 存入 SQLite events 表
└────────┬────────┘
         │
          ├── source_type == user_behavior
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
┌─────────┐    status=accepted     ┌─────────┐
│  事件    │ ──────────────────→  │ 短期记忆 │
│(写入时)  │                      │ (SHORT)  │
└─────────┘                      └────┬────┘
       │
       ├── status=review → 复核队列
       └── status=rejected → 审计记录
                                      │
                              出现次数 ≥ 2
                              quality.score ≥ 0.4
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
            "turn_id": "turn_007",
            "source_type": "tool_result",
            "event_type": "agent_response",
            "payload": {
                "response_status": "success"
            },
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
            "occurred_at": "2026-07-15T10:30:00Z",
            "text": "已根据项目文件和本周日程生成周报。",
            "schema_version": "1.1",
            "source_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "redactions": [],
            "quality": {
                "score": 1.0,
                "status": "accepted",
                "completeness": 1.0,
                "validity": 1.0,
                "consistency": 1.0,
                "freshness": 1.0,
                "issues": []
            }
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
| source_type | VARCHAR(32) INDEX | 接入来源大类 |
| event_type | VARCHAR(64) INDEX | 来源内具体事件类型 |
| user_id | VARCHAR(64) INDEX | 用户 ID |
| session_id | VARCHAR(64) | 会话 ID |
| turn_id | VARCHAR(64) INDEX | 同一轮 Agent 调用链 ID |
| scene | VARCHAR(64) INDEX | 场景 |
| task_type | VARCHAR(128) INDEX | 任务类型 |
| occurred_at | DATETIME | 规范化后的 UTC 事件时间 |
| text | TEXT | 抽取摘要文本 |
| payload | JSON | 来源特有结构化内容 |
| tool_calls | JSON | 按 `sequence` 排序的 `ToolCallResult` 列表 |
| schema_version | VARCHAR(16) | canonical schema 版本 |
| source_hash | VARCHAR(64) INDEX | 清洗后事件哈希，用于审计和去重 |
| redactions | JSON | 脱敏类型列表 |
| quality | JSON | `EventQuality` 完整对象 |

旧版 `task_id/source/content/timestamp/quality_score/sensitive_level/metadata` 列不再用于新事件。已有数据库升级时必须执行显式迁移，不能把旧列和新列并列当作两个可选契约。

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
