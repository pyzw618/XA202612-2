# MemoryHub vNext API 契约

版本：`vnext/v1`

冻结任务：`S0-04`
实现：`memoryhub/adapter/vnext_schemas.py`

## 统一原则

REST、MCP、CLI 和 SDK 都是协议适配器，统一调用业务服务；本文件和
`memoryhub/adapter/vnext_schemas.py` 只定义 DTO，不实现记忆、检索或 Forget
算法。旧入口可继续返回旧响应形状，但必须由兼容层适配同一个 vNext 服务。

每个请求有 `api_version=vnext/v1` 和 `request_id`；写入/Forget 还需要
`idempotency_key`。响应有 `trace_id`，便于把事件、Authority、Projection、
Retrieval 和 Context 串起来。

## 接口模型

| 能力 | 请求 | 响应 | 业务语义 |
|---|---|---|---|
| write | `WriteEventRequest` | `WriteEventResponse` | 事件进入 Policy、幂等和 Canonical Write；长期 Reflection 可以异步 |
| retrieve | `MemoryRetrievalRequest` | `MemoryRetrievalResponse` | Router → Planner → Recall → Rerank → Scope/Authority → Context |
| resume | `ResumeTaskRequest` | `ResumeTaskResponse` | 恢复 Working/Episode，并报告 stale resource 与复验要求 |
| forget | `ForgetRequest` | `ForgetResponse` | dry-run 预览或先阻断 Authority 再清理 Projection、验证残留 |
| diagnostic | `DiagnosticRequest` | `DiagnosticResponse` | 管理权限下查 Memory/Evidence/Lineage/Trace/Projection/Candidate |

### Write

`WriteEventRequest.events` 是 `MemoryEventContract` 列表；Policy `DROP` 只返回
治理状态，不回显敏感正文。`WriteEventResponse.formation_status` 区分
`EVENT_ACCEPTED`、`WORKING_UPDATED`、`CHECKPOINT_CREATED` 和
`REFLECTION_PENDING`，调用方不能把 HTTP 成功误解为长期记忆已固化。

### Retrieve

查询可以为空，用于 `CURRENT_STATE`/任务恢复；输入还可以带 task、session、
当前目标/步骤、实体、硬约束、Scope、Intent hint、token budget、consistency
和分页游标。`AUTHORITY_CHECKED` 用于刚写入、Forget 验证和高风险事实；
`EVENTUAL` 允许 Projection 延迟，但响应必须暴露 `degraded_channels`、
`completeness` 和 warnings。

`selected_memories` 是结构化结果，包含 Layer/Type/Scope/version/分数分解/来源；
调用方不得绕过 `context` 再拼接原始候选。Context 必须能表达当前状态、约束、
冲突说明、来源 ID 和预算裁剪原因。

### Resume

恢复响应必须同时返回 Snapshot、`stale_resources`、`required_revalidation`
和 `resume_token`。续作请求携带 token 并由服务执行乐观锁，防止两个设备同时
恢复覆盖。

### Forget

请求必须显式指定 memory ID、normalized key、Scope 或 instruction 之一；
执行模式必须 `confirm=true`，默认 `dry_run=true`。Scope 需要同时给出
`scope_level`，Global/批量授权由应用服务额外校验。响应区分 Authority、Projection
和 Verification 状态，并报告 `residual_retrieval_count`；异步清理未完成时不能
宣称 `VERIFIED`。

### Diagnostic

管理接口和用户检索接口权限分离。默认 `include_sensitive=false`，结果脱敏且
包含 actor/reason/idempotency/audit 的应用服务记录；DTO 本身不授权调用方。

## 错误码

`INVALID_REQUEST`、`UNAUTHORIZED`、`POLICY_REJECTED`、`VERSION_CONFLICT`、
`IDEMPOTENCY_CONFLICT`、`NOT_FOUND`、`PARTIAL_RESULT`、
`SERVICE_UNAVAILABLE`、`INTERNAL_ERROR`。错误响应包含稳定 code、可安全显示的
message、retryable 和 trace_id；不得回显敏感正文或底层异常。

## 兼容响应

`LegacySearchCompatibilityResponse.from_vnext()` 只投影旧客户端需要的
`results/preferences/knowledge/facts/latency_ms/total_count` 字段，并保留
`trace_id`。它不实现排序、过滤、Scope 或 Context 算法。旧 `level=short/mid/long`
只能在 adapter 层映射到 vNext Layer，禁止进入新的领域契约。

## 版本、分页和降级

- `schema_version` 与业务 `content_version` 分离；结果至少返回
  `memory_id + content_version`。
- 请求分页使用不透明 `cursor` 和受限 `page_size`；服务负责校验 cursor 所属
  tenant/user/查询版本。
- 部分通道超时可以少返回，但不得越权、返回 Candidate、DELETED、SUPERSEDED
  或 Forget 已阻断内容。
- 改变状态、Scope 优先级、错误语义或字段含义时必须新增契约版本与迁移/双读/
  回滚证据。
