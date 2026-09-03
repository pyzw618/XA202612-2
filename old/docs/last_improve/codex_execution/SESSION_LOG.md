# MemoryHub vNext Session Log

历史记录只追加，最新会话写在文件底部。

## Checkpoint 2026-08-25-B17-01 — B17 start reconciliation

- Started: 2026-08-25 +08:00; Ended: in progress.
- Branch/HEAD: `dev-remem` / `330f4d27f04b0729a53a2b63b1ab5747eb6f6dcb` (B16 commit, `Batch-ID: B16`).
- Restored batch/task: B17 READY with no in-progress task; claimed S5-05 as the smallest dependency-satisfied task.
- Initial reconciliation: tracked worktree diff is empty; no applicable `AGENTS.md`; existing untracked evaluation databases/reports and denied pytest temp directories are preserved and excluded.
- Boundary: only S5-05～S5-08 and required continuity/spec/test/report artifacts; S5-09/S5-10/B18 are hard-stop out of scope.
- Task status changes: B17 READY → IN_PROGRESS; S5-05 TODO → IN_PROGRESS.
- Exact next step: implement redacted Agent Usage/Utility Feedback Shadow, then run focused and safety validation before the next checkpoint.

## Session 2026-08-22-01

- Started: 2026-08-22 13:10 +08:00
- Ended: in progress
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: None; first session, selected `S0-01`
- Initial reconciliation: 无 `AGENTS.md`；方案文件存在且未跟踪；连续性目录缺失；现有代码已有旧事件、Safety、MemoryWriteService、DomainMemoryWriter 和 Retrieval 基础。
- Completed changes: 初始化连续性文件；领取 S0-01。
- Files changed: `docs/last_improve/codex_execution/`
- Validation run: Git/status、方案阅读、相关代码/测试基线检查；S0-01 定向测试尚未运行。
- Task status changes: `S0-01 READY/initial → IN_PROGRESS`
- Decisions added: `DEC-20260822-001`
- Blockers: None
- Exact next step: 实现 S0-01 最小术语枚举/旧值映射契约，添加测试并运行定向验证。

## Checkpoint 2026-08-22-02

- Started: 2026-08-22 13:10 +08:00
- Ended: 2026-08-22 13:22 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-01 IN_PROGRESS`
- Initial reconciliation: 状态文件与当前代码一致；无生产文件被覆盖。
- Completed changes: 新增 vNext 正交枚举、旧值映射、术语表和 10 个契约测试。
- Files changed: `memoryhub/domain/__init__.py`, `memoryhub/domain/contracts.py`, `docs/vnext/spec/VNEXT_GLOSSARY.md`, `tests/test_vnext_contracts.py`
- Validation run: `python -m pytest tests/test_vnext_contracts.py -q` → 10 passed；1 个既有 pytest 配置警告。
- Task status changes: `S0-01 IN_PROGRESS`，等待旧契约回归和 lint 后验收。
- Decisions added: `DEC-20260822-002`
- Blockers: None
- Exact next step: 运行 `tests/test_ingestion_schema.py`、`tests/test_memory_write_contract_schema.py` 和 vNext 文件 lint。

## Checkpoint 2026-08-22-03

- Started: 2026-08-22 13:22 +08:00
- Ended: 2026-08-22 13:29 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-01 IN_PROGRESS`
- Initial reconciliation: 新增产物、测试和状态文件存在；未修改旧事件/写入路径。
- Completed changes: 以组合测试完成 S0-01 验收；将任务置为 DONE；领取关键路径最小 READY 任务 S0-02。
- Files changed: `memoryhub/domain/*`, `docs/vnext/spec/VNEXT_GLOSSARY.md`, `tests/test_vnext_contracts.py`, `docs/last_improve/codex_execution/*`
- Validation run: `python -m pytest tests/test_vnext_contracts.py tests/test_ingestion_schema.py -q` → 31 passed；ruff → passed；`test_memory_write_contract_schema.py` 的 2 个 tmp_path 用例因主机 pytest 临时目录权限错误未执行，失败证据已保留。
- Task status changes: `S0-01 IN_PROGRESS → DONE`; `S0-02 TODO → IN_PROGRESS`
- Decisions added: 无新增；沿用 `DEC-20260822-002`
- Blockers: S0-01 无 blocker；主机 pytest tmp_path 权限是后续回归环境问题，尚未阻断 vNext 任务。
- Exact next step: 读取现有模块边界，编写并校验 `docs/vnext/design/ADR-vnext-memory-architecture.md`。

## Checkpoint 2026-08-22-04

