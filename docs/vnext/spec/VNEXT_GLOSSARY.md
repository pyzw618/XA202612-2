# MemoryHub vNext 术语与兼容映射

版本：`vnext/v1`

冻结任务：`S0-01`
日期：2026-08-22

## 术语维度

vNext 不再使用一个 `level` 字段同时表示生命周期和类型。以下维度必须独立传输、存储和评测：

| 维度 | 枚举 | 含义 |
|---|---|---|
| Lifecycle Layer | `WORKING` / `EPISODE` / `LONG_TERM` | 当前状态、可恢复任务过程、跨任务长期记忆 |
| Memory Type | `PREFERENCE` / `SEMANTIC` / `PROCEDURAL` / `EPISODIC` | 记住的内容类型 |
| Formation Status | `RAW_EVENT` / `WORKING_STATE` / `EPISODE_CHECKPOINT` / `CANDIDATE` / `CONSOLIDATED_MEMORY` | 信息形成链路阶段 |
| Evolution Status | `ACTIVE` / `DORMANT` / `SUPERSEDED` / `ARCHIVED` / `DELETED` | 长期记忆版本当前状态 |
| Evolution Action | `REINFORCE` / `REVISE` / `SUPERSEDE` / `COEXIST` / `REVIEW` | 对版本执行的演化决策，不是状态 |
| Activation | `RECALLED` / `SELECTED` / `IN_CONTEXT` / `USED` | 本次查询的使用进度，不改变 Layer |
| Scope | `TASK` / `PROJECT` / `APPLICATION` / `DOMAIN` / `GLOBAL` / `SESSION` | 作用域；长期记忆优先级为 TASK > PROJECT > APPLICATION > DOMAIN > GLOBAL，SESSION 仅用于 Working/Episode |
| Retrieval Intent | `CURRENT_STATE` / `TASK_HISTORY` / `PREFERENCE` / `SEMANTIC_FACT` / `PROCEDURE` / `EXPERIENCE` / `MIXED` | 统一 Router 的七类意图 |

## 旧值兼容映射

旧入口仍可接收旧值，但只能在兼容层转换为 vNext 枚举，生产域模型不得继续以 `level` 代替上述维度。

| 旧字段/值 | vNext | 说明 |
|---|---|---|
| `level=short` | `layer=WORKING` | 当前任务状态；不等价于短 TTL |
| `level=mid` | `layer=EPISODE` | 可恢复任务过程；不等价于摘要 |
| `level=long` | `layer=LONG_TERM` | 跨任务记忆 |
| `preference`、`*_preference` | `memory_type=PREFERENCE` | 偏好不等价于安全策略 |
| `knowledge_type=fact` | `memory_type=SEMANTIC` | 结构化事实 |
| `knowledge_type=workflow/template` | `memory_type=PROCEDURAL` | 可复用流程或模板 |
| `knowledge_type=case` | `memory_type=EPISODIC` | 历史案例/经验 |
| `status=active` | `evolution_status=ACTIVE` | 默认可读，仍需 Policy/Scope 校验 |
| `status=archived` | `evolution_status=ARCHIVED` | 非默认结果 |
| `status=deleted` | `evolution_status=DELETED` | 读取阻断并清理 Projection |

未能可靠推断类型、Scope 或 Evidence 的旧数据必须进入 `REVIEW`/迁移复核，不得静默成为 `LONG_TERM + ACTIVE + GLOBAL`。

## 代码来源

- 枚举和映射：`memoryhub/domain/contracts.py`
- 后续完整 Pydantic 对象：S0-03 扩展同一 `vnext/v1` 契约
- 旧接口适配：保持在 adapter/interface 层，禁止领域层依赖旧 `MemoryLevel`
