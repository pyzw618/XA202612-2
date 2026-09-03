# REST API 参考

> 服务默认监听 `127.0.0.1:8099`（开发配置 `config.yaml` 为 `0.0.0.0:8099`）。
> 交互式文档：`http://<host>:8099/docs`（FastAPI 自动生成，含请求/响应 Schema）。
>
> **数据契约权威**：Pydantic 模型以 `memoryhub/adapter/schemas.py`（标准面）与 `memoryhub/adapter/vnext_schemas.py`（vNext 面）为唯一权威；修改任何字段必须同步更新本文档与对应 Schema。vNext 接口的规范性描述见 [vnext/spec/VNEXT_INTERFACE.md](vnext/spec/VNEXT_INTERFACE.md)。

应用共注册 6 组 Router（`memoryhub/app.py`）：

| Router 模块 | 前缀 | 职责 |
|---|---|---|
| `adapter/vnext_api.py` | `/api/memory/vnext` | vNext 统一入口（写入/检索/上下文/任务/遗忘/反馈/灰度/看板/诊断） |
| `adapter/api.py` | `/api/memory` | 标准接口（事件、检索、偏好、知识、事实、冲突、遗忘、反馈、来源、评测、抽取任务） |
| `adapter/management_api.py` | `/api/memory`（管理面） | 桌面控制台驱动的管理接口 |
| `adapter/memory_v2_api.py` | `/api/memory/v2` | 谱系/证据/审计/投影溯源（只读 + replay） |
| `adapter/agent_api.py` | `/api/agent`、`/api` | Agent 演示适配（step/replay/decision）与根级 health |

租户与用户隔离通过请求头传递（如 `X-MemoryHub-Tenant`），由 EventGateway / ScopeResolver 在写入与检索两侧强制执行。

---

## 1. vNext 统一入口 `/api/memory/vnext`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/events` | 统一写入（canonical write：边界检测 → 工作/情景 → 可重试抽取任务） |
| POST | `/search` | 统一检索（意图路由 → 多通道 → RRF 融合 → 重排 → 预算） |
| POST | `/context` | 上下文装配（返回可直接注入 Agent 提示词的 ContextPayload） |
| POST | `/feedback` | 使用/效用反馈（INCLUDED / REFERENCED / ACTION_INFLUENCED / OUTCOME / CORRECTION） |
| GET | `/tasks/{task_id}` | 抽取任务状态（含 candidate_ids、Candidate 状态、memory_ids） |
| GET | `/tasks/{task_id}/resume` | 任务恢复（跨重启续跑） |
| POST | `/forget` | 自然语言精准遗忘（LLM 意图解析 + 规则兜底 + 语义定位） |
| GET | `/forget` | 遗忘记录列表 |
| GET | `/forget/{record_id}` | 遗忘记录状态 |
| GET | `/rollout` | 灰度状态（当前级别、观察窗口、门禁结果） |
| POST | `/rollout/advance` | 切流推进（5→25→50→100%，零容忍门禁） |
| POST | `/rollout/observe` | 登记观察证据 |
| POST | `/rollout/rollback` | 只读回滚（回 legacy/shadow/dual-read） |
| POST | `/dashboard/{view}` | 看板视图：`explorer` / `evolution` / `retrieval` / `benchmark`（脱敏，管理授权） |
| POST | `/diagnostics` | 诊断（管理授权） |

## 2. 标准接口 `/api/memory`

### 事件与来源

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/events` | 写入 MemoryEvent（`vnext.events_default=true` 时路由到 canonical write） |
| GET | `/events/session/{session_id}` | 按会话查询事件 |
| POST | `/sources/tool_result` | 工具执行结果结构化接入（源适配器） |
| POST | `/sources/behavior` | 用户行为数据接入 |
| POST | `/sources/config` | 手动配置接入（版本化） |

### 检索与上下文

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/search` | 混合检索（vector/keyword/metadata + RRF + rerank + cache） |
| POST | `/context` | 场景上下文装配 |

### 记忆读取

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/preferences` · `/preferences/{memory_id}` · `/preferences/{memory_id}/versions` | 偏好列表 / 详情 / 版本链 |
| GET | `/knowledge` · `/knowledge/{memory_id}` | 知识列表 / 详情 |
| GET | `/facts` · `/facts/{fact_id}` · `/facts/{fact_id}/evidence` · `/facts/conflicts` | 事实读取（**兼容转发**：FACT 已并入 knowledge 单一来源） |
| POST | `/memories/preference` · `/memories/knowledge` | 手动创建记忆 |
| POST | `/facts/propose` | 事实提案（进入知识链） |

### 冲突、反馈与遗忘

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/conflicts` | 冲突列表 |
| POST | `/conflicts/{conflict_id}/resolve` | 冲突消解（决策矩阵 + LLM 辅助） |
| POST | `/feedback` | 记忆反馈 |
| POST | `/forget` · `/forget/preview` | 精准遗忘 / 影响面预览 |
| GET | `/forget/history` | 遗忘审计历史 |
| GET/POST | `/forget/rules` · DELETE `/forget/rules/{rule_id}` | 遗忘类用户规则管理 |

