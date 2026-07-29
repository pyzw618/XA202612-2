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

> 当前阶段已落地安全接口契约、版本化规则库、递归扫描、策略执行、事件脱敏、
> 同快照复检、内存审计投影、持久审计链、REVIEW 加密隔离和强制写入 Gate。
> 共享安全处理模型定义在 `memoryhub.adapter.schemas`，规则资产模型定义在
> `memoryhub.safety_rules`，并由 `memoryhub.core.safety` 稳定导出。普通 SQLite、
> 向量和证据业务实现仍是脚手架；后续只能作为 Gate 的受保护 sink 接入。

#### 版本化规则库

| 类型/入口 | 关键字段或行为 | 约束 |
|---|---|---|
| `RuleDefinition` | `rule_id`, `category`, `risk_level`, `default_action`, `pattern`, `validator`, `masker`, `target_paths`, `target_path_case_sensitive`, `priority`, `standard_ref`, `rule_version`, `enabled` | extra 禁止；规则、路径、捕获组和组件引用在加载时整体校验 |
| `RuleSource` / `RuleSourceLink` | 来源类型、效力、版次、状态日期、官方定位；来源到规则的用途与 caveat | 分类、语法、验证、处理、去标识化、评估、生命周期、审计和项目策略不得混写 |
| `RuleSetSnapshot` | 规则集 ID/版本、来源、治理引用、声明式规则、兼容规则、组件注册表摘要、canonical digest | 深度不可变；摘要覆盖声明文档、编译 schema/结果和当前规则引用的组件；规则按 `(-priority, rule_id, rule_version)` 规范排序 |
| `load_builtin_rule_set(version=...)` | 读取 catalog 默认版本或精确版本 | 使用包资源；不存在或摘要不符即失败，不回退、不部分加载 |
| `ComponentRegistry` | 解析版本化组件 ID、绑定实现指纹和 masker capability | 只接受可检查源码、无 closure/可变全局的 Python 函数；禁止任意模块路径、import 或 eval；`redact_allow` 要求 `full_redaction` capability |

内置规则集把 `redact_allow` 编译为 `SafetyAction.MASK`，保持第一步动作聚合和
复检约束不变；替换值只能是固定的 `[REDACTED...]` 标记，加载时会做契约探针，
每次完整替换调用还必须返回 replacement（输入已经是安全标记时允许幂等返回）。
候选正则只负责缩小范围；例如公民身份号码随后由版本化 validator
校验出生日期、顺序码和 MOD 11-2 校验位，IPv4 候选由 IP 解析器校验八位组。
规则的法律、标准、RFC、安全指南和项目策略来源见
[`SAFETY_RULE_LIBRARY.md`](SAFETY_RULE_LIBRARY.md)。

#### 安全数据契约

