# MemoryHub vNext Cross-session Decisions

只追加会影响后续任务的决策，不删除历史；废弃决策用新条目明确 supersede。

## DEC-20260822-001

- Date: 2026-08-22
- Task: Bootstrap / S0-01
- Status: ACTIVE
- Decision: 连续性文件缺失时按主提示词模板初始化；保留现有 `docs/last_improve/` 未跟踪方案文件，不重置或覆盖。
- Evidence/reason: Git status 显示仅 `docs/last_improve/` 未跟踪；仓库无适用 `AGENTS.md`，方案明确要求首次会话初始化 `codex_execution/`。
- Affected files/contracts: `docs/last_improve/codex_execution/*`
- Alternatives considered: 忽略状态文件继续开发；被拒绝，因为跨会话验收依赖持久化状态。
- Compatibility/migration impact: 不改变生产代码或现有数据。
- Rollback: 删除本次新增的连续性文件即可恢复到初始化前状态；不执行删除操作。
- Supersedes: None

## DEC-20260822-002

- Date: 2026-08-22
- Task: S0-01
- Status: ACTIVE
- Decision: vNext 使用独立的 Lifecycle Layer、Memory Type、Formation Status、Evolution Status、Evolution Action、Activation、Scope 和七类 Retrieval Intent；旧 `short/mid/long` 只允许通过兼容映射进入 Layer。
- Evidence/reason: 改进方案明确要求 Layer/Type/Status/Activation 正交；现有 `MemoryLevel` 同时被旧 API/测试使用，直接重命名会破坏兼容性。
- Affected files/contracts: `memoryhub/domain/contracts.py`, `docs/spec/VNEXT_GLOSSARY.md`, 后续 S0-03/S0-04 vNext 契约
- Alternatives considered: 直接修改现有 `MemoryLevel`；被拒绝，因为会破坏现有接口且无法表达 Candidate/Activation/Scope。
- Compatibility/migration impact: 旧 adapter 可继续接受 `short/mid/long`，迁移层显式转换；未知/`pending` 状态不自动升级为 ACTIVE。
- Rollback: 关闭 vNext adapter/Feature Flag，保留旧 `memoryhub.adapter.schemas` 路径；新领域模块可独立回退。
- Supersedes: None

## DEC-20260822-003

- Date: 2026-08-22
- Task: S0-02
- Status: ACTIVE
- Decision: Authority Store 是唯一业务事实源；Vector/BM25/Cache 是可删除可重建 Projection；所有写入和检索入口分别委托 Canonical Write/Retrieval Service；适配层不得复制算法或直写长期表/索引。
- Evidence/reason: 当前仓库已有 DomainMemoryWriter 的 Evidence/Lineage/Outbox 写链和 Hybrid/Milvus 检索实现，但 REST fallback、旧表和兼容 DTO 仍并存；ADR 将迁移事实与目标边界分开。
- Affected files/contracts: `docs/design/adr/ADR-vnext-memory-architecture.md`, 后续 S0-03～S5-10 代码和接口
- Alternatives considered: Vector 作为 Authority、各入口各自写入、Reflection 直接写长期表、大爆炸替换；均会破坏版本、租户、Forget 或回滚证据。
- Compatibility/migration impact: legacy/shadow/dual-read/canary/vnext 逐级切换；回滚切读路径，不回滚已正确提交的 Authority 数据。
- Rollback: 使用旧兼容读取/Formation 开关；Projection 由 Authority 重建并切换别名。
- Supersedes: None

## DEC-20260822-004

- Date: 2026-08-22
- Task: S0-03
- Status: ACTIVE
- Decision: vNext 数据对象统一使用 `vnext/v1`、独立 `schema_version/content_version`、tenant/user 和 Policy/retention/sensitivity/actor/time 治理字段；Evidence 只保存 `content_ref`，Candidate 明确是普通检索隔离的 staging。
- Evidence/reason: S0-03 fixture 与 58 项契约/旧 ingestion/safety 回归通过；改进方案要求 Schema、正文治理和 Candidate 默认隔离。
- Affected files/contracts: `memoryhub/domain/contracts.py`, `docs/spec/VNEXT_DATA_CONTRACT.md`, `tests/fixtures/vnext/minimal_contracts.json`
- Alternatives considered: 复用旧 `MemoryEvent`/`MemoryLevel` 或在各模块复制 DTO；被拒绝，因为旧对象缺少 vNext 生命周期、版本、Scope 和治理组合，复制会产生漂移。
- Compatibility/migration impact: 旧 adapter DTO 保持不变；后续 S0-04 负责显式适配到 vnext/v1。
- Rollback: 关闭 vNext DTO adapter，继续使用旧 `adapter.schemas`；新契约文件不改变已有数据库。
- Supersedes: None