- Started: 2026-08-22 13:29 +08:00
- Ended: 2026-08-22 13:37 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-02 IN_PROGRESS`
- Initial reconciliation: 现有 REST fallback、Hybrid/Milvus 检索、MemoryWriteService/DomainMemoryWriter、Outbox 和 legacy 表均已核对。
- Completed changes: 新增架构 ADR 与 3 个可执行边界测试；S0-02 验收通过。
- Files changed: `docs/vnext/design/ADR-vnext-memory-architecture.md`, `tests/test_vnext_architecture_adr.py`, `docs/last_improve/codex_execution/*`
- Validation run: ADR + vNext contract tests → 13 passed；ruff → passed；1 个既有 pytest 配置警告。
- Task status changes: `S0-02 IN_PROGRESS → DONE`; `S0-03 TODO → IN_PROGRESS`
- Decisions added: `DEC-20260822-003`
- Blockers: None
- Exact next step: 读取现有 Pydantic DTO 和数据存储字段，完成 `S0-03` vNext 数据契约。

## Checkpoint 2026-08-22-05

- Started: 2026-08-22 13:37 +08:00
- Ended: 2026-08-22 13:45 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-03 IN_PROGRESS`
- Initial reconciliation: 现有旧 Pydantic DTO 未被修改；新契约独立位于 domain 层。
- Completed changes: 新增 vnext/v1 核心数据对象、JSON fixture、数据契约文档和 extra/version/round-trip 测试；S0-03 验收通过。
- Files changed: `memoryhub/domain/contracts.py`, `memoryhub/domain/__init__.py`, `docs/vnext/spec/VNEXT_DATA_CONTRACT.md`, `tests/fixtures/vnext/minimal_contracts.json`, `tests/test_vnext_contracts.py`
- Validation run: vNext + ingestion + safety → 58 passed；ruff → passed；1 个既有 pytest 配置警告。
- Task status changes: `S0-03 IN_PROGRESS → DONE`; `S0-04 TODO → IN_PROGRESS`
- Decisions added: `DEC-20260822-004`
- Blockers: None
- Exact next step: 读取 REST/MCP/CLI/SDK 当前请求模型，定义 `memoryhub/adapter/vnext_schemas.py` 和接口契约。

## Checkpoint 2026-08-22-06

- Started: 2026-08-22 13:45 +08:00
- Ended: 2026-08-22 13:54 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-04 IN_PROGRESS`
- Initial reconciliation: 旧 `SearchRequest/Response`、Write/Forget DTO、agent-integration REST 映射已读取；旧入口未改动。
- Completed changes: 新增 vnext/v1 API DTO、接口文档、兼容响应适配和契约测试；S0-04 验收通过。
- Files changed: `memoryhub/adapter/vnext_schemas.py`, `docs/vnext/spec/VNEXT_INTERFACE.md`, `tests/test_vnext_interface.py`
- Validation run: vNext interface + contract + ingestion → 38 passed；ruff → passed；1 个既有 pytest 配置警告。
- Task status changes: `S0-04 IN_PROGRESS → DONE`; `S0-05 TODO → IN_PROGRESS`
- Decisions added: `DEC-20260822-005`
- Blockers: None
- Exact next step: 读取 `memoryhub/storage/models.py`、现有迁移/数据库初始化和旧 memory 字段，完成迁移 dry-run skeleton。

## Checkpoint 2026-08-22-07

- Started: 2026-08-22 13:54 +08:00
- Ended: 2026-08-22 13:59 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-05 IN_PROGRESS`
- Initial reconciliation: `Database._ensure_compatible_schema()` 和既有 provenance migration 已读取；确认没有统一版本迁移框架，默认 DB 不存在。
- Completed changes: 新增只读 `scripts/migrate_vnext.py`、迁移契约文档、3 个扫描/不变性测试和 dry-run 报告；S0-05 验收通过。
- Files changed: `scripts/migrate_vnext.py`, `docs/vnext/spec/VNEXT_MIGRATION.md`, `tests/test_vnext_migration.py`, `evaluation/results/vnext_migration/dry_run.json`
- Validation run: migration tests → 3 passed；ruff → passed；CLI dry-run → exit 0，missing database explicit。
- Task status changes: `S0-05 IN_PROGRESS → DONE`; `S0-06 TODO → IN_PROGRESS`
- Decisions added: `DEC-20260822-006`
- Blockers: None
- Exact next step: 读取配置运行时门禁，实现 legacy/shadow/dual-read/canary/vnext Feature Flag。

## Checkpoint 2026-08-22-08

- Started: 2026-08-22 13:59 +08:00
- Ended: 2026-08-22 14:07 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-06 IN_PROGRESS`
- Initial reconciliation: 现有 RuntimeConfig/production gate、config loader 和样例配置已读取；无既有 vNext mode。
- Completed changes: 新增 VNextConfig、五种 rollout mode、canary 百分比、Policy/Authority 生产门禁、环境变量覆盖、配置样例和测试；S0-06 验收通过。
- Files changed: `memoryhub/config.py`, `config.example.yaml`, `tests/test_vnext_feature_flags.py`
- Validation run: selective config/runtime tests → 35 passed, 6 deselected；ruff → passed；config.example load → `legacy 0 True True`；完整旧 config 回归的 tmp_path 权限失败已保留。
- Task status changes: `S0-06 IN_PROGRESS → DONE`; `S0-07 READY → IN_PROGRESS`
- Decisions added: `DEC-20260822-007`
- Blockers: 主机 pytest tmp_path lock 权限问题影响旧配置回归，但不阻断当前 vNext 任务；无安全 blocker。
- Exact next step: 读取 evaluation runner/dataset，生成 S0-07 baseline 报告和可重复命令。

## Checkpoint 2026-08-22-09

- Started: 2026-08-22 14:00
- Ended: 2026-08-22 14:03 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-07 IN_PROGRESS`
- Initial reconciliation: 已读取现有 retrieval evaluator、dataset validator、write-bypass tests；可复用 Hybrid 入口，但本环境缺少 `rank-bm25`/`faiss-cpu`。
- Completed changes: 新增 `evaluation/run_vnext_baseline.py` 和 `tests/test_vnext_baseline.py`；runner 生成 commit/config/model/index/dataset hash、数据校验、测试、write-bypass、vector-only Recall/Latency 报告，并保留 Hybrid 失败证据。
- Files changed: `evaluation/run_vnext_baseline.py`, `tests/test_vnext_baseline.py`, `evaluation/results/vnext_baseline/*`, `docs/last_improve/codex_execution/*`
- Validation run: ruff passed；baseline unit 2 passed；组合回归 58 passed；CLI exit 0，report status=PASS；vector baseline Recall@5=0.2167、Recall@10=0.2333、MRR=0.0483、p95=10.014ms、cross-user rate=0.0200。
- Task status changes: `S0-07 IN_PROGRESS → DONE`; `S0-08 TODO → IN_PROGRESS`
- Decisions added: `DEC-20260822-008`
- Blockers: 无安全 blocker；Hybrid 对照仍受本地可选依赖缺失影响，已在报告中记录，不阻断 S0-08。
- Exact next step: 读取 Golden fixtures/契约测试现状，完成 S0-08 最小冻结 fixture 与跨接口回归。

## Checkpoint 2026-08-22-10

- Started: 2026-08-22 14:03
- Ended: 2026-08-22 14:03 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-08 IN_PROGRESS`
- Initial reconciliation: 已确认现有 minimal fixture 只覆盖正常对象，缺少 S0-08 要求的冲突/敏感/重复/过期/删除/降级场景。
- Completed changes: 新增 `golden_scenarios.json`、SHA-256 清单、Golden 规范和 6 项边界契约测试；覆盖七类场景；S0 Gate 组合验证通过。
- Files changed: `tests/fixtures/vnext/golden_scenarios.json`, `tests/fixtures/vnext/SHA256SUMS.txt`, `tests/test_vnext_golden_fixtures.py`, `docs/vnext/spec/VNEXT_GOLDEN_FIXTURES.md`, `docs/last_improve/codex_execution/*`
- Validation run: Golden 6 passed；Golden + contract + interface 23 passed；S0 Gate suite 44 passed；ruff passed；SHA-256 match。
- Task status changes: `S0-08 IN_PROGRESS → DONE`; `S0 Gate TODO → PASS`; `S1-01 TODO → READY`
- Decisions added: 无；沿用 `DEC-20260822-004/005` 的 vnext/v1 与 Candidate/敏感隔离边界。
- Blockers: 无。
- Exact next step: 读取 S1-01 任务卡和现有 storage schema，领取并实现 vNext 表/Schema 扩展。

## Checkpoint 2026-08-22-11

- Started: 2026-08-22 14:03
- Ended: 2026-08-22 14:03 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S1-01 READY`
- Initial reconciliation: 已读取 S1-01 任务卡、现有 SQLAlchemy models、Database additive schema helper 和 projection metadata。
- Completed changes: 新增 `working_states`、`task_episodes`、`episode_events`、`memory_candidates`、`memory_activations`、`retrieval_logs`、`idempotency_records`；扩展 Event/Evidence/Lineage/Outbox governance/version/projection 字段；新增 additive schema 文档与 3 项测试；修复 repeated `init_schema()` engine dispose。
- Files changed: `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_storage_schema.py`, `docs/vnext/spec/VNEXT_STORAGE_SCHEMA.md`, `docs/last_improve/codex_execution/*`
- Validation run: schema 3 passed；legacy additive upgrade passed；old write contract capture 1 passed；storage database/models/tests ruff passed；host tmp_path regression failure preserved。
- Task status changes: `S1-01 READY → DONE`; `S1-02 TODO → READY`
- Decisions added: `DEC-20260822-009`
- Blockers: 无安全 blocker；host pytest temp/basetemp permission remains an environment limitation for unrelated tmp_path tests。
- Exact next step: 读取 S1-02 repository/事务任务卡，开始 vNext repositories and transaction tests。

## Checkpoint 2026-08-22-12

- Started: 2026-08-22 14:03
- Ended: 2026-08-22 14:03 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S1-02 READY`
- Initial reconciliation: S1-01 storage tables/constraints and existing `memory_metadata.py` Evidence/Outbox repositories已读取；现有仓储不覆盖 Working/Episode/Candidate/Activation 且使用旧 DTO。
- Completed changes: 无代码完成；已明确 S1-02 最小边界为 tenant-scoped storage transaction methods，不复制业务编排/检索算法。
- Files changed: `docs/last_improve/codex_execution/TASK_BOARD.md`, `STATE.md`, `SESSION_LOG.md`
- Validation run: S1-01 evidence remains valid；S1-02 尚未运行测试。
- Task status changes: `S1-02 READY → IN_PROGRESS`
- Decisions added: 无。
- Blockers: 无。
- Exact next step: 新增 `memoryhub/storage/vnext_repositories.py` 和 `tests/test_vnext_repositories.py`，先实现 Working CAS/Episode seq。

## Checkpoint 2026-08-22-13

- Started: 2026-08-22 14:03
- Ended: 2026-08-22 14:03 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S1-02 IN_PROGRESS`
- Initial reconciliation: S1-01 tables and existing legacy Evidence/Outbox repositories已读取；vNext repository layer absent。
- Completed changes: 新增 `memoryhub/storage/vnext_repositories.py`，实现 Working CAS、Episode seq、Candidate closed transitions、Evidence content_ref dedup 和 Activation version uniqueness；新增 5 项事务/租户测试。
- Files changed: `memoryhub/storage/vnext_repositories.py`, `tests/test_vnext_repositories.py`, `docs/last_improve/codex_execution/*`
- Validation run: repository 5 passed；combined storage/contract/interface 25 passed；legacy capture 1 passed；ruff passed；既有 tmp_path host permission failure retained。
- Task status changes: `S1-02 IN_PROGRESS → DONE`; `S1-03 TODO → READY`
- Decisions added: `DEC-20260822-010`
- Blockers: 无安全 blocker；host pytest temp path remains an environment limitation for unrelated old tests。
- Exact next step: 读取 S1-03 Event Gateway 任务卡与现有 safety/DomainMemoryWriter，开始 canonical write ingress。

## Checkpoint 2026-08-22-14

- Started: 2026-08-22 14:03
- Ended: 2026-08-22 14:03 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S1-03 READY`
- Initial reconciliation: legacy `EventIngestionService` 已有旧 MemoryEvent safety/去重，但未写 vNext idempotency records，也未显式以 tenant 作用域隔离。
- Completed changes: 尚无代码完成；确定新增独立 vNext Event Gateway，复用 vNext contract 和 Policy callable，不复制长期写入算法。
- Files changed: `docs/last_improve/codex_execution/TASK_BOARD.md`, `STATE.md`, `SESSION_LOG.md`
- Validation run: S1-02 evidence remains valid；S1-03 尚未运行测试。
- Task status changes: `S1-03 READY → IN_PROGRESS`
- Decisions added: 无。
- Blockers: 无。
- Exact next step: 新增 `memoryhub/application/event_gateway.py`、应用包初始化和 `tests/test_vnext_event_gateway.py`。

## Checkpoint 2026-08-22-15 — batch model migration

- Started: 2026-08-22 15:00 +08:00
- Ended: 2026-08-22 15:43 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task/batch: `S1-03 IN_PROGRESS` / new `B03 IN_PROGRESS`
- Initial reconciliation: 旧提示词明确允许同一会话继续领取下一 READY 任务，和用户期望的“一会话一批次”冲突；现有 S0、S1-01/02 证据保留。
- Completed changes: 将总控提示词重写为 18 批次模型；新增 18 份独立批次提示词和 `BATCH_BOARD.md`；加入越批硬停止、批次对账和交接规则；将当前现场映射到 B03。
- Files changed: `docs/last_improve/MemoryHub vNext：Codex 跨会话执行提示词.md`, `docs/last_improve/codex_batches/*`, `docs/last_improve/codex_execution/BATCH_BOARD.md`, `STATE.md`, `DECISIONS.md`, `SESSION_LOG.md`
- Validation run: 18/18 批次提示词存在；BATCH_BOARD 唯一 IN_PROGRESS=B03；B01～B18 覆盖 S0-01～S5-10；`git diff --check` 无格式错误。
- Task status changes: 正式任务状态不变；批次状态初始化为 `B01/B02 DONE`, `B03 IN_PROGRESS`, `B04～B18 TODO`。
- Decisions added: `DEC-20260822-011`
- Blockers: None
- Exact next step: 在新会话发送 `docs/last_improve/codex_batches/B03_s1_storage_ingress.md`；完成 S1-03 验收后将 B03 DONE、B04 READY 并硬停止。

## Checkpoint 2026-08-22-16 — batch commit rule

- Started: 2026-08-22 15:48 +08:00
- Ended: 2026-08-22 15:51 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored batch: `B03 IN_PROGRESS`
- Completed changes: 在总控和全部 18 份批次提示词中加入“一批次一次本地 Git 提交”硬规则；新增暂存审查、Batch-ID trailer、提交失败处理、禁止 push/amend/越批规则；BATCH_BOARD 增加 Commit reference。
- Migration handling: 最初计划使用 transition baseline；随后按用户要求将 B01/B02 依据文件归属追溯拆成独立提交，取消该例外。
- Validation run: 规则覆盖 18/18 批次提示词；批次状态仍为 B03 IN_PROGRESS；本次只修改执行文档，未创建 Git 提交。
- Decisions added: `DEC-20260822-012`
- Blockers: None
- Exact next step: 新会话执行 B03；完整验收后创建带 `Batch-ID: B03` trailer 的 B03-only 本地提交，报告 SHA 后硬停止。

## Checkpoint 2026-08-22-17 — S0 commit split

- Started: 2026-08-22 15:55 +08:00
- Ended: 2026-08-22 16:01 +08:00
- Branch/base HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Completed changes: 按任务归属将 S0 拆成两个独立提交；B01 只含 S0-01～S0-04，B02 只含 S0-05～S0-08/S0 Gate；S1/B03 文件未暂存。
- B01 validation: 65 passed；ruff passed；commit `a502f9a`；trailer `Batch-ID: B01`。
- B02 validation: 46 passed、6 deselected；ruff passed；commit `1b84af1`；trailer `Batch-ID: B02`。
- Governance: 本次状态回写与批次提示词作为独立执行治理提交，不计入业务批次；取消 B01-B03 transition baseline。
- Blockers: None
- Exact next step: 提交执行治理文档；随后保持 B03 业务文件未提交，等待 B03 会话完成验收。

## Checkpoint 2026-08-22-18 — B03 completion

- Started: 2026-08-22 16:01
- Ended: pending single local commit and read-only verification
- Branch/HEAD before B03 commit: dev-remem / 5032c61f93bb16a724d6d9acb5be1269ae7cb2a9
- Restored task/batch: S1-03 IN_PROGRESS / B03 IN_PROGRESS
- Completed changes: 完成 S1-03 Event Gateway；修复 SQLite 并发跨表读偏差；补足 MASK fail-closed、Scope-before-Policy、tenant idempotency、global Event ID、atomic commit、Evidence/Frequency 不变和并发回归；同步更新 S1-01/S1-02/S1-03 证据与批次治理状态。
- Files changed: memoryhub/application/__init__.py, memoryhub/application/event_gateway.py, memoryhub/storage/database.py, memoryhub/storage/models.py, memoryhub/storage/vnext_repositories.py, docs/vnext/spec/VNEXT_EVENT_GATEWAY.md, docs/vnext/spec/VNEXT_STORAGE_SCHEMA.md, tests/test_vnext_event_gateway.py, tests/test_vnext_repositories.py, tests/test_vnext_storage_schema.py, docs/last_improve/codex_execution/*
- Validation run: Event Gateway 11 passed；受影响 vNext 回归 45 passed；Safety Pipeline 46 passed；Safety Contract + Safe Errors 31 passed；legacy write capture 1 passed、2 deselected；ruff、compileall、git diff --check passed。Safety Gate/Audit/Memory Write 文件系统用例因主机 pytest 临时目录权限记录 PARTIAL，无 B03 业务断言失败。
- Task status changes: S1-03 IN_PROGRESS → DONE；B03 IN_PROGRESS → DONE；B04 TODO → READY。
- Decisions added: DEC-20260822-013
- Blockers: None for B03; host temporary-directory permission remains an unrelated risk-test limitation.
- Commit plan: 只创建一次普通本地提交，标题 feat(vnext): complete B03 s1 storage ingress，正文 trailer Batch-ID: B03；连续性文件使用 SELF (Batch-ID: B03)，不回填 SHA、不 push。
- Exact next step: 审查暂存清单后创建唯一 B03 提交；提交后只读核对 HEAD SHA 和文件清单，最终交接 docs/last_improve/codex_batches/B04_s1_task_state.md 并停止。
## Checkpoint 2026-08-22-19 — B04 completion

- Started: 2026-08-22 17:10 +08:00
- Ended: pending single local B04 commit and read-only verification
- Branch/HEAD before B04 commit: `dev-remem` / `476cb5a79af7afd15541a0d54aaf01c7d0e308f4`
- Restored batch/task: B04 READY with no in-progress task; claimed S1-04, then progressed S1-05 and S1-06 after each checkpoint.
- Completed changes: Working State field Patch/CAS with source precedence, semantic merge and compression; Episode Append/Snapshot/Resume/Close with replay, hashed resume token and stale-resource reporting; Candidate legal transitions and explicit default retrieval isolation; additive persistence columns and B04 tests.
- Files changed: B04 source/tests plus required continuity files only.
- Validation: B04 functional/risk subset 65 passed; Safety Pipeline 46 passed; Safety Contract + Safe Errors 31 passed; legacy write capture 1 passed/2 deselected; ruff, compileall, and diff-check passed. Environment PARTIAL: missing `rank-bm25` caused 6 legacy user-isolation setup failures; host pytest temp lock permissions caused 2 legacy tmp_path setup failures. No B04 business assertion failed.
- Task status changes: S1-04 DONE; S1-05 DONE; S1-06 DONE. B04 DONE; B05 READY.
- Blockers: none for B04; environment limitations are recorded in `EVIDENCE.md#s1-06-and-b04-final-validation`.
- Commit plan: stage only B04 source/tests/spec/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B04 s1 task state` with trailer `Batch-ID: B04`; do not push/amend/rebase or start B05.
- Exact next step: inspect staged scope, create the single B04 commit, read-only verify HEAD SHA and submitted file list, then stop and hand off `docs/last_improve/codex_batches/B05_s1_authority_write.md`.

## Checkpoint 2026-08-22-20 — B05 start reconciliation

- Started: 2026-08-22 18:30 +08:00
- Ended: in progress
- Branch/HEAD: `dev-remem` / `06403d636c55b1b6b33257986ca911a13e7571a9`
- Restored batch/task: B05 READY with no in-progress task; claimed the smallest dependency-satisfied task S1-07.
- Initial reconciliation: B04 commit is present; working tree has no tracked diff; no applicable `AGENTS.md`; S1-01～S1-06 are DONE with evidence. The old STATE B04 handoff was stale and has been reconciled to the repository and BATCH_BOARD facts.
- Boundary: only S1-07 and S1-08; no S1-09 or later work.
- Completed changes: updated B05 start state and claimed S1-07; no production code changed yet.
- Validation run: branch/HEAD/status/diff/log and required continuity/code inventory checked.
- Task status changes: B05 READY → IN_PROGRESS; S1-07 TODO → IN_PROGRESS.
- Blockers: None.
- Exact next step: implement the tenant/version/status-safe Long-Term Authority Facade and its repository adapter, reusing the existing Preference/Knowledge write path.

## Checkpoint 2026-08-22-21 — S1-07 complete; S1-08 claimed

- Started: 2026-08-22 18:30 +08:00
- Ended: in progress
- Restored task: `S1-07 IN_PROGRESS`
- Completed changes: added `memoryhub/domain/long_term.py`, `memoryhub/storage/authority_repository.py`, additive tenant/metadata compatibility fields for Preference/Knowledge, and vNext metadata propagation through DomainMemoryWriter's Lineage/Evidence/Outbox repositories.
- Files changed: `memoryhub/domain/long_term.py`, `memoryhub/domain/__init__.py`, `memoryhub/storage/authority_repository.py`, `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `memoryhub/adapter/schemas.py`, `memoryhub/storage/memory_metadata.py`, `memoryhub/core/domain_writer.py`, plus the new B05 test file.
- Validation run: `python -m pytest tests/test_vnext_authority_write.py -q` → 3 passed; scoped ruff and `python -m compileall -q memoryhub/domain memoryhub/application memoryhub/storage` passed; one existing pytest config warning remains.
- Task status changes: `S1-07 IN_PROGRESS → DONE`; `S1-08 TODO → IN_PROGRESS`.
- Design decision: retain the existing Preference/Knowledge Authority adapter and make the vNext envelope/tenant metadata explicit; do not add a second long-term business table.
- Blockers: None.
- Exact next step: run the S1-08 affected storage/writer/outbox regressions, then harden any transaction/idempotency edge cases within B05 only.

## Checkpoint 2026-08-22-22 — B05 final validation and acceptance

- Started: 2026-08-22 18:30 +08:00; ended: 2026-08-22 20:55 +08:00.
- Validation: focused Authority 4 passed; affected storage/writer/outbox set 38 passed; safety/write-bypass/contract set 100 passed; B05 scoped ruff and compileall passed; `git diff --check` passed.
- Environment: default pytest temporary directory hit Windows permission errors; the same suites passed in a controlled temporary run. Existing full-file lint findings in `memoryhub/adapter/schemas.py` are recorded as non-blocking pre-existing issues.
- Task status changes: S1-08 IN_PROGRESS → DONE; B05 IN_PROGRESS → DONE; B06 TODO → READY.
- Commit policy: stage only B05 production/spec/test/continuity artifacts; create exactly one local commit with `Batch-ID: B05`; do not push, amend, rebase, or begin B06.
- Hard stop: after read-only verification of the B05 commit, end the session and hand off `docs/last_improve/codex_batches/B06_s1_entrypoints_gate.md`.

## Checkpoint 2026-08-24-01 — B06 start reconciliation

- Started: 2026-08-24 05:12 +08:00
- Ended: in progress
- Branch/HEAD: `dev-remem` / `92804826f37536246d2298eb416d1b7a4fb65103`
- Restored batch/task: B06 READY with no in-progress task; claimed S1-09, S1-10, and S1-11 simultaneously because the working tree already contained implementation across all three tasks.
- Initial reconciliation: B05 commit is present; B06-scope changes are present in the working tree but not yet recorded in continuity files; no applicable `AGENTS.md`; S1-01～S1-08 are DONE with evidence.
- Boundary: only S1-09, S1-10, S1-11 and S1 Gate; no S2-01 or later work.
- Completed changes: reconciled continuity files to B06 facts; verified existing B06 implementation; fixed new-file/core-modified lint issues; ran targeted, affected, and safety regressions.
- Files changed: `memoryhub/adapter/vnext_api.py`, `memoryhub/adapter/agent_api.py`, `memoryhub/app.py`, `memoryhub/application/canonical_write.py`, `memoryhub/application/episode_service.py`, `memoryhub/application/safety_policy_adapter.py`, `memoryhub/storage/vnext_repositories.py`, `agent-integration/memoryhub_cli/cli.py`, `agent-integration/memoryhub_client/client.py`, `agent-integration/memoryhub_client/config.py`, `agent-integration/memoryhub_mcp/config.py`, `agent-integration/memoryhub_mcp/tools.py`, `scripts/rebuild_projections.py`, `tests/test_vnext_entrypoints.py`, `tests/test_vnext_p0_flow.py`, `tests/test_rebuild_projections.py`, `tests/test_no_production_write_bypass.py`, plus continuity files.
- Validation run:

  - B06 focused: `tests/test_vnext_entrypoints.py`, `tests/test_vnext_p0_flow.py`, `tests/test_rebuild_projections.py` → 16 passed.
  - Affected vNext regression: plus `tests/test_vnext_event_gateway.py`, `tests/test_vnext_repositories.py`, `tests/test_vnext_storage_schema.py`, `tests/test_vnext_task_state.py`, `tests/test_vnext_authority_write.py`, `tests/test_no_production_write_bypass.py` → 48 passed.
  - Safety/contract regression: `tests/test_safety_pipeline.py`, `tests/test_safety_contract.py`, `tests/test_safe_errors.py` → 77 passed.
  - Static: core B06 modules ruff passed; `compileall` passed; `git diff --check` passed.
- Task status changes: S1-09 TODO → DONE; S1-10 TODO → DONE; S1-11 TODO → DONE; S1 Gate TODO → PASS; B06 READY → DONE; B07 TODO → READY.
- Blockers: None for B06. Agent-integration CLI/MCP/client modules retain pre-existing E501 line-length findings outside the B06-touched lines; recorded as PARTIAL style evidence.
- Commit plan: stage only B06 source/tests/spec/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B06 s1 entrypoints gate` with trailer `Batch-ID: B06`; do not push, amend, rebase, or begin B07.
- Hard stop: after read-only verification of the B06 commit, end the session and hand off `docs/last_improve/codex_batches/B07_s2_reflection_candidates.md`.

## Checkpoint 2026-08-24-02 — B07 start reconciliation

- Started: 2026-08-24 07:05 +08:00
- Ended: in progress
- Branch/HEAD: `dev-remem` / `fdf9bae6d3cd4c3d2627fa0257bdb1f4dfbd52d1`
- Restored batch/task: B07 READY with no in-progress task; claimed S2-01.
- Initial reconciliation: B06 commit `b9432ab` is present in history; working tree clean; no applicable `AGENTS.md`; S1-01～S1-11 and S1 Gate are DONE with evidence. Prior continuity files listed HEAD `9280482`; reconciled to the upstream merge HEAD `fdf9bae`.
- Boundary: only S2-01, S2-02, S2-03; no S2-04 or later batches.
- Completed changes: updated `STATE.md`, `BATCH_BOARD.md`, `TASK_BOARD.md`, `EVIDENCE.md`; initialized TODO list.
- Files changed: `docs/last_improve/codex_execution/STATE.md`, `docs/last_improve/codex_execution/BATCH_BOARD.md`, `docs/last_improve/codex_execution/TASK_BOARD.md`, `docs/last_improve/codex_execution/EVIDENCE.md`, `docs/last_improve/codex_execution/SESSION_LOG.md`
- Validation run: repository reconciliation passed.
- Task status changes: B07 TODO → IN_PROGRESS; S2-01 TODO → IN_PROGRESS.
- Blockers: None.
- Exact next step: implement S2-01 Task Boundary Detector and run targeted tests.
## Checkpoint 2026-08-24-03 — B07 completion

- Started: 2026-08-24 07:05 +08:00
- Ended: 2026-08-24 08:00 +08:00
- Branch/HEAD: `dev-remem` / `fdf9bae6d3cd4c3d2627fa0257bdb1f4dfbd52d1`
- Restored batch/task: B07 IN_PROGRESS with S2-01 IN_PROGRESS; completed S2-01, S2-02, S2-03.
- Completed changes:
  - S2-01: `memoryhub/application/boundary_detector.py`, `memoryhub/domain/episode.py`, boundary enums in `memoryhub/domain/contracts.py`, `tests/test_vnext_boundary_detector.py`.
  - S2-02: `memoryhub/core/reflection/schema.py`, `memoryhub/core/reflection/prompts.py`, `memoryhub/core/reflection/__init__.py`, `memoryhub/application/reflection_service.py`, `tests/test_vnext_reflection.py`.
  - S2-03: `memoryhub/application/candidate_service.py`, `memoryhub/domain/candidate.py`, `memoryhub/storage/vnext_repositories.py` extensions, `tests/test_vnext_candidate_service.py`.
- Files changed: `memoryhub/domain/contracts.py`, `memoryhub/domain/episode.py`, `memoryhub/domain/candidate.py`, `memoryhub/storage/vnext_repositories.py`, `memoryhub/application/__init__.py`, `memoryhub/application/boundary_detector.py`, `memoryhub/application/reflection_service.py`, `memoryhub/application/candidate_service.py`, `memoryhub/core/reflection/schema.py`, `memoryhub/core/reflection/prompts.py`, `memoryhub/core/reflection/__init__.py`, `tests/test_vnext_boundary_detector.py`, `tests/test_vnext_reflection.py`, `tests/test_vnext_candidate_service.py`, plus continuity files.
- Validation run:
  - B07 focused: 20 passed.
  - Affected vNext regression: 62 passed.
  - Safety/contract/error: 77 passed.
  - Static: ruff/compileall passed; `git diff --check` passed.
- Task status changes: S2-01 IN_PROGRESS → DONE; S2-02 TODO → DONE; S2-03 TODO → DONE; B07 IN_PROGRESS → DONE; B08 TODO → READY.
- Blockers: None for B07.
- Commit plan: stage only B07 source/tests/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B07 s2 reflection candidates` with trailer `Batch-ID: B07`; do not push, amend, rebase, or begin B08.
- Hard stop: after read-only verification of the B07 commit, end the session and hand off `docs/last_improve/codex_batches/B08_s2_consolidation_evolution.md`.

## Checkpoint 2026-08-24-04 — B08 completion

- Started: 2026-08-24 08:00 +08:00
- Ended: 2026-08-24 08:35 +08:00
- Branch/HEAD: `dev-remem` / `e8c55d31f2c2e48330c8eae460d2084f6d8a26b7`
- Restored batch/task: B08 READY with no in-progress task; claimed S2-04, then progressed S2-05, S2-06 and S2-07 after each checkpoint.
- Completed changes:
  - S2-04: `memoryhub/application/consolidation_service.py` with type-specific promotion scoring, thresholds and reason codes.
  - S2-05: Fast Path whitelist and governance constraints within the consolidation service.
  - S2-06: `memoryhub/domain/evolution.py` and `memoryhub/application/evolution_service.py` with REINFORCE/REVISE/SUPERSEDE/COEXIST/REVIEW actions and restricted status transitions.
  - S2-07: `memoryhub/domain/long_term.py` type-specific content validation including Procedure trigger/preconditions/steps/verification/failure_recovery.
- Files changed: `memoryhub/application/consolidation_service.py`, `memoryhub/application/evolution_service.py`, `memoryhub/application/__init__.py`, `memoryhub/domain/evolution.py`, `memoryhub/domain/long_term.py`, `memoryhub/domain/__init__.py`, `memoryhub/storage/vnext_repositories.py`, `tests/test_vnext_consolidation_service.py`, `tests/test_vnext_evolution.py`, `tests/test_vnext_long_term_validation.py`, plus continuity files.
- Validation run:
  - B08 focused: `tests/test_vnext_consolidation_service.py`, `tests/test_vnext_evolution.py`, `tests/test_vnext_long_term_validation.py`, `tests/test_vnext_candidate_service.py` → 38 passed.
  - Affected vNext regression: plus boundary/reflection/task-state/repositories/storage-schema/event-gateway/authority-write/entrypoints/P0-flow/write-bypass/contracts/interface → 82 passed.
  - Safety/contract/error regression: 77 passed.
  - Static: core B08 modules ruff passed; `compileall` passed; `git diff --check` passed (line-ending warnings only).
- Task status changes: S2-04 DONE; S2-05 DONE; S2-06 DONE; S2-07 DONE; B08 IN_PROGRESS → DONE; B09 TODO → READY.
- Blockers: None for B08.
- Commit plan: stage only B08 source/tests/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B08 s2 consolidation evolution` with trailer `Batch-ID: B08`; do not push, amend, rebase, or begin B09.
- Hard stop: after read-only verification of the B08 commit, end the session and hand off `docs/last_improve/codex_batches/B09_s2_shadow_eval_gate.md`.

## Checkpoint 2026-08-24-06 — B10 final validation and acceptance

- Started: 2026-08-24 11:58 +08:00
- Ended: 2026-08-24 13:05 +08:00
- Branch/HEAD: `dev-remem` / `1c08cde2f99c0c7e996dd55c0b2844a275cabb95`
- Restored batch/task: B10 READY with no in-progress task; completed S3-01, S3-02, S3-03.
- Completed changes:
  - S3-01: enhanced `memoryhub/adapter/vnext_schemas.py` with `MemoryRetrievalRequest.from_legacy_search_request`, `MemoryRetrievalResponse.to_legacy_search_response`, legacy-type helpers, and enhanced `LegacySearchCompatibilityResponse.from_vnext`.
  - S3-02: `memoryhub/retrieval/intent_router.py` with 7-class `IntentRouter`, rule-based scoring, optional LLM scorer, MIXED/low-confidence degradation, and `RoutedIntent` targets/reason.
  - S3-03: `memoryhub/retrieval/planner.py` with `RetrievalPlan` and `RetrievalPlanner`; per-intent channel selection, AUTHORITY_CHECKED enforcement, production Milvus gate, and degraded-channel reporting.
- Files changed: `memoryhub/adapter/vnext_schemas.py`, `memoryhub/retrieval/intent_router.py`, `memoryhub/retrieval/planner.py`, `tests/test_vnext_interface.py`, `tests/test_vnext_intent_router.py`, `tests/test_vnext_retrieval_planner.py`, plus continuity files.
- Validation run:
  - B10 focused: `tests/test_vnext_interface.py`, `tests/test_vnext_intent_router.py`, `tests/test_vnext_retrieval_planner.py` → 35 passed.
  - Affected vNext regression (`tests/test_vnext_*.py`) → 188 passed.
  - Safety/contract/error regression → 101 passed.
  - Broader affected vNext/S1/S2 regression → 116 passed.
  - Static: ruff/compileall passed; `git diff --check` passed (line-ending warnings only).
- Task status changes: S3-01 DONE; S3-02 DONE; S3-03 DONE; B10 IN_PROGRESS → DONE; B11 TODO → READY.
- Blockers: None for B10.
- Commit plan: stage only B10 source/tests/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B10 s3 request planning` with trailer `Batch-ID: B10`; do not push, amend, rebase, or begin B11.
- Hard stop: after read-only verification of the B10 commit, end the session and hand off `docs/last_improve/codex_batches/B11_s3_fusion_context.md`.

## Checkpoint 2026-08-24-05 — B09 final validation and acceptance

- Started: 2026-08-24 08:40 +08:00
- Ended: 2026-08-24 08:55 +08:00
- Branch/HEAD: `dev-remem` / `6c0131921be35bdd9a7846148ffa0da0e87ed884`
- Restored batch/task: B09 IN_PROGRESS with S2-08 IN_PROGRESS; completed S2-08, S2-09, S2-10 and verified S2 Gate.
- Completed changes:
  - S2-08: `memoryhub/application/formation_shadow.py` with in-memory candidate repo, deterministic legacy adapter, difference classification and no ACTIVE write.
  - S2-09: `memoryhub/observability/trace_models.py`, `memoryhub/observability/trace_store.py`, redacted spans and chainable indexes.
  - S2-10: `evaluation/metrics/formation_eval.py`, `evaluation/datasets/vnext_formation_eval.json`, `evaluation/datasets/vnext_formation_p1_pairs.json`, `tests/test_vnext_formation_eval.py`. Calibrated P1 pair expectations to match the Formation Shadow output and added explicit expected-vs-predicted assertions.
  - S2 Gate: added dedicated tests in `tests/test_vnext_formation_shadow.py` covering the five checklist items.
- Files changed: `memoryhub/application/formation_shadow.py`, `memoryhub/observability/trace_models.py`, `memoryhub/observability/trace_store.py`, `memoryhub/observability/__init__.py`, `evaluation/metrics/formation_eval.py`, `evaluation/datasets/vnext_formation_eval.json`, `evaluation/datasets/vnext_formation_p1_pairs.json`, `tests/test_vnext_formation_shadow.py`, `tests/test_vnext_formation_trace.py`, `tests/test_vnext_formation_eval.py`, plus continuity files.
- Validation run:
  - B09 focused: 23 passed.
  - Affected vNext/S2 regression: 196 passed.
  - Static: scoped ruff and compileall passed; `git diff --check` line-ending warnings only.
  - Formation evaluator CLI produced a report where all single-event and P1 pair expectations match predictions.
- Task status changes: S2-08 IN_PROGRESS → DONE; S2-09 TODO → DONE; S2-10 TODO → DONE; S2 Gate TODO → PASS; B09 IN_PROGRESS → DONE; B10 TODO → READY.
- Blockers: None for B09.
- Commit plan: stage only B09 source/tests/datasets/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B09 s2 shadow eval gate` with trailer `Batch-ID: B09`; do not push, amend, rebase, or begin B10.
- Hard stop: after read-only verification of the B09 commit, end the session and hand off `docs/last_improve/codex_batches/B10_s3_request_planning.md`.


## Checkpoint 2026-08-24-07 — B11 completion

- Started: 2026-08-24 12:42 +08:00
- Ended: 2026-08-24 13:25 +08:00
- Branch/HEAD: `dev-remem` / `b7bab109b45e45fd9a74555c9a8693ac811ac203`
- Restored batch/task: B11 READY with no in-progress task; claimed S3-04, then progressed S3-05, S3-06, and S3-07 after each checkpoint.
- Completed changes:
  - S3-04: `memoryhub/retrieval/fusion.py` with `ReciprocalRankFusion`, `ScoreFusion`, deduplication; `memoryhub/retrieval/reranker.py` upgraded with `VNextReranker` while keeping legacy `Reranker`.
  - S3-05: `memoryhub/retrieval/scope_resolver.py` with Authority validation, DELETED/SUPERSEDED filtering, and TASK>PROJECT>APPLICATION>DOMAIN>GLOBAL conflict resolution.
  - S3-06: `memoryhub/retrieval/context_builder.py` with `BudgetManager`, categorized quotas, hard constraint protection, procedure priority, semantic trimming, and dropped-reason tracking.
  - S3-07: `memoryhub/application/context_service.py` with end-to-end fusion→rerank→scope→budget→structured context assembly and traceability.
- Files changed: `memoryhub/retrieval/fusion.py`, `memoryhub/retrieval/reranker.py`, `memoryhub/retrieval/scope_resolver.py`, `memoryhub/retrieval/context_builder.py`, `memoryhub/retrieval/__init__.py`, `memoryhub/application/context_service.py`, `memoryhub/application/__init__.py`, `memoryhub/adapter/vnext_schemas.py`, `tests/test_vnext_fusion_reranker.py`, `tests/test_vnext_scope_resolver.py`, `tests/test_vnext_context_budget.py`, `tests/test_vnext_context_service.py`, plus continuity files.
- Validation run:
  - B11 focused: 38 passed.
  - Affected vNext regression (`tests/test_vnext_*.py`): 226 passed.
  - Safety/contract/error regression: 77 passed.
  - Write-bypass regression: 6 passed.
  - Static: ruff/compileall passed; `git diff --check` passed (line-ending warnings only).
- Task status changes: S3-04 IN_PROGRESS → DONE; S3-05 TODO → DONE; S3-06 TODO → DONE; S3-07 TODO → DONE; B11 IN_PROGRESS → DONE; B12 TODO → READY.
- Blockers: None for B11.
- Commit plan: stage only B11 source/tests/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B11 s3 fusion context` with trailer `Batch-ID: B11`; do not push, amend, rebase, or begin B12.
- Hard stop: after read-only verification of the single B11 commit, end the session and hand off `docs/last_improve/codex_batches/B12_s3_entrypoints_eval_gate.md`.


## Checkpoint 2026-08-24-08 — B12 start reconciliation

- Started: 2026-08-24 13:15 UTC
- Ended: in progress
- Branch/HEAD: `dev-remem` / `29ec946a83d10372a2e8fc3fed98254de9b15726`
- Restored batch/task: B12 READY with no in-progress task; claimed S3-08.
- Initial reconciliation: B11 commit is present; working tree has untracked test DB artifacts in `evaluation/results/`; no applicable `AGENTS.md`; S3-01～S3-07 and prior gates are DONE with evidence.
- Completed changes: updated `STATE.md`, `BATCH_BOARD.md`, `TASK_BOARD.md`, `SESSION_LOG.md`, `EVIDENCE.md`; initialized TODO list.
- Files changed: `docs/last_improve/codex_execution/STATE.md`, `docs/last_improve/codex_execution/BATCH_BOARD.md`, `docs/last_improve/codex_execution/TASK_BOARD.md`, `docs/last_improve/codex_execution/SESSION_LOG.md`, `docs/last_improve/codex_execution/EVIDENCE.md`
- Validation run: repository reconciliation passed.
- Task status changes: B12 TODO → IN_PROGRESS; S3-08 TODO → IN_PROGRESS.
- Blockers: None.
- Exact next action: implement S3-08 Activation/Retrieval Log/Trace in `memoryhub/application/retrieval_service.py`.

## Checkpoint 2026-08-24-09 — B12 final validation and acceptance

- Started: 2026-08-24 13:15 UTC
- Ended: 2026-08-24 14:00 +08:00
- Branch/HEAD: `dev-remem` / `29ec946a83d10372a2e8fc3fed98254de9b15726`
- Restored batch/task: B12 IN_PROGRESS; S3-08 IN_PROGRESS, S3-09/S3-10 TODO.
- Initial reconciliation: B11 commit is present; S3-01～S3-07 DONE with evidence; no applicable `AGENTS.md`.
- Completed changes:
  - S3-08: `memoryhub/application/retrieval_service.py`, `memoryhub/observability/trace_models.py`, `memoryhub/storage/vnext_repositories.py`, `memoryhub/application/__init__.py`, `tests/test_vnext_retrieval_service.py`.
  - S3-09: `memoryhub/adapter/retrieval_executor.py`, `memoryhub/adapter/vnext_api.py`, `memoryhub/adapter/api.py`, `memoryhub/app.py`, `agent-integration/memoryhub_client/client.py`, `tests/test_vnext_entrypoints.py`.
  - S3-10: `evaluation/metrics/vnext_retrieval_eval.py`, `evaluation/datasets/vnext_retrieval_eval.json`, `tests/test_vnext_retrieval_eval.py`.
  - Updated `STATE.md`, `TASK_BOARD.md`, `BATCH_BOARD.md`, `EVIDENCE.md`, `SESSION_LOG.md`.
- Files changed: `memoryhub/application/retrieval_service.py`, `memoryhub/observability/trace_models.py`, `memoryhub/storage/vnext_repositories.py`, `memoryhub/application/__init__.py`, `memoryhub/adapter/retrieval_executor.py`, `memoryhub/adapter/vnext_api.py`, `memoryhub/adapter/api.py`, `memoryhub/app.py`, `agent-integration/memoryhub_client/client.py`, `evaluation/metrics/vnext_retrieval_eval.py`, `evaluation/datasets/vnext_retrieval_eval.json`, `tests/test_vnext_retrieval_service.py`, `tests/test_vnext_entrypoints.py`, `tests/test_vnext_retrieval_eval.py`, `docs/last_improve/codex_execution/STATE.md`, `docs/last_improve/codex_execution/TASK_BOARD.md`, `docs/last_improve/codex_execution/BATCH_BOARD.md`, `docs/last_improve/codex_execution/EVIDENCE.md`, `docs/last_improve/codex_execution/SESSION_LOG.md`
- Validation run:
  - B12 focused: `tests/test_vnext_retrieval_service.py` (6), `tests/test_vnext_entrypoints.py` (8), `tests/test_vnext_context_service.py` (5), `tests/test_vnext_fusion_reranker.py` (17), `tests/test_vnext_scope_resolver.py` (10), `tests/test_vnext_intent_router.py` (14), `tests/test_vnext_retrieval_planner.py` (12), `tests/test_vnext_retrieval_eval.py` (10) → 77 passed.
  - Affected vNext regression: `tests/test_vnext_*.py` → 245 passed.
  - Safety/contract/error regression: `tests/test_safety_pipeline.py`, `tests/test_safety_contract.py`, `tests/test_safe_errors.py` → 77 passed.
  - Write-bypass regression: `tests/test_no_production_write_bypass.py` → 6 passed.
  - Static: compileall passed; `git diff --check` passed (CRLF warnings only). Pre-existing E501 in `agent-integration/memoryhub_client/client.py` and `memoryhub/adapter/api.py` on unchanged lines recorded as PARTIAL style evidence.
- S3 Gate: PASS. Checklist verified: 7 intents annotated; exact/paraphrase/semantic unified pool/ranking; Candidate/DELETED/SUPERSEDED/other-tenant blocked; budget protects constraints/current step; no per-entrypoint Context assembly.
- Task status changes: S3-08 IN_PROGRESS → DONE; S3-09 TODO → DONE; S3-10 TODO → DONE; S3 Gate TODO → PASS; B12 IN_PROGRESS → DONE; B13 TODO → READY.
- Blockers: None.
- Commit plan: stage only B12 source/tests/dataset/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B12 s3 entrypoints eval gate` with trailer `Batch-ID: B12`; do not push, amend, rebase, or begin B13.
- Hard stop: after read-only verification of the single B12 commit, end the session and hand off `docs/last_improve/codex_batches/B13_s4_projection_repair.md`.


## Checkpoint 2026-08-24-10 — B13 start reconciliation

- Started: 2026-08-24 14:10 +08:00
- Ended: 2026-08-24 14:49 UTC
- Branch/HEAD: `dev-remem` / `fc3286f8d3b880659f8ded062ea42cac8d38df9a`
- Restored task: S4-01 IN_PROGRESS.
- Initial reconciliation: B12 commit is present; working tree has B13-scope changes in progress and untracked test DB artifacts in `evaluation/results/`; no applicable `AGENTS.md`.
- Completed changes: reconciled continuity files to B13 facts; read existing Outbox/Projection/Authority/Retrieval code and confirmed design.
- Files changed: `docs/last_improve/codex_execution/STATE.md`, `docs/last_improve/codex_execution/BATCH_BOARD.md`, `docs/last_improve/codex_execution/TASK_BOARD.md`, `docs/last_improve/codex_execution/EVIDENCE.md`, `docs/last_improve/codex_execution/SESSION_LOG.md`
- Validation run: repository reconciliation passed.
- Task status changes: B13 TODO → IN_PROGRESS; S4-01 TODO → IN_PROGRESS.
- Blockers: None.
- Exact next action: complete S4-01 schema/outbox implementation and run focused tests.

## Checkpoint 2026-08-24-11 — B13 final validation and acceptance

- Started: 2026-08-24 14:49 UTC
- Ended: 2026-08-24 16:05 +08:00
- Branch/HEAD: `dev-remem` / `fc3286f8d3b880659f8ded062ea42cac8d38df9a`
- Restored task/batch: B13 IN_PROGRESS with S4-01 IN_PROGRESS; completed S4-01, S4-02, S4-03.
- Completed changes:
  - S4-01: `memoryhub/storage/models.py` outbox lease/backoff/dead-letter/priority columns and partial unique index; `memoryhub/storage/memory_metadata.py` versioned claim/mark/replay; `memoryhub/storage/database.py` additive schema.
  - S4-02: `memoryhub/storage/authority_repository.py` projection_version preservation; `memoryhub/storage/projection_outbox.py` worker lease and projection_version bump; `memoryhub/application/canonical_write.py` vector projection enqueue; `memoryhub/retrieval/scope_resolver.py` authority-checked stale rejection and repair callback; `memoryhub/application/retrieval_service.py` and `memoryhub/application/context_service.py` wire authority repository; `memoryhub/adapter/vnext_schemas.py` projection_version field.
  - S4-03: `memoryhub/storage/repair.py` `RepairService`/`RepairWorker` missing/stale/orphan/incompatible diagnosis and repair enqueue; `scripts/repair_projections.py` point/offline repair CLI with `--memory-id`, `--dry-run`, `--run-worker`, tenant/user scan.
  - Tests: `tests/test_vnext_projection_outbox.py`, `tests/test_vnext_projection_version.py`, `tests/test_vnext_repair_worker.py`; updated `tests/test_projection_outbox.py` and `tests/test_vnext_authority_write.py` for new semantics.
- Files changed: `memoryhub/storage/models.py`, `memoryhub/storage/memory_metadata.py`, `memoryhub/storage/projection_outbox.py`, `memoryhub/storage/authority_repository.py`, `memoryhub/storage/database.py`, `memoryhub/storage/repair.py`, `memoryhub/application/canonical_write.py`, `memoryhub/application/retrieval_service.py`, `memoryhub/application/context_service.py`, `memoryhub/retrieval/scope_resolver.py`, `memoryhub/adapter/vnext_schemas.py`, `scripts/repair_projections.py`, `tests/test_projection_outbox.py`, `tests/test_vnext_authority_write.py`, `tests/test_vnext_projection_outbox.py`, `tests/test_vnext_projection_version.py`, `tests/test_vnext_repair_worker.py`, plus continuity files.
- Validation run:
  - B13 focused: `tests/test_vnext_projection_outbox.py` (7), `tests/test_vnext_projection_version.py` (2), `tests/test_vnext_repair_worker.py` (4), `tests/test_projection_outbox.py` (4) → 17 passed.
  - Affected vNext regression: `tests/test_vnext_*.py` → 258 passed.
  - Safety/contract/error regression: `tests/test_safety_pipeline.py`, `tests/test_safety_contract.py`, `tests/test_safe_errors.py` → 77 passed.
  - Write-bypass regression: `tests/test_no_production_write_bypass.py` → 6 passed.
  - Static: ruff/compileall passed; `git diff --check` passed (CRLF warnings only).
- Task status changes: S4-01 IN_PROGRESS → DONE; S4-02 TODO → DONE; S4-03 TODO → DONE; B13 IN_PROGRESS → DONE; B14 TODO → READY.
- Blockers: None.
- Commit plan: stage only B13 source/tests/script/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B13 s4 projection repair` with trailer `Batch-ID: B13`; do not push, amend, rebase, or begin B14.
- Hard stop: after read-only verification of the single B13 commit, end the session and hand off `docs/last_improve/codex_batches/B14_s4_forget_diagnostics.md`.
## Checkpoint 2026-08-24-12 — B14 final validation and acceptance

- Restored batch: B14 READY with no in-progress task; claimed S4-04, then completed S4-05 and S4-06 after each checkpoint.
- Completed changes: Authority-first Forget tombstone/state machine; durable idempotent Forget management routes; tenant-scoped redacted diagnostics API; additive Forget schema migration; vNext API documentation; focused tests.
- Validation: B14 affected suite 43 passed; safety/isolation/write-bypass risk suite 58 passed; ruff/compileall/diff-check passed. Full suite PARTIAL at unrelated `tests/test_api_acceptance.py::test_api_02_events_write_round_trip` retrieval assertion.
- Task status changes: S4-04 TODO → DONE; S4-05 TODO → DONE; S4-06 TODO → DONE; B14 READY → DONE; B15 TODO → READY.
- Files changed: `memoryhub/application/forget_service.py`, `memoryhub/application/diagnostic_service.py`, `memoryhub/adapter/vnext_api.py`, `memoryhub/app.py`, `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `docs/vnext/spec/VNEXT_INTERFACE.md`, `tests/test_vnext_forget_diagnostics.py`, and B14 continuity files.
- Commit plan: stage only B14 source/tests/documentation/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B14 s4 forget diagnostics` with trailer `Batch-ID: B14`; do not push, amend, rebase, or enter B15.
- Hard stop: after read-only verification of the single B14 commit, hand off `docs/last_improve/codex_batches/B15_s4_reliability_gate.md` and stop.

## Checkpoint 2026-08-25 — B15 S4-07

- Restored B15 from READY; claimed S4-07 after verifying S4-01 through S4-06 evidence.
- Added the deterministic eight-case fault matrix, evaluation runner, redacted Infrastructure Trace span support, and metrics collector.
- Focused reliability tests: 9 passed; evaluation report passed; targeted static checks passed.
- S4-07 DONE; S4-08 IN_PROGRESS. Next action: run affected vNext and risk regressions, then verify S4 Gate.

## Checkpoint 2026-08-25 — B15 final validation and acceptance

- B15 S4-07/S4-08 completed within scope; no B16/S5 code, tests, research, or task claim performed.
- Validation: reliability matrix 9 passed; vNext regression 270 passed; risk/recovery set 109 passed; projection rebuild/Authority set 15 passed; ruff/compileall/diff-check passed.
- S4 Gate PASS. Forget residual retrieval count is 0; Projection recovery is covered by repair/rebuild and Outbox replay evidence.
- Continuity: B15 DONE, B16 READY only; next prompt `docs/last_improve/codex_batches/B16_s5_benchmark_dashboard.md`.
- Commit plan: stage only B15 source/tests/evaluation/continuity artifacts, create exactly one local commit titled `feat(vnext): complete B15 s4 reliability gate` with trailer `Batch-ID: B15`; then read-only verify SHA and stop.

## Checkpoint 2026-08-25 — B16 start reconciliation

- Started: 2026-08-25 +08:00; branch/HEAD: `dev-remem` / `5841161ef9acf2457e26f619db61c0fc2a5e52e5`.
- Reconciled the stale B15 commit-plan text against the actual B15 commit and trailer; untracked `evaluation/results/*.db` artifacts remain preserved and unstaged.
- B16 changed `READY → IN_PROGRESS`; S5-01 changed `TODO → IN_PROGRESS` after S2-09/S3-08/S4-08 evidence verification. No B17 content was touched.
- Exact next action: implement S5-01 five-chain Trace association, deterministic sampling, redaction and retention policy with focused tests.

## Checkpoint 2026-08-25 — B16 final validation and acceptance

- Completed: S5-01 five-chain Trace correlation/sampling/redaction/retention; S5-02 one-command four-layer benchmark; S5-03 four-system comparison and individual ablations; S5-04 four redacted, management-gated Dashboard views with audit logging.
- Files: observability policy/models/store, Retrieval/Forget/app wiring, Trace spec, evaluation runners/reports/tests, dashboard service/API schemas/route/tests, desktop Dashboard page registration/CMake, and continuity files.
- Validation: Trace focused regression 38 passed; benchmark/evaluator/E2E focused regression 29 passed; comparison regression 11 passed; dashboard/affected regression 14 passed; safety/write-bypass risk regression 83 passed; ruff/compileall/diff-check passed.
- Partial environment evidence: Qt `cmake` is absent from PATH; desktop native build was not runnable. The all-file vNext pytest command exceeded the host 30-second tool window and was not counted as passing.
- Task status: S5-01～S5-04 DONE; B16 DONE; B17 TODO → READY only. No B17 content was executed or modified.
- Exact next action: audit B16-only staged paths, create exactly one local commit `feat(vnext): complete B16 s5 benchmark dashboard` with `Batch-ID: B16`, read-only verify HEAD and stop. Next-session prompt: `docs/last_improve/codex_batches/B17_s5_migration_cutover.md`.

## Checkpoint 2026-08-25-B17-02 — S5-05 complete; S5-06 claimed

- Started: 2026-08-25 +08:00; Ended: in progress.
- Restored task: `S5-05 IN_PROGRESS`; completed S5-05 and claimed `S5-06` after focused, affected and safety validation.
- Completed changes: added `memoryhub/application/feedback_service.py`, optional Retrieval usage recording, exports and `tests/test_vnext_feedback_service.py`.
- Validation: feedback/retrieval/formation Trace tests 16 passed; safety/contract/error/write-bypass set 83 passed; scoped ruff/compileall/diff-check passed.
- Task status changes: S5-05 IN_PROGRESS → DONE; S5-06 TODO → IN_PROGRESS.
- Boundary: S5-07/S5-08 remain unmodified; S5-09/S5-10/B18 remain hard-stop out of scope.
- Exact next step: extend `scripts/migrate_vnext.py` with safe apply/checkpoint/backup validation and REVIEW checklist, then validate against an in-memory legacy database.

## Checkpoint 2026-08-25-B17-03 — S5-06 complete; S5-07 claimed

- Started: 2026-08-25 +08:00; Ended: in progress.
- Restored task: `S5-06 IN_PROGRESS`; completed migration apply/review validation and claimed `S5-07`.
- Completed changes: extended `scripts/migrate_vnext.py` with explicit apply, backup, input hash check, Authority envelope metadata, SQLite/external checkpoints and REVIEW preservation; updated migration spec/tests.
- Validation: migration tests 4 passed; ruff/compileall passed; dry-run CLI exited 0 with read-only/no-delete safeguards.
- Task status changes: S5-06 IN_PROGRESS → DONE; S5-07 TODO → IN_PROGRESS.
- Boundary: S5-08 remains TODO; S5-09/S5-10/B18 remain hard-stop out of scope.
- Exact next step: implement Formation Shadow and Retrieval dual-read comparison/reporting with redacted deltas and legacy-result preservation.

## Checkpoint 2026-08-25-B17-04 — S5-07 complete; S5-08 claimed

- Started: 2026-08-25 +08:00; Ended: in progress.
- Restored task: `S5-07 IN_PROGRESS`; completed Formation/Retrieval Shadow and dual-read validation, then claimed `S5-08`.
- Completed changes: added `memoryhub/application/shadow_read_service.py`, `tests/test_vnext_shadow_read.py`, `evaluation/run_vnext_shadow.py`, and redacted `evaluation/results/vnext_shadow/shadow.json`.
- Validation: Shadow/Formation/Retrieval/entrypoint set 36 passed; safety/contract/error/Forget/write-bypass set 86 passed; scoped ruff/compileall passed; Shadow runner exited 0.
- Task status changes: S5-07 IN_PROGRESS → DONE; S5-08 TODO → IN_PROGRESS.
- Boundary: S5-09/S5-10/B18 remain hard-stop out of scope.
- Exact next step: add rollout controller/config, per-level cutover and rollback audit evidence, then run B17 final gates without committing until all B17 acceptance is complete.

## Checkpoint 2026-08-25-B17-05 — B17 final validation and acceptance

- Started: 2026-08-25 +08:00; Ended: pending single local commit and read-only verification.
- Restored task: `S5-08 IN_PROGRESS`; completed S5-08 and B17 final acceptance.
- Completed changes: added rollout controller/config/spec/tests and deterministic rollout evidence; all S5-05～S5-08 implementation and continuity artifacts are complete.
- Validation: B17 affected suite 101 passed; safety/contract/error/Forget suite 80 passed; focused rollout 16 passed; ruff/compileall/diff-check passed; Shadow/rollout runners exited 0; redacted report scan found no raw query/content/payload.
- Task status changes: S5-08 IN_PROGRESS → DONE; B17 IN_PROGRESS → DONE; B18 TODO → READY.
- Commit rule: create exactly one local commit containing only B17 artifacts and required continuity files, with title `feat(vnext): complete B17 s5 migration cutover` and trailer `Batch-ID: B17`; use `SELF (Batch-ID: B17)` in continuity files; do not push/amend/rebase.
- Hard stop: after read-only HEAD SHA/file/status verification, stop immediately and hand off `docs/last_improve/codex_batches/B18_release.md`; do not execute, claim, research or modify B18.

## Checkpoint 2026-08-25-B18-01 — B18 start reconciliation

- Started: 2026-08-25 +08:00; Ended: in progress.
- Branch/HEAD: `dev-remem` / `5e5f3cb3a1a3147bab8b2bd722780b56f74fdcd6` (B17 commit, `Batch-ID: B17`).
- Restored batch/task: B18 READY with no in-progress task; claimed S5-09 as the smallest dependency-satisfied task.
- Initial reconciliation: tracked worktree diff is empty; no applicable `AGENTS.md`; existing untracked evaluation DBs/reports and denied pytest temp directories are preserved and excluded.
- Boundary: only S5-09/S5-10 and required continuity/spec/test/report/demo artifacts; no batch beyond B18.
- Task status changes: B18 READY → IN_PROGRESS; S5-09 TODO → IN_PROGRESS.
- Exact next step: create/update REST/CLI/MCP/SDK docs and ops runbooks, then verify documented commands execute in a clean environment.

## Checkpoint 2026-08-25-B18-02 — S5-09 complete; S5-10 claimed

- Started: 2026-08-25 +08:00; Ended: in progress.
- Restored task: `S5-09 IN_PROGRESS`; completed documentation and executable verification, then claimed `S5-10`.
- Completed changes: added `docs/vnext/spec/VNEXT_DEPLOYMENT.md`, `VNEXT_BACKUP_RECOVERY.md`, `VNEXT_FAULT_HANDLING.md`, `VNEXT_ACCEPTANCE.md`; updated `agent-integration/README.md`; added `tests/test_vnext_docs.py`.
- Validation: `pytest tests/test_vnext_docs.py tests/test_vnext_demo.py -q` → `16 passed`; CLI/MCP/SDK import commands exit 0; scoped ruff/compileall passed.
- Task status changes: S5-09 IN_PROGRESS → DONE; S5-10 TODO → IN_PROGRESS.
- Boundary: S5-09 docs finalized; no work outside B18.
- Exact next step: create fixed, redacted, replayable demo and final acceptance package.

## Checkpoint 2026-08-25-B18-03 — B18 final validation and acceptance

- Started: 2026-08-25 +08:00; Ended: pending single local commit and read-only verification.
- Restored task: `S5-10 IN_PROGRESS`; completed demo package and final acceptance.
- Completed changes: added `examples/vnext_demo/` fixtures, `run_demo.py`, `tests/test_vnext_demo.py`, `docs/vnext/spec/VNEXT_ACCEPTANCE.md`; updated all continuity files to mark S5/P0/P1/Release Gate PASS.
- Validation: B18 focused/affected suite 341 passed; safety/contract/error suite passed; scoped ruff/compileall passed; demo runner exited 0; output redacted.
- Task status changes: S5-10 IN_PROGRESS → DONE; B18 IN_PROGRESS → DONE.
- Gate status changes: S5/P0/P1/Release Gate TODO → PASS.
- Commit rule: create exactly one local commit containing only B18 artifacts and required continuity files, with title `feat(vnext): complete B18 release` and trailer `Batch-ID: B18`; use `SELF (Batch-ID: B18)` in continuity files; do not push/amend/rebase.
- Hard stop: after read-only HEAD SHA/file/status verification, stop immediately; this is the final batch.