| 类型 | 关键字段 | 约束 |
|---|---|---|
| `SensitiveRule` | `name`, `version`, `pattern`, `level`, `action`, `reason_code`, `reason`, `standard_source`, `replacement`, `match_group`, `path_pattern`, `enabled` | 规则名在规则集内唯一；正则不得匹配空字符串；`MASK` 必须有替换文本；启用规则不得直接 `ALLOW` |
| `SafetyFinding` | `finding_id`, `rule_name`, `rule_version`, `level`, `suggested_action`, `field_path`, `target`, `start`, `end`, `maskable`, 原因与标准来源 | `field_path` 是 RFC 6901 JSON Pointer；`text_span` 的 `[start, end)` 是原始叶子字符串区间，`whole_value` 表示非字符串整值并固定为 `[0, 0)`；禁止保存命中原文 |
| `SafetyReport` | 事件/规则集摘要、`context`, `context_digest`, `attestation`, `findings`, `highest_level`, `scanned_field_count`, `scan_complete`, `issues` | 报告绑定事件摘要、一次规则快照和策略上下文；完整报告必须扫描至少一个字段且没有 issue；同一 detector 用进程内 HMAC attestation 阻断报告篡改 |
| `SafetyExceptionScope` / `SafetyPolicyException` | 规则与上下文作用域、原因、负责人、版本、有效期、可选规则集摘要 | 空上下文作用域、无时区有效期和重复例外 ID 均拒绝；普通 override 不得直接 `ALLOW` |
| `SafetyPolicy` | 不可变规则/等级覆盖、有限期例外、失败动作、`auto_sanitize`, `fail_closed` | 规则级覆盖优先于等级覆盖；覆盖只能提高动作严格度，不能削弱规则建议；仅低风险上下文标识允许作用域化 `ALLOW` |
| `SafetyDecision` | `report_id`, 最终 `action`, 策略版本/摘要、逐 Finding 动作、原因码、例外 ID、`decided_at` | 聚合优先级固定为 `REJECT > REVIEW > MASK > ALLOW`；等级本身不决定动作 |
| `SafetyAuditRecord` | 报告/事件/规则集/策略标识、最终动作、例外 ID、Finding 摘要、`processing_time_ms` | 仅内存安全投影；不得包含原事件正文、payload、工具结果或命中原文 |
| `SafetyAuditLogRecord` | 组件/规则/策略版本、动作、最高风险、分类计数、字段路径、脱敏数、HMAC 输入指纹、输出摘要、处理耗时、前驱/记录哈希 | 磁盘最小投影；不直接序列化 `SafetyAuditRecord`；记录由持久设备密钥认证并跨轮转分段成链 |
| `ApprovedWrite` | 递归只读安全事件、动作、审计 ID/记录哈希/序号、输出摘要、进程内 MAC | 只有 `SafetyWriteGate` 能签发；SQLite、Embedding、向量、证据链内容写入只能消费该能力对象 |
| `SafetyResult` | `report`, `decision`, `audit`, `sanitized_event`, `verification_report`, `attestation` | 各对象必须属于同一报告、规则和策略快照；`ALLOW/MASK` 才能携带递归只读的安全事件；`MASK` 必须有无残留的完整复检；同实例结果 HMAC 覆盖全部字段 |

`SensitiveLevel = none | low | medium | high` 只表示风险。处理动作独立为
`SafetyAction = allow | mask | review | reject`。因此 `HIGH + MASK` 与
`HIGH + REVIEW` 都是合法策略，禁止恢复为 “HIGH 一律拒绝”。
`SafetyFindingTarget = text_span | whole_value` 独立表示定位语义，不参与风险
等级或策略动作聚合。

所有 `*_digest` 统一使用 canonical JSON：Pydantic 模型先
`model_dump(mode="json")`，再以 `ensure_ascii=False`、键排序和紧凑分隔符
序列化为 UTF-8，最后计算小写 SHA-256。声明式 `RuleSetSnapshot.digest`
覆盖规范化后的完整规则和溯源、编译 schema、完整兼容规则及作用域化组件摘要；
组件摘要覆盖实际引用组件的实现指纹和 masker capability，内置 catalog 固定最终
快照摘要。兼容
`SensitiveDetector` 的摘要仍包含 `rule_set_version` 和调用方传入顺序的完整
编译规则，因此同一请求的报告、复检和审计必须复用同一个 detector 快照。
策略摘要包含完整 `SafetyPolicy` 以及兼容开关 `auto_mask`、
`reject_on_detect`。扫描器先以显式栈在结构预算内建立 JSON-like 事件快照，
事件摘要和规则遍历再共同消费该快照；事件摘要覆盖完整 `MemoryEvent`，避免
预检后再次读取可变 payload/tool result 产生摘要与命中不一致。
输入 `MemoryEvent` 仍是可变的 v0.1 模型；扫描器先建立独立快照且不修改输入。
`SafetyResult.sanitized_event` 会在结果边界重新校验并递归冻结顶层模型、payload、
工具参数/结果、redactions 与质量 issue；运行时映射不继承 `dict`，序列使用
tuple/frozenset，不能通过基类 mutator 绕过。`model_dump()` 仍投影为普通
JSON dict/list，保持持久化格式兼容。结果契约同时核对
事件摘要、上下文和复检摘要；`canonical_sha256()` 由 Safety 包公开供两端一致计算。
`SafetyReport.attestation` 是同一 detector 实例内的临时 HMAC 完整性标签，不是
跨事件关联令牌；随机实例密钥对除 `attestation` 外的整份报告做 HMAC-SHA256。
`SafetyResult.attestation` 使用同一临时密钥和独立域标签，覆盖报告、决策、审计、
安全事件与复检报告，阻断结果字段注入和跨候选拼接。独立调用
`scan/decide/sanitize` 或验证结果时必须使用同一存活实例，不支持跨实例或跨进程
移交；未来若需要跨进程验证，应引入带 key ID、版本和轮换策略的持久签名器。
把只读安全事件复制为可变对象后，该副本应重新视为不可信输入并再次调用 `process()`。