## DEC-20260822-005

- Date: 2026-08-22
- Task: S0-04
- Status: ACTIVE
- Decision: vnext/v1 API 统一使用 request_id/trace_id；写入与 Forget 使用 idempotency_key；Forget 默认 dry-run 且执行必须 confirm；Retrieval 支持 EVENTUAL/AUTHORITY_CHECKED 和显式部分降级；旧 SearchResponse 只能由兼容形状适配。
- Evidence/reason: API 契约测试 38 项通过；现有 REST/MCP/CLI/SDK 仍透传旧 DTO，必须先冻结统一边界再在 S1/S3 收敛入口。
- Affected files/contracts: `memoryhub/adapter/vnext_schemas.py`, `docs/spec/VNEXT_INTERFACE.md`, 后续 REST/MCP/CLI/SDK adapters
- Alternatives considered: 让各入口自行拼 Context/处理 Forget 或复制搜索算法；被拒绝，因为会违反 S0-02 Authority 单写和统一 Retrieval 决策。
- Compatibility/migration impact: `LegacySearchCompatibilityResponse` 保留旧字段；vNext 结果额外带 content_version、trace_id 和可解释降级信息。
- Rollback: 兼容入口继续返回旧 shape；关闭 vNext feature flag，不改变既有业务数据。
- Supersedes: None

## DEC-20260822-006

- Date: 2026-08-22
- Task: S0-05
- Status: ACTIVE
- Decision: S0-05 只提供 SQLite read-only dry-run；不 bootstrap、不建表、不写 Authority、不删除旧数据。缺 tenant/Scope/Evidence 的记录进入 REVIEW，deleted 记录只规划为 Tombstone；实际 apply、备份、checkpoint 和 Projection 重建放到 S5-06。
- Evidence/reason: 现有数据库初始化是 `create_all + additive _ensure_compatible_schema`，默认数据库当前不存在；迁移测试与 CLI dry-run 通过并生成显式 missing-database 报告。
- Affected files/contracts: `scripts/migrate_vnext.py`, `docs/spec/VNEXT_MIGRATION.md`, `evaluation/results/vnext_migration/dry_run.json`, S5-06
- Alternatives considered: 在 dry-run 中调用 `Database.init_schema()` 或直接写迁移表；被拒绝，因为预演会产生副作用且无法证明原库未变。
- Compatibility/migration impact: 旧表保持不变；报告记录稳定 hash/tenant/scope/review，后续 apply 必须以报告和备份为输入。
- Rollback: S0-05 无 apply，无需数据回滚；S5-06 使用 checkpoint/兼容读/索引别名回滚，禁止直接删除旧表。
- Supersedes: None

## DEC-20260822-007

- Date: 2026-08-22
- Task: S0-06
- Status: ACTIVE
- Decision: vNext rollout 只允许 `legacy/shadow/dual-read/canary/vnext`；默认 `legacy`；canary 百分比只允许 5/25/50/100；生产必须 Policy required、Authority single writer，禁止 policy bypass；legacy read fallback 仅作为回滚窗口。
- Evidence/reason: 35 个模式/生产 gate 测试和 `config.example.yaml` load 通过；现有 RuntimeConfig 仅覆盖 provider/fallback，不足以表达 vNext 切流。
- Affected files/contracts: `memoryhub/config.py`, `config.example.yaml`, 后续 S2/S5 rollout 和服务组装
- Alternatives considered: 用环境变量散落控制各模块、生产静默 fallback、允许双 Authority writer；均会导致切流不可审计或安全门禁失效。
- Compatibility/migration impact: legacy 默认保持旧行为；新模式由显式配置选择，rollback 保留旧读，不改变 Authority。
- Rollback: 设置 `vnext.mode=legacy` 或关闭 vNext feature flag；保留已提交 Authority 数据。
- Supersedes: None

## DEC-20260822-008

- Date: 2026-08-22
- Task: S0-07
- Status: ACTIVE
- Decision: 基线 runner 先尝试现有 Hybrid/FAISS 评测；当本地可选依赖缺失时，只允许降级到明确标注的纯 Python vector-only baseline，Hybrid 指标保留为失败证据，不得冒充通过。
- Evidence/reason: 当前环境缺少 `rank-bm25` 和 `faiss-cpu`；纯 Python 余弦排序可提供可重复的测试数据指标和延迟，同时不修改生产检索实现。
- Affected files/contracts: `evaluation/run_vnext_baseline.py`, `evaluation/results/vnext_baseline/baseline.json`, 后续 S5 benchmark runner
- Alternatives considered: 安装外部依赖或把缺失依赖当作零指标；前者超出当前本地无授权范围，后者会污染基线结论，均不采用。
- Compatibility/migration impact: 仅影响评测报告；生产 Authority、Projection 和 Retrieval 代码不变。具备依赖的环境可复跑现有 Hybrid runner 对照。
- Rollback: 删除 runner 新增的 fallback 分支并恢复仅使用现有评测入口；不删除当前证据文件。
- Supersedes: None

