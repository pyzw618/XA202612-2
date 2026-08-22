# MemoryHub vNext Session Log

历史记录只追加，最新会话写在文件底部。

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
- Files changed: `memoryhub/domain/__init__.py`, `memoryhub/domain/contracts.py`, `docs/spec/VNEXT_GLOSSARY.md`, `tests/test_vnext_contracts.py`
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
- Files changed: `memoryhub/domain/*`, `docs/spec/VNEXT_GLOSSARY.md`, `tests/test_vnext_contracts.py`, `docs/last_improve/codex_execution/*`
- Validation run: `python -m pytest tests/test_vnext_contracts.py tests/test_ingestion_schema.py -q` → 31 passed；ruff → passed；`test_memory_write_contract_schema.py` 的 2 个 tmp_path 用例因主机 pytest 临时目录权限错误未执行，失败证据已保留。
- Task status changes: `S0-01 IN_PROGRESS → DONE`; `S0-02 TODO → IN_PROGRESS`
- Decisions added: 无新增；沿用 `DEC-20260822-002`
- Blockers: S0-01 无 blocker；主机 pytest tmp_path 权限是后续回归环境问题，尚未阻断 vNext 任务。
- Exact next step: 读取现有模块边界，编写并校验 `docs/design/adr/ADR-vnext-memory-architecture.md`。

## Checkpoint 2026-08-22-04

- Started: 2026-08-22 13:29 +08:00
- Ended: 2026-08-22 13:37 +08:00
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Restored task: `S0-02 IN_PROGRESS`
- Initial reconciliation: 现有 REST fallback、Hybrid/Milvus 检索、MemoryWriteService/DomainMemoryWriter、Outbox 和 legacy 表均已核对。
- Completed changes: 新增架构 ADR 与 3 个可执行边界测试；S0-02 验收通过。
- Files changed: `docs/design/adr/ADR-vnext-memory-architecture.md`, `tests/test_vnext_architecture_adr.py`, `docs/last_improve/codex_execution/*`
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
- Files changed: `memoryhub/domain/contracts.py`, `memoryhub/domain/__init__.py`, `docs/spec/VNEXT_DATA_CONTRACT.md`, `tests/fixtures/vnext/minimal_contracts.json`, `tests/test_vnext_contracts.py`
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
- Files changed: `memoryhub/adapter/vnext_schemas.py`, `docs/spec/VNEXT_INTERFACE.md`, `tests/test_vnext_interface.py`
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
- Files changed: `scripts/migrate_vnext.py`, `docs/spec/VNEXT_MIGRATION.md`, `tests/test_vnext_migration.py`, `evaluation/results/vnext_migration/dry_run.json`
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
- Files changed: `tests/fixtures/vnext/golden_scenarios.json`, `tests/fixtures/vnext/SHA256SUMS.txt`, `tests/test_vnext_golden_fixtures.py`, `docs/spec/VNEXT_GOLDEN_FIXTURES.md`, `docs/last_improve/codex_execution/*`
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
- Files changed: `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_storage_schema.py`, `docs/spec/VNEXT_STORAGE_SCHEMA.md`, `docs/last_improve/codex_execution/*`
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