声明式 `target_paths` 会确定性编译为兼容规则的锚定 `path_pattern`；
后者使用 `re.search` 匹配 `field_path`，内容 `pattern` 使用 `finditer`
匹配字符串叶子；两者同时存在时必须同时满足。默认 `credential_field` 规则借此覆盖
`{"arguments": {"api_key": "sk-..."}}` 这类键值分离的结构化凭据。
目标模板是 RFC 6901 的受控扩展：整段 `*`/`**` 是 glob，`~2` 表示字面星号；
实际 `SafetyFinding.field_path` 仍只允许 RFC 6901 的 `~0`/`~1`。

扫描器和脱敏器都不会修改原事件。字符串内容先按 normalization unit 做 NFKC，并移除零宽/
格式控制字符；正则和 validator 使用该安全视图，Finding span 则反投影到原始
Unicode 字符位置。映射键本身不作为普通内容写入 Finding，而是经相同规范化后参与
临时路径匹配：原始键构成报告路径，规范化键只用于阻断全角、零宽敏感键名绕过。
若键名内容本身命中邮箱、电话等非路径规则，现有契约无法在不泄漏键名的情况下表达
可脱敏 span，扫描器会返回 `scan.sensitive_member_name` 并将报告标为不完整，
由失败关闭策略隔离；该键对应的整条分支不再生成可能泄漏键名的后代 Finding，
且不会把该键写入 Finding/issue。
路径规则命中的数字、布尔、null、对象或数组使用 `target=whole_value`，让后续
sanitize 能按路径整体替换而无需猜测虚构字符串 span。

运行时计划在 detector 构造时统一编译内容/路径正则，并从同一个
`RuleSetSnapshot` 绑定 priority 和 validator。每次扫描开始只校验一次组件注册表；
身份证、银行卡和 IP 等宽松候选必须通过日期/校验码、Luhn 或解析器验证。重叠候选
按“priority 降序、原始跨度降序、动作严格度、稳定规则标识”确定性选择。同一路径
的 `whole_value` 候选按该顺序保留一个；祖先整值与后代局部命中属于不同风险事实，
报告同时保留，避免低优先级祖先命中吞掉更严格的后代，`sanitize()` 再按
路径深度消除实际替换操作的冗余。没有
声明式 priority/validator 的旧 inline 规则只做 regex-only 检测，并以调用方顺序
作为合成 priority；只有与可信快照逐字段一致的规则才能绑定其 priority/validator，
同名同版本的外部规则不能冒充内置规则。

`scanned_field_count` 统计尝试扫描的映射键、标量叶子及持久化字符串元数据
（包括空字符串）；数组索引和容器本身不计入。扫描受最大深度、单字段字符数、
总 UTF-8 字节数、字段/节点数、
候选数、Finding 数及路径长度约束；可配置深度的安全硬上限是 64。无法在结构预算
内建立可信快照（包括循环引用）
时抛出 `SafetyScanError`，异常只含稳定代码且不含原文。快照后的候选/Finding
超限或 validator 异常会保留已确认结果，但 `scan_complete=false`，且 `issues`
只含稳定代码。`scan_text()` 没有不完整报告通道，因此遇到同类限制时直接抛出
`SafetyScanError`。

#### SensitiveDetector

