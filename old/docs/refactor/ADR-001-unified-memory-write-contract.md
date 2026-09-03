# ADR-001: 统一记忆写入契约与权威关系表

- **状态**：已接受
- **日期**：2026-08-15
- **关联路线图**：`MAIN_TO_REMEM_REFACTOR_ROADMAP.md` 的架构冻结与统一数据契约工作包

## 背景

Preference、Knowledge 与 Fact 的证据、版本和索引同步状态此前分散在领域表、JSON 字段和临时补偿路径中。后续要将生产写入收口到 Domain Writer，因此必须先提供三类记忆共用、可审计且可迁移的数据契约。

## 决策

1. 在 `memoryhub.adapter.schemas` 定义：
   - `MemoryDecision`：唯一的内部状态迁移动作集合；
   - `MemoryProvenance`：获批事件、来源哈希以及 Safety audit/review/action 关联；
   - `MemoryWriteReceipt`：Domain Writer 每次状态迁移的统一返回值。
2. 新增 SQLite 权威表：
   - `memory_lineage`：版本及父/根关系；
   - `memory_evidence`：记忆证据；
   - `memory_projection_outbox`：异步 vector、keyword、lookup、cache 投影任务。
3. 新表先由 SQLAlchemy metadata 创建，并在 `Database._ensure_compatible_schema()` 显式补齐查询索引；现有 JSON evidence、旧版本字段和 `pending_index` 暂不删除，仅作为迁移和短期读取兼容来源。
4. `memory_evidence` 对 `(memory_id, event_id, source_hash)` 建唯一约束，保证重复事件来源不会重复累积为证据。

## 后果

- 新的 Domain Writer 能在一个数据库事务中写入业务记忆、lineage、evidence 和 outbox。
- 后续查询、迁移和 API v2 必须优先以新表为权威来源。
- 本 ADR 不改变当前生产写路径；收口 `repo.save()`、Fact 写入和 `pending_index` 将在后续工作包完成。