## DEC-20260822-009

- Date: 2026-08-22
- Task: S1-01
- Status: ACTIVE
- Decision: S1-01 采用 additive/idempotent SQLite schema：新表由 `Base.metadata.create_all()` 创建，既有表由兼容迁移补列/索引；新 vNext 表 tenant/user 必填，旧扩展列在兼容窗口允许 NULL；不删除 legacy 表/列。
- Evidence/reason: 任务方案要求 short/mid 不直接升级为 Working/Episode，且迁移可重复；测试发现重复 init 需要先 dispose 旧 engine 才能在 Windows 正确释放 SQLite 锁。
- Affected files/contracts: `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `docs/spec/VNEXT_STORAGE_SCHEMA.md`, S1-02 repositories and S4/S5 migrations
- Alternatives considered: 直接重命名旧表、物理合表、不可逆 ALTER/drop；均会破坏兼容读、回滚和旧数据证据，拒绝。
- Compatibility/migration impact: 新表独立承载 Working/Episode/Candidate/Activation/Retrieval/Idempotency；Event/Evidence/Lineage/Outbox 增量增加 governance/version/projection 字段。
- Rollback: 设置 `vnext.mode=legacy`，保留新增表供诊断；不删除新表，后续 apply/回滚需另行备份演练。
- Supersedes: None

## DEC-20260822-010

- Date: 2026-08-22
- Task: S1-02
- Status: ACTIVE
- Decision: vNext repositories return detached immutable views and own tenant-scoped transaction invariants；CAS/episode seq/status transitions/dedup/activation uniqueness are storage responsibilities；Policy、formation、promotion and retrieval ranking remain application-service responsibilities。
- Evidence/reason: 25 repository/storage/contract/interface tests passed；stale Working and Episode writes fail explicitly；Evidence stores `content_ref` only；Candidate is not exposed as ordinary retrieval data。
- Affected files/contracts: `memoryhub/storage/vnext_repositories.py`, `tests/test_vnext_repositories.py`, S1-03 Event Gateway and S2/S3 services
- Alternatives considered: return mutable ORM rows to callers、implement transitions in each API adapter、or use global unscoped queries；rejected because they weaken transaction boundaries and tenant isolation。
- Compatibility/migration impact: legacy metadata repositories remain unchanged；vNext repositories target only S1-01 tables and extended metadata columns。
- Rollback: disable vNext repository callers via Feature Flag；leave committed Authority rows and use existing legacy repositories during compatibility window。
- Supersedes: None

## DEC-20260822-011

- Date: 2026-08-22
- Task: Execution continuity model
- Status: ACTIVE
- Decision: 将执行计划拆为 B01～B18；单个会话只授权一个批次，批次完成后硬停止，不在同一会话领取下一批次。
- Evidence/reason: 旧提示词同时包含“一次一个主任务”和“有执行空间就领取下一个 READY 任务”，导致单次会话从 S0 连续推进到 S1。批次边界需要成为独立、显式且可持久化的授权单元。
- Affected files/contracts: `docs/last_improve/MemoryHub vNext：Codex 跨会话执行提示词.md`, `docs/last_improve/codex_batches/`, `docs/last_improve/codex_execution/BATCH_BOARD.md`, `STATE.md`
- Alternatives considered: 每个正式任务一个会话，粒度过细且增加交接成本；每个阶段一个会话，S1～S5 工作量过大且难以稳定验收；继续使用全局 `/goal`，无法保证会话边界。
- Compatibility/migration impact: 现有有效 DONE 任务和证据全部保留；当前现场映射为 B03，不重做 B01/B02。后续状态恢复先看批次，再看批次内任务。
- Rollback: 恢复旧版总控提示词并删除批次提示词/BATCH_BOARD；不会影响生产代码或既有任务证据。
- Supersedes: 旧提示词中允许同一会话继续领取下一 READY 任务的执行规则。

## DEC-20260822-012

- Date: 2026-08-22
- Task: Batch Git governance
- Status: ACTIVE
- Decision: 每个完整验收的批次只创建一次本地 Git 提交；批次未完成或被阻断时不提交；提交后不在同一会话进入下一批次。
- Evidence/reason: 让代码历史、批次验收和跨会话交接形成一一对应关系，同时避免半成品提交及下一批次改动混入。
- Affected files/contracts: 总控提示词、B01～B18 批次提示词、`BATCH_BOARD.md`、`STATE.md`
- Alternatives considered: 每个正式任务提交一次会产生过多碎片；会话结束无条件提交会固化半成品；批次完成后再回填 SHA 会要求第二次提交，均不采用。
- Compatibility/migration impact: B01/B02 已依据文件归属追溯拆成独立提交 `a502f9a`/`1b84af1`；B03 继续保持未提交，完整验收后创建自己的唯一提交。提交使用 `Batch-ID: Bxx` trailer，文件内用 `SELF` 引用自身提交，避免递归回填 SHA。
- Rollback: 后续批次可停止自动提交并恢复为仅记录工作区状态；不重写已经产生的提交历史。
- Supersedes: None

## DEC-20260822-013

- Date: 2026-08-22
- Task: S1-03
- Status: ACTIVE
- Decision: Event Gateway 只提交 Policy 返回的治理事件；REVIEW/DROP/未净化 MASK fail-closed 且不创建 Event/IdempotencyRecord。幂等键按 `(tenant_id, idempotency_key)`，Event ID 按其全局主键约束检查；唯一键竞争在事务回滚后重读，统一返回 IDEMPOTENT/CONFLICT。
- Evidence/reason: S1-03 定向 11 tests passed；并发重复提交产生 1 个 Event/IdempotencyRecord，7 次重试为 IDEMPOTENT；敏感 payload 未进入拒绝路径的存储记录；既有 Evidence/Frequency 在重复提交后保持不变。数据库约束与 Gateway 的检查范围必须一致，避免并发或跨租户 Event ID 竞争泄漏 IntegrityError。
- Affected files/contracts: `memoryhub/application/event_gateway.py`, `tests/test_vnext_event_gateway.py`, `docs/spec/VNEXT_EVENT_GATEWAY.md`
- Alternatives considered: 只依赖读前检查；被拒绝，因为并发提交可同时通过检查并在唯一键处失败。允许 MASK 原 payload 直接提交；被拒绝，因为会把未净化正文写入 Authority。
- Compatibility/migration impact: 仅影响 vNext Event Gateway；legacy EventIngestionService 保持不变。拒绝结果仍为安全元数据，不保存正文。
- Rollback: 关闭 vNext Gateway/Feature Flag，保留已提交 Authority rows；不删除新表。
- Supersedes: None

## DEC-20260822-014

- Date: 2026-08-22
- Task: S1-07/S1-08
- Status: ACTIVE
- Decision: Long-Term Authority uses the existing Preference/Knowledge rows as the compatibility Authority adapter; vNext binds tenant identity and the complete LongTermEnvelope in additive governed metadata, while Canonical Write delegates long-term persistence to MemoryWriteService/DomainMemoryWriter.
- Evidence/reason: The accepted ADR forbids a second Authority write store and requires reuse of the existing Evidence/Lineage/Outbox write chain. B05 focused tests verify tenant isolation, ACTIVE-chain uniqueness, default inactive filtering, and one transaction-produced business/Evidence/Lineage/Outbox set.
- Affected files/contracts: `memoryhub/domain/long_term.py`, `memoryhub/storage/authority_repository.py`, `memoryhub/application/canonical_write.py`, additive legacy columns and Domain Writer metadata propagation.
- Alternatives considered: create a separate `long_term_authority` table or let each adapter write legacy tables directly; rejected because either creates dual Authority or bypasses the canonical writer.
- Compatibility/migration impact: legacy rows remain readable by existing APIs; rows without vNext metadata remain compatibility-only and are not returned by tenant-scoped vNext Authority reads.
- Rollback: disable vNext callers/flag and continue legacy adapters; additive columns/metadata are inert for legacy writes.
- Supersedes: None

## DEC-20260822-015

- Date: 2026-08-22
- Task: B05 acceptance
- Status: ACTIVE
- Decision: Accept S1-07/S1-08 after focused, affected, safety, contract, and static validation; keep B06 READY and stop this session at the B05 commit boundary.
- Evidence/reason: Authority-focused validation passed 4 tests; affected storage/writer/outbox regressions passed 38 tests; safety/write-bypass/contract/interface regressions passed 100 tests; duplicate canonical events remained idempotent and the Authority business/Evidence/Lineage/Outbox set remained transaction-consistent.
- Affected files/contracts: B05 Authority Facade, Authority adapter, Canonical Write Service, additive metadata propagation, B05 specification/tests, and continuity artifacts.
- Alternatives considered: continue into REST/MCP/CLI/SDK entrypoint convergence; rejected because S1-09 is outside B05 authorization.
- Compatibility/migration impact: no second Authority store introduced; legacy Preference/Knowledge storage remains the compatibility adapter and existing APIs remain available.
- Rollback: disable vNext callers/flag and use legacy adapters; retain additive columns and B05 artifacts for diagnosis.
- Supersedes: None