| 方法 | 签名 | 输入 | 输出 | 说明 |
|---|---|---|---|---|
| `scan` | `(event: MemoryEvent) -> SafetyReport` | 原始事件 | 单次扫描报告 | 递归覆盖 `text`、`payload`、工具内容/标识及所有会持久化的自由字符串元数据；捕获一次规则快照；结构预检失败抛 `SafetyScanError` |
| `decide` | `(report: SafetyReport, policy: SafetyPolicy \| None = None) -> SafetyDecision` | 报告、策略 | 最终决策 | 只消费报告，不重新扫描；重验策略/报告并验证同实例 attestation |
| `sanitize` | `(event: MemoryEvent, report: SafetyReport) -> MemoryEvent` | 原事件、报告 | 脱敏副本 | 校验事件摘要和报告 attestation；按路径和 span 精确替换；不重新扫描 |
| `build_audit` | `(report: SafetyReport, decision: SafetyDecision) -> SafetyAuditRecord` | 报告、决策 | 内存安全审计投影 | 不读取或复制敏感原文；本阶段不负责持久化 |
| `process` | `(event: MemoryEvent) -> SafetyResult` | 原始事件 | 原子处理结果 | 唯一生产主入口；同一规则/策略快照完成扫描、决策、必要脱敏、复检和审计 |
| `validate_result` | `(event: MemoryEvent, result: SafetyResult) -> SafetyResult` | 原事件、外部或反序列化结果 | 已重新验证结果 | 写入信任边界入口；重验报告 attestation、事件/规则/策略绑定并重新决策；MASK 还会重新派生安全副本，拒绝被削弱或跨候选重放的结果 |
| `scan_text` | `(text: str, field_path: str = "/text") -> tuple[SafetyFinding, ...]` | 文本、字段路径 | 结构化命中 | 给出规则、路径、字符区间和原因 |
| `detect` | `(event: MemoryEvent, *, result: SafetyResult \| None = None) -> SensitiveLevel` | 事件、可选共享结果 | 最高敏感等级 | v0.1 兼容包装 |
| `detect_text` | `(text: str) -> tuple[SensitiveLevel, list[str]]` | 文本 | 等级和规则名 | v0.1 兼容包装；详细结果使用 `scan_text` |
| `mask` | `(event: MemoryEvent, *, result: SafetyResult \| None = None) -> MemoryEvent` | 原始事件、可选共享结果 | 已验证安全副本 | v0.1 兼容包装；仅接受未被削弱的同实例 `ALLOW/MASK` 结果，`REVIEW/REJECT` 失败关闭 |
| `mask_text` | `(text: str) -> str` | 文本 | 脱敏文本 | v0.1 兼容入口；规则/策略为 REVIEW/REJECT 或关闭自动脱敏时失败关闭 |
| `should_reject` | `(event: MemoryEvent, *, result: SafetyResult \| None = None) -> tuple[bool, str]` | 事件、可选共享结果 | `(是否阻止普通入库, 原因)` | v0.1 有损包装；`REVIEW/REJECT` 都返回 `True` |

事件扫描的自由字符串范围是
`event_id/event_type/user_id/session_id/turn_id/scene/task_type/text`、
递归 `payload` 键和值、`tool_calls[*].call_id/tool_name/arguments/result/error`、
`redactions[*]` 和 `quality.issues[*]`。`source_type/status/schema_version` 是枚举，
`occurred_at/source_hash` 有严格格式约束，不作为自由文本内容扫描。`event_id`
虽然会扫描，但为保持报告与审计身份绑定不允许原地脱敏；若其命中需要 MASK，
`process()` 会失败关闭到至少 `REVIEW`。
工具调用的正整数 `sequence` 也按整值扫描；它是顺序标识而不是内容字段，因此
命中后不可替换为字符串标记，同样至少进入 `REVIEW`。
`event_id/event_type/scene/task_type` 还会进入报告或策略上下文；一旦这些字段有
敏感候选，或扫描器无法确认其完整性，报告使用固定类型标记而不复制原值，审计沿用
安全事件引用。这样即使最终动作是 REVIEW/REJECT，报告、异常和审计也不携带该原文。

生产写入链不得独立调用 `detect() → mask() → should_reject()`。必须只调用
一次 `result = process(event)`。同一调用栈内可消费这个递归只读结果；结果一旦
经过反序列化、缓存或其他组件边界，写入门禁必须先调用
`result = validate_result(event, result)`，不能直接信任可手工构造的数据模型。
确需多个旧返回视图时，三个
包装都必须显式传入同一个 `result=result`。脱敏后复检是允许的第二次内容
扫描，但必须复用初始报告记录的同一规则集快照。

