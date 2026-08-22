# MemoryHub vNext 数据契约

版本：`vnext/v1`

冻结任务：`S0-03`
实现：`memoryhub/domain/contracts.py`

## 通用治理字段

除局部操作对象 `WorkingPatchOperation` 外，所有 vNext 对象都包含：

```text
tenant_id / user_id
schema_version = vnext/v1
content_version >= 1
policy_version
retention_class / sensitivity_level
created_by / updated_by
created_at / updated_at
```

`schema_version` 表示对象结构如何解析；`content_version` 表示业务内容
变更。迁移只提升 Schema 版本时不得伪造一次记忆演化。

所有对象默认 `extra=forbid`，未知字段不能静默进入 Authority。敏感正文
不由 Evidence 复制保存，Evidence 使用 `content_ref` 指向已通过 Policy 的
摘要、哈希或受控对象地址。

## 核心对象

### `MemoryEventContract`

Canonical Write 的输入事件。必须有事件身份、来源、任务/会话、发生时间、
Policy 动作、来源哈希、幂等键和 Trace ID。`DROP` 事件只能保留治理结果，
调用方不得把被拒正文放入 payload。

### `WorkingPatch` / `WorkingSnapshot`

Working 通过字段级 `add/replace/remove` Patch 更新，Patch 携带
`base_version`、事件引用和原因；Snapshot 保存可恢复的目标、当前步骤、
待办、已完成步骤和约束。过期版本由后续 CAS/语义合并任务处理，不能静默
覆盖。

### `EpisodeEventContract` / `EpisodeSnapshot`

Episode 使用 `episode_id + seq_no` 的追加事件和 Snapshot。Snapshot 记录
状态、阶段、目标、步骤、约束、事件水位及 `stale_resources`/
`required_revalidation`，支持跨会话恢复和资源复验。

### `Candidate`

Long-Term 之前的 staging 对象，固定 `formation_status=CANDIDATE`，状态为
`ACCUMULATING/CONFIRMED/REJECTED/REVIEW`。普通 Retrieval 不得把 Candidate
当作 Long-Term 结果；它必须保留归一键、Scope、证据引用和独立 Episode 引用。

### `LongTermEnvelope`

正式长期记忆的公共 Envelope。固定 `layer=LONG_TERM`，包含 Type、内容、
Scope、Evolution Status、有效期、Projection 版本、Evidence 引用和可选
Candidate 来源。`DELETED`/`SUPERSEDED` 的默认可读性由后续 Authority/Scope
任务强制校验。

### `Evidence` / `Lineage`

Evidence 记录来源、因果组、可信度和受治理内容引用；同一
`causal_group_id` 不得被重复计算为独立证据。Lineage 记录形成、强化、修订、
替代、并存和删除关系，不能只依靠推断恢复。

### `Activation`

记录检索结果从 `RECALLED` 到 `USED` 的使用过程，包括 Query、Intent、排序、
分数和是否进入 Context。Activation 不改变 Memory 的 Layer 或 Evolution 状态。

## JSON 与兼容

- `tests/fixtures/vnext/minimal_contracts.json` 是最小合法样例；
  `tests/test_vnext_contracts.py` 会逐对象执行 Pydantic 校验和 JSON 往返。
- 旧 `MemoryEvent`、`MemoryLevel` 和旧 Search DTO 保持在 adapter 兼容层；
  它们不得被伪装成 vNext 对象，也不得跳过 Policy、幂等或 Authority 事务。
- 新增字段默认向后兼容；改变枚举、Scope 优先级、状态语义或版本含义时必须
  提升契约版本，并补充迁移、双读和回滚证据。