### 运维与评测

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（embedding/vector engine/维度） |
| GET | `/extraction/tasks` · `/extraction/tasks/metrics` | 抽取任务列表 / 指标 |
| POST | `/extraction/tasks/run` · `/extraction/tasks/{task_id}/retry` | 触发 / 重试抽取任务 |
| POST | `/evaluate/{task_name}` · GET `/evaluate/reports` | 内置评测触发 / 报告 |
| POST | `/admin/reconcile` | 投影漂移对账（SQLite ↔ 向量引擎） |

## 3. 管理面 `/api/memory`（management_api）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/events` | 事件管理列表 |
| GET | `/system/config` · `/system/status` | 系统配置 / 运行状态 |
| PUT | `/system/llm` | 运行时更新 LLM 配置（桌面控制台设置页） |
| GET | `/short-term` · `/mid-term` | 短期 / 中期记忆查看 |
| GET | `/memories/health` | 记忆健康度看板 |
| PATCH | `/memories/{memory_id}/status` · POST `/memories/status` | 状态流转（单条 / 批量） |
| DELETE | `/memories/{memory_id}` · POST `/memories/delete` | 软删除 / 批量删除 |
| PUT | `/{memory_type}/{memory_id}` | 记忆编辑（含知识版本历史） |
| GET | `/lifecycle/settings` | 生命周期阈值展示 |
| POST | `/lifecycle/check` · `/lifecycle/consolidate` · `/lifecycle/auto-forget` | 手动触发生命周期检查 / 汇总 / 自动遗忘 |
| GET | `/safety/audit-logs` · `/safety/audit-logs/verify` | 审计日志查询 / 哈希链校验 |
| GET | `/safety/quarantine` · `/safety/quarantine/{review_id}` | 隔离区列表 / 详情 |
| POST | `/safety/quarantine/{review_id}/release` · DELETE 同路径 | 隔离放行 / 删除 |

安全模块未启用时返回稳定错误码（如 `safety.audit_disabled`、`safety.quarantine_disabled`）。

## 4. 溯源只读 `/api/memory/v2`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/search` | 带溯源信息的检索（支持 project 过滤） |
| GET | `/memories/{memory_id}/lineage` | 谱系（来源事件链） |
| GET | `/memories/{memory_id}/evidence` | 证据链 |
| GET | `/memories/{memory_id}/audit` | 审计记录 |
| GET | `/projections` · POST `/projections/replay` | 投影状态 / 重放 |

响应按 user scope 隔离并脱敏。

## 5. Agent 演示适配 `/api/agent`、`/api`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 根级健康检查 |
| POST | `/api/agent/step` | 模拟器单步演示 |
| POST | `/api/agent/replay` | 会话回放 |
| POST | `/api/agent/actions/{action_id}/decision` | 动作决策 |
| DELETE | `/api/agent/demo-data` | 清空演示数据 |
| DELETE | `/api/agent/preferences` | 清空演示偏好 |

---

## 6. 核心数据结构（摘要）

完整定义见 `memoryhub/adapter/schemas.py`；此处仅列协作必备概念：

### MemoryEvent（统一事件模型，Schema 1.1）

```python
class MemoryEvent(BaseModel):
    event_id: str                 # 事件唯一 ID
    source_type: SourceType       # TOOL_RESULT / USER_BEHAVIOR / MANUAL_CONFIG
    event_type: str               # 来源内具体动作（开放字符串）
    user_id: str; session_id: str; turn_id: str
    scene: str; task_type: str    # 场景与任务类型（SceneScope 维度）
    occurred_at: str              # UTC，YYYY-MM-MMTHH:MM:SSZ
    text: str                     # 抽取摘要文本
    payload: dict                 # 来源特有结构化内容
    tool_calls: list[ToolCallResult]
    schema_version: Literal["1.0", "1.1"]
    source_hash: str              # canonical SHA-256（幂等去重）
    redactions: list[str]         # 脱敏记录
    quality: EventQuality         # 质量评分
```

### 其他关键模型

| 模型 | 说明 |
|---|---|
| `SceneScope` | `scene`（粗）/ `task_type`（细，`.` 分层）/ `app`（来源） |
| `PreferenceMemory` | 7 类 preference_type（含 TOOL_PREFERENCE），版本链 version/parent_id/root_id |
| `KnowledgeMemory` | `KnowledgeType`：workflow / case / template / fact（事实为知识子类型） |
| `MemoryLevel` | short / mid / long（分层流转维度） |
| `Evidence` | 证据链（event 关联、weight、冲突 decision） |
| `SearchRequest/SearchResponse` | 检索契约（top_k、memory_types、min_confidence、scope 过滤） |

### 错误模型

错误响应为 JSON，携带**稳定错误码**（点分命名，如 `embedding.unavailable`、`embedding.timeout`、`embedding.dimension_mismatch`、`rollout.gate_failed`、`rollout.service_unavailable`、`safety.audit_disabled`），客户端应按错误码而非文案分支。