默认规则已经证明等级与动作解耦：API 凭据是 `HIGH + REJECT`，身份证号是
`HIGH + MASK`。兼容开关只做单向收紧：`reject_on_detect=True` 强制所有
命中进入 `REJECT`，`False` 不会降级结构化规则的显式 `REJECT`；
`auto_mask=False` 或 `policy.auto_sanitize=False` 会把原本的 `MASK` 提升为
`REVIEW`，绝不放行未脱敏原文。其余决策以 `SafetyPolicy` 为准。

完整且无命中的报告固定为 `ALLOW`；`fallback_action` 只处理与当前规则快照
元数据不一致的 Finding，不用于 clean report。不完整扫描至少进入 `REVIEW`。
逐 Finding 先按“规则覆盖 > 等级覆盖 > 规则建议”选择覆盖来源，再把覆盖动作
与规则建议按严格度取高者；普通覆盖因此只能收紧、不能降级。随后应用不可脱敏、
自动脱敏开关和全局拒绝门禁，最后按固定优先级聚合。

作用域化 `ALLOW` 不能通过普通 rule/level override 配置，必须使用
`SafetyPolicyException`，并同时提供规则名、至少一个来源/事件/场景/任务用途/
字段路径选择器、原因、负责人、版本和带时区的过期时间；有效窗口
`[valid_from, expires_at)` 按实际决策时刻判断并写入 `decided_at`，扫描时尚未
过期不能锁定放行资格。当前安全下限仅允许
低风险上下文标识（内置规则中的 IPv4）使用此例外；凭据、身份证、银行卡、
手机号、邮箱及敏感个人信息不能被例外降为 `ALLOW`。`REVIEW` 就是“阻止普通
写入并交给后续隔离复核”的决策信号，不新增独立 `QUARANTINE` 动作。

`sanitize()` 使用 Finding 自带的固定全值类型标记（如
`[REDACTED_PHONE]`、`[REDACTED_ID_CARD]`），不会保留手机号或证件尾号；
这些标记不用于跨事件稳定关联。若未来确需稳定关联，应在独立版本中使用设备密钥
生成 HMAC 令牌，本阶段不实现。`process()` 对 `MASK` 分支强制使用同一个
规则快照复检，并且只有复检完整、无残留 Finding 且二次脱敏幂等时才暴露
`sanitized_event`；其余情况至少升级为 `REVIEW`。

#### 持久审计、隔离与强制写入 Gate

`SafetyAuditLog.append(event, result, detector)` 不信任单独的
`SafetyAuditRecord`。它先用同一 detector 调用 `validate_result()`，再从已认证结果
生成第二层最小投影。持久记录包含：

- `audit_id`、安全事件引用、UTC 时间、单调 `sequence`；
- `policy_version/digest`、`rule_set_version/digest`、
  `component_version` 和组件注册表摘要；
- `decision`、稳定 `reason_codes`、最高风险、按规则类别统计的命中数；
- 去重字段路径、`redaction_count`；
- 基于可信 `report.event_digest` 和设备密钥计算的 HMAC
  `input_fingerprint`，以及仅在 `ALLOW/MASK` 时存在的安全输出摘要；
- `processing_time_ms`、`previous_record_hash` 和 `record_hash`。

记录不会保存 user ID、原始事件 ID、事件正文、payload、工具参数/结果、命中值、
规则说明或 `decision.reason`。每个事件 ID 都改为稳定的域分离 HMAC 引用，在保留
关联能力的同时避免事件 ID 与用户标识重合时泄漏；JSON Pointer 只保留 schema 控制的
字段名和明确的列表下标，所有动态段均改为 `seg_<HMAC>`，并由同一规则快照再次扫描。
因此“审计记录本身也脱敏”。输入指纹不使用调用方给出的 `source_hash`，两个伪造
相同 `source_hash` 的不同事件仍产生不同指纹。

