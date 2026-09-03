# MemoryHub vNext Authority 与 Canonical Write

## Long-Term Authority Facade

`LongTermEnvelope` 是 Preference、Semantic FACT、Procedural 和 Episodic
长期记忆的统一读取契约。`LongTermAuthorityFacade` 负责：

- 校验 `tenant_id/user_id`、`content_version` 和同一 Scope/type/normalized key
  版本链的 ACTIVE 唯一性；
- 默认只返回 `evolution_status=ACTIVE`；`SUPERSEDED`、`DELETED`、`ARCHIVED`
  只能通过显式 `include_inactive=True` 读取；
- 将 vNext 类型和 Scope 映射到现有 Preference/Knowledge API，保留旧 API 的
  `preference`、`knowledge` 和 `fact` 兼容形状。

`AuthorityRepository` 使用现有 Preference/Knowledge 表作为兼容 Authority
适配器。新增的 `tenant_id` 和 `extra_payload.vnext_authority` 是 additive
字段；不创建第二套长期业务事实表。没有 vNext tenant metadata 的旧行不会
通过 tenant-scoped vNext Authority 读取路径返回。

## Canonical Write 顺序

```text
MemoryEventContract
  → EventGateway（identity / Scope / Policy / idempotency / Event）
  → Working Patch/CAS（可选）
  → Episode append + checkpoint（可选）
  → ExtractionTaskRepository（异步 Reflection 任务）
  → LongTermAuthorityFacade
  → MemoryWriteService / DomainMemoryWriter
       → Preference/Knowledge business row
       → MemoryEvidence + MemoryLineage + Projection Outbox
```

`CanonicalWriteService` 对非 `COMMITTED` 的 EventGateway 结果停止后续写入；
重复事件返回 `IDEMPOTENT`，不会重复创建 Reflection 任务或 Evidence。长期
提交复用 `DomainMemoryWriter` 的事务边界，Evidence 只保存受治理的引用/摘要，
Lineage、Evidence 和 Outbox 同时携带 tenant 与 content version。向量、BM25
和缓存仍是可重建 Projection，不属于 Authority。