JSONL 使用 canonical UTF-8 单行、严格 JSON 解析、进程内锁与系统文件锁、
`O_APPEND/O_NOFOLLOW`、文件 `0600`、目录 `0700` 和 `fsync`。记录 HMAC 覆盖
前驱哈希，认证 head sidecar 固定当前序号与链头，可检测完整尾记录截断；若记录已
fsync 而 head 更新前断电，只接受从旧 head 出发的有效 HMAC 扩展并自动前移。
按大小或期限轮转均不重置链；保留清理只删除已关闭的连续旧分段，并先原子写入认证
anchor。anchor 已发布而旧段尚未删完的中断可恢复。中段损坏、尾部回滚、重复键、
NaN、非 canonical 行、软链接、链断裂或错误密钥一律失败关闭。保留后的 `verify()`
只证明从认证 anchor 开始的后缀完整性，不代表被合法清理的历史仍然可验证。
同目录 head 不能抵抗具有写权限的攻击者同时回放一组旧日志与旧 head；该威胁需要把
链头周期性提交到独立 WORM/签名服务。

`SafetyWriteGate` 是普通写入的唯一生产边界，固定顺序为：

1. `SensitiveDetector.process(event)`；
2. `validate_result(event, result)`；
3. 真实 `SafetyAuditLog` 成功追加，并从磁盘严格验链、逐字段确认该记录已持久化；
4. 按最终动作路由。

| 最终动作 | 普通 SQLite / Embedding / 向量 / 证据 / 日志 | REVIEW 隔离区 | 持久安全审计 |
|---|---|---|---|
| `ALLOW` | 内容 sink 仅接收 `ApprovedWrite`；日志仅接收 `SafeLogRecord` | 否 | 是 |
| `MASK` | 内容 sink 仅接收脱敏后的 `ApprovedWrite`；日志仅接收 `SafeLogRecord` | 否 | 是 |
| `REVIEW` | 全部禁止 | AES-256-GCM 密文 | 是 |
| `REJECT` | 全部禁止 | 否 | 是 |

审计追加失败、回执无效、隔离写入失败、能力 MAC/签发者不匹配或任一下游调用失败
都只抛稳定错误码，异常文本不包含待检测输入。`ApprovedWrite` 的 MAC 绑定安全事件、
输出摘要及实际审计记录身份；各内容 sink 由 `GuardedCallbacks` 接收能力对象，不能
接收原始字符串或原始 `MemoryEvent`。普通日志只允许 `SafeLogRecord`，其中不含
事件正文、用户 ID 或命中原文。

`ReviewQuarantineStore` 使用独立的 32 字节设备密钥和 AES-256-GCM。明文只存在于
受控加解密调用内；磁盘元数据仅保存 HMAC 事件引用/输入指纹、安全审计关联、版本、
动作和期限，完整事件位于认证密文中。临时文件 fsync 后才原子发布最终记录，Gate
随后重新读取、认证并核对完整回执。`put()` 会再次调用
`detector.validate_result()`，手工构造的 REVIEW 结果不能直接入隔离区；到期记录即使
尚未由清理任务删除也拒绝解密返回。`cleanup_expired()` 会继续处理其他有效过期记录，
同时以稳定错误报告损坏记录。特权复核读取后不能直接把动作改成 ALLOW；必须把事件
重新送入当前规则/策略的 Gate。

审计和隔离的期限清理应由系统定时任务调用 `enforce_retention()` 与
`cleanup_expired()`；新审计流量也会按期限触发旧分段轮转。没有进程运行时无法自行
删除磁盘文件，因此期限配置不能替代操作系统调度。持久目录必须位于服务账户控制的
可信父目录中；实现会拒绝路径层级中的软链接/Windows junction，但仅靠路径检查不能
替代服务账户权限和目录 fd 隔离。

银河麒麟部署用 POSIX mode 和 `O_NOFOLLOW` 强制本地权限。Windows 开发环境中的
`chmod` 不能替代 NTFS ACL；若在 Windows 生产部署，必须另行配置服务账户专用 ACL、
拒绝重解析点并完成等效验收。

FastAPI 的请求验证错误只返回白名单化的错误类型和字段位置，不返回 `input`、
`msg`、`ctx` 或请求正文；麒麟 Embedding 封装同样只抛稳定错误码，不拼接输入片段
或 SDK 后端消息。

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
