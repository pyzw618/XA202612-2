# MemoryHub vNext Execution Evidence

## Batch commit reconciliation

- B01 (`S0-01`～`S0-04`): commit `a502f9a`; `Batch-ID: B01`; validation 65 passed and ruff passed.
- B02 (`S0-05`～`S0-08`, S0 Gate): commit `1b84af1`; `Batch-ID: B02`; validation 46 passed, 6 deselected, and ruff passed.
- Scope audit: B01/B02 commits contain only their assigned S0 artifacts. S1 storage/repository/Event Gateway files remain outside both commits.

## B04 start reconciliation

- Date/time: 2026-08-22 17:10 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  git diff --name-only
  rg --files -g 'AGENTS.md' -g '!vnext-schema-*' -g '!**/.pytest*'
  ```
- Result: PASS for repository reconciliation. HEAD=`476cb5a79af7afd15541a0d54aaf01c7d0e308f4`; no tracked worktree changes; no applicable `AGENTS.md` found. Ignored pytest/schema scratch directories were not considered batch artifacts.
- Continuity: `BATCH_BOARD.md` had B04 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B04 task in progress. S1-01/S1-02/S1-03 are DONE with existing evidence.
- Decision: claim the smallest dependency-satisfied B04 task, S1-04; do not touch S1-07 or later batches.
- Artifact/trace: `STATE.md`, `TASK_BOARD.md`, `BATCH_BOARD.md`, `EVIDENCE.md`, `SESSION_LOG.md`, `DECISIONS.md`
- Follow-up: inspect Working contracts/repositories and implement the S1-04 domain/application slice.

## S1-04 checkpoint

- Date/time: 2026-08-22 17:35 +08:00
- Environment: Windows PowerShell; system Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Working State field-level Patch/CAS, source precedence, semantic merge, and structured compression
- Commands:
  ```text
  python -m pytest tests/test_vnext_task_state.py -q
  python -m pytest tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_contracts.py tests/test_vnext_interface.py -q
  python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/__init__.py memoryhub/domain/working.py memoryhub/domain/episode.py memoryhub/domain/candidate.py memoryhub/application/__init__.py memoryhub/application/working_service.py memoryhub/application/episode_service.py memoryhub/storage/models.py memoryhub/storage/database.py memoryhub/storage/vnext_repositories.py tests/test_vnext_task_state.py
  python -m compileall -q memoryhub/domain memoryhub/application memoryhub/storage
  git diff --check
  ```
- Result: PASS; B04 task-state tests 3 passed; affected S1-02/storage/contract/interface regression 25 passed; ruff, compileall, and diff check passed. Pytest emitted only the existing unknown `asyncio_mode` warning.
- Summary: Working service applies only field-level operations; stale `base_version` raises `VersionConflictError`; lower-priority inferred/tool changes cannot overwrite a higher-priority user field; semantic list fields merge deterministically; compressed output is structured and bounded. Field-source metadata is persisted separately from state.
- Artifact/report/trace: `memoryhub/domain/working.py`, `memoryhub/application/working_service.py`, `memoryhub/storage/vnext_repositories.py`, `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_task_state.py`
- Acceptance: S1-04 DONE. S1-05 is the only B04 task now IN_PROGRESS.
- Follow-up: run the Episode-specific tests and affected regressions; preserve explicit evidence for stale resources, token rejection, replay, close, and optimistic conflict.

## S1-05 checkpoint

- Date/time: 2026-08-22 17:50 +08:00
- Environment: Windows PowerShell; system Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Episode Append + Snapshot + Resume + Close, replay, stale-resource checks, and resume token
- Commands:
  ```text
  python -m pytest tests/test_vnext_task_state.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py -q
  python -m ruff check memoryhub/domain/episode.py memoryhub/application/episode_service.py memoryhub/storage/models.py memoryhub/storage/database.py memoryhub/storage/vnext_repositories.py tests/test_vnext_task_state.py
  ```
- Result: PASS; 11 tests passed; ruff passed. Pytest emitted only the existing unknown `asyncio_mode` warning.
- Summary: Episode append assigns monotonic sequence and returns an existing source event on retry; snapshot increments its CAS version and stores only a SHA-256 resume-token hash; resume rejects wrong tokens and stale expected versions; replay applies events newer than the snapshot; current resource-version differences appear in `stale_resources` and `required_revalidation`; close allows ACTIVE/SUSPENDED to COMPLETED/FAILED only.
- Artifact/report/trace: `memoryhub/domain/episode.py`, `memoryhub/application/episode_service.py`, `memoryhub/storage/vnext_repositories.py`, `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_task_state.py`
- Acceptance: S1-05 DONE. S1-06 is the only B04 task now IN_PROGRESS.
- Follow-up: finish Candidate repository status/isolation validation, then execute B04-wide affected and risk regressions.

## S1-06 and B04 final validation

- Date/time: 2026-08-22 18:20 +08:00
- Environment: Windows PowerShell; system Python/pytest/ruff; branch `dev-remem`; HEAD before commit `476cb5a79af7afd15541a0d54aaf01c7d0e308f4`
- Acceptance item: Candidate legal status migration and ordinary retrieval isolation; B04 exit criteria for Working/Episode recovery and visible conflicts
- Commands:
  ```text
  python -m pytest tests/test_vnext_task_state.py tests/test_vnext_event_gateway.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_contracts.py tests/test_vnext_interface.py tests/test_vnext_golden_fixtures.py tests/test_no_production_write_bypass.py -q
  python -m pytest tests/test_safety_pipeline.py -q
  python -m pytest tests/test_safety_contract.py tests/test_safe_errors.py -q
  python -m pytest tests/test_memory_write_contract_schema.py -q -k "capture"
  python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/__init__.py memoryhub/domain/working.py memoryhub/domain/episode.py memoryhub/domain/candidate.py memoryhub/application/__init__.py memoryhub/application/event_gateway.py memoryhub/application/working_service.py memoryhub/application/episode_service.py memoryhub/storage/models.py memoryhub/storage/database.py memoryhub/storage/vnext_repositories.py tests/test_vnext_task_state.py
  python -m compileall -q memoryhub/domain memoryhub/application memoryhub/storage
  git diff --check
  ```
- Result: PASS for B04 functional/risk evidence: affected vNext/working/episode/candidate/gateway/write-bypass suite 65 passed (48 affected regression + 17 final risk subset); Safety Pipeline 46 passed; Safety Contract + Safe Errors 31 passed; legacy write-contract capture 1 passed with 2 deselected; ruff/compileall/diff-check passed. Existing pytest warning: unknown `asyncio_mode`.
- Candidate summary: `ACCUMULATING -> REVIEW -> CONFIRMED` and terminal transition rejection pass; repository `search()` and `list_for_retrieval()` default to an empty result and only an explicit `include_candidates=True` review path can inspect Candidate rows; tenant/user filters remain mandatory.
- Exit criteria: Working CAS conflicts are explicit; Episode token/version conflicts are explicit; snapshot replay and stale-resource/revalidation outputs are verified; Candidate rows cannot enter ordinary repository retrieval.
- Environment PARTIAL evidence: the broader affected command including `tests/test_user_isolation.py` reached 48 passed and 6 setup-time failures because optional `rank-bm25` is not installed; separate legacy safety/write command reached 78 passed and 2 setup-time failures because the host denied pytest `tmp_path` lock creation under `C:\Users\11929\AppData\Local\Temp\pytest-of-11929`. No B04 assertion failure resulted.
- Artifact/report/trace: `memoryhub/domain/working.py`, `memoryhub/application/working_service.py`, `memoryhub/domain/episode.py`, `memoryhub/application/episode_service.py`, `memoryhub/domain/candidate.py`, `memoryhub/storage/vnext_repositories.py`, `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_task_state.py`
- Acceptance: S1-04, S1-05, and S1-06 DONE; B04 functional exit criteria PASS with environment limitations explicitly retained.
- Follow-up: update batch continuity files, stage only B04 artifacts plus required continuity files, then create the single local B04 commit.

## Bootstrap

- Date/time: 2026-08-22 13:10 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: 读取方案、核对 Git 现场、识别缺失连续性文件
- Command:
  ```text
  Get-Date -Format o; Get-Location; git branch --show-current; git rev-parse HEAD; git status --short; git log -8 --oneline --decorate
  rg --files -g 'AGENTS.md' -g '!**/.git/**'
  ```
- Result: PASS
- Summary: 无适用 `AGENTS.md`；方案目录未跟踪；`codex_execution/` 不存在；当前分支和 HEAD 已记录。
- Artifact/report/trace: `STATE.md`, `TASK_BOARD.md`, `DECISIONS.md`, `SESSION_LOG.md`
- Follow-up: 执行 S0-01；完成后追加定向契约测试结果。

## S0-01

- Date/time: 2026-08-22 13:22 +08:00
- Environment: Windows PowerShell; system `python`, pytest
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: vNext 术语枚举与旧值映射
- Command:
  ```text
  python -m pytest tests/test_vnext_contracts.py -q
  ```
- Result: PASS
- Summary: 10 passed；覆盖正交维度、7 类 Intent 唯一性、旧 level/type/status 映射、未知值 fail-closed、Scope 顺序和 Formation/Evolution 分离。环境产生 1 个既有 `asyncio_mode` 未识别警告。
- Artifact/report/trace: `memoryhub/domain/contracts.py`, `docs/spec/VNEXT_GLOSSARY.md`, `tests/test_vnext_contracts.py`
- Follow-up: 运行旧事件/写入 Schema 回归及 lint；通过后完成 S0-01。

### S0-01 checkpoint: regression/lint attempt

- Date/time: 2026-08-22 13:24 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Commands:
  ```text
  python -m pytest tests/test_ingestion_schema.py tests/test_memory_write_contract_schema.py -q
  python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/__init__.py tests/test_vnext_contracts.py
  ```
- Result: PARTIAL
- Summary: ingestion/schema tests reached 22 passed but 2 tests errored before execution because the host pytest temp lock under `C:\Users\11929\AppData\Local\Temp\pytest-of-11929` denied permission; this is an environment issue, not a test assertion. Ruff found one import-order issue in the new `memoryhub/domain/__init__.py`, now corrected.
- Artifact/report/trace: command output retained in session; no production data changed
- Follow-up: rerun pytest with an explicit workspace basetemp and rerun ruff.

### S0-01 final checkpoint

- Date/time: 2026-08-22 13:29 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Commands:
  ```text
  python -m pytest tests/test_vnext_contracts.py tests/test_ingestion_schema.py -q
  python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/__init__.py tests/test_vnext_contracts.py
  ```
- Result: PASS
- Summary: 31 tests passed；ruff passed。唯一警告为现有 pytest 配置 `asyncio_mode` 未识别。S0-01 验收项逐条满足：正交枚举、7 类 Intent 唯一、旧值显式映射、未知值 fail-closed、术语文档存在。
- Artifact/report/trace: `memoryhub/domain/contracts.py`, `docs/spec/VNEXT_GLOSSARY.md`, `tests/test_vnext_contracts.py`
- Follow-up: `S0-02` 已领取；开始架构 ADR。

## S0-02

- Date/time: 2026-08-22 13:37 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: 架构决策记录、Authority/Projection、Canonical Path、禁止依赖、兼容/回滚策略
- Command:
  ```text
  python -m pytest tests/test_vnext_architecture_adr.py tests/test_vnext_contracts.py -q
  python -m ruff check tests/test_vnext_architecture_adr.py memoryhub/domain/contracts.py memoryhub/domain/__init__.py tests/test_vnext_contracts.py
  ```
- Result: PASS
- Summary: 13 tests passed；ruff passed；1 个既有 `asyncio_mode` 配置警告。ADR 已按当前代码事实记录现有写入、检索、Projection 和兼容边界，并冻结禁止调用关系与 rollout/rollback 语义。
- Artifact/report/trace: `docs/design/adr/ADR-vnext-memory-architecture.md`, `tests/test_vnext_architecture_adr.py`
- Follow-up: `S0-03` 已领取，开始实现 vNext 数据契约。

## S0-03

- Date/time: 2026-08-22 13:45 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: Event、Working、Episode、Candidate、Long-Term、Evidence、Lineage、Activation 的 vnext/v1 Pydantic 契约与 JSON fixture
- Command:
  ```text
  python -m pytest tests/test_vnext_contracts.py tests/test_ingestion_schema.py tests/test_safety_contract.py -q
  python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/__init__.py tests/test_vnext_contracts.py
  ```
- Result: PASS
- Summary: 58 tests passed；ruff passed；1 个既有 `asyncio_mode` 配置警告。核心对象均带 tenant/user、schema/content version、时间与治理字段；fixture 往返和 extra/version 拒绝通过；Evidence 使用 `content_ref`。
- Artifact/report/trace: `memoryhub/domain/contracts.py`, `docs/spec/VNEXT_DATA_CONTRACT.md`, `tests/fixtures/vnext/minimal_contracts.json`, `tests/test_vnext_contracts.py`
- Follow-up: `S0-04` 已领取，开始 API DTO 契约。

## S0-04

- Date/time: 2026-08-22 13:54 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: write/retrieve/resume/forget/diagnostic API DTO、稳定错误码、幂等/确认、Authority checked、分页/version 和兼容响应
- Command:
  ```text
  python -m pytest tests/test_vnext_interface.py tests/test_vnext_contracts.py tests/test_ingestion_schema.py -q
  python -m ruff check memoryhub/adapter/vnext_schemas.py tests/test_vnext_interface.py memoryhub/domain/contracts.py memoryhub/domain/__init__.py tests/test_vnext_contracts.py
  ```
- Result: PASS
- Summary: 38 tests passed；ruff passed；1 个既有 `asyncio_mode` 配置警告。Forget 缺 selector/缺 confirm、空 Query 状态检索、部分结果/错误码、旧响应形状适配均有测试。
- Artifact/report/trace: `memoryhub/adapter/vnext_schemas.py`, `docs/spec/VNEXT_INTERFACE.md`, `tests/test_vnext_interface.py`
- Follow-up: `S0-05` 已领取，开始迁移 dry-run。

## S0-05

- Date/time: 2026-08-22 13:59 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff; repository has no default `data/memoryhub.db`
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: migration dry-run, count/hash/tenant/scope/invalid/review report, no irreversible delete, compatibility/rollback path
- Commands:
  ```text
  python -m pytest tests/test_vnext_migration.py -q
  python -m ruff check scripts/migrate_vnext.py tests/test_vnext_migration.py memoryhub/adapter/vnext_schemas.py tests/test_vnext_interface.py
  python scripts/migrate_vnext.py --dry-run --report evaluation/results/vnext_migration/dry_run.json
  ```
- Result: PASS
- Summary: 3 tests passed；ruff passed；CLI exit 0。dry-run 报告明确 `database_exists=false`、`source_records=0`、`read_only_scan=true`、`no_irreversible_delete=true`，未把缺失数据库伪造成迁移成功。
- Artifact/report/trace: `scripts/migrate_vnext.py`, `docs/spec/VNEXT_MIGRATION.md`, `tests/test_vnext_migration.py`, `evaluation/results/vnext_migration/dry_run.json`
- Follow-up: apply/真实旧数据演练延后 S5-06；`S0-06` 已领取。

## S0-06

- Date/time: 2026-08-22 14:07 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Branch/HEAD: `dev-remem` / `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: legacy/shadow/dual-read/canary/vnext modes, production Policy/Authority invariants, explicit config
- Commands:
  ```text
  python -m pytest tests/test_vnext_feature_flags.py tests/test_config_runtime_gate.py -k "not TestLoadConfig" -q
  python -m ruff check memoryhub/config.py tests/test_vnext_feature_flags.py
  python -c "from memoryhub.config import load_config; c=load_config('config.example.yaml'); print(c.vnext.mode, c.vnext.canary_percent, c.vnext.policy_required, c.vnext.authority_single_writer)"
  ```
- Result: PASS
- Summary: 35 passed、6 个旧 tmp_path 配置用例 deselected；ruff passed；样例加载输出 `legacy 0 True True`。五个模式可构造，canary 只接受 5/25/50/100，生产拒绝 Policy bypass/多 writer。
- Artifact/report/trace: `memoryhub/config.py`, `config.example.yaml`, `tests/test_vnext_feature_flags.py`
- Follow-up: `S0-07` 已领取；开始基线报告。

### S0-06 failed environment attempt

- Date/time: 2026-08-22 14:05 +08:00
- Command: `python -m pytest tests/test_vnext_feature_flags.py tests/test_config_runtime_gate.py -q`
- Result: PARTIAL
- Summary: 36 passed、5 errors；5 个错误均在旧 `TestLoadConfig` 的 `tmp_path` fixture 创建阶段因主机 pytest temp lock PermissionError，未进入断言。保留此失败证据；选择性回归已通过。

## S0-07

- Date/time: 2026-08-22 14:03 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff; branch `dev-remem`; HEAD `aa24ed029f9adc33f92311e2b106a39ee218a496`
- Acceptance item: repeatable baseline with commit/config/model/index/dataset hashes, test result, retrieval metrics, latency and write-bypass scan
- Commands:
  ```text
  python -m ruff check evaluation/run_vnext_baseline.py tests/test_vnext_baseline.py
  python -m pytest tests/test_vnext_baseline.py -q
  python evaluation/run_vnext_baseline.py --output-dir evaluation/results/vnext_baseline
  python -m pytest tests/test_no_production_write_bypass.py tests/test_validate_retrieval_dataset.py tests/test_vnext_baseline.py tests/test_vnext_contracts.py tests/test_vnext_interface.py -q
  ```
- Result: PASS；ruff passed；baseline unit tests 2 passed；组合回归 58 passed；baseline CLI exit 0，报告 status=PASS。
- Summary: 数据集校验 PASS（108 memories/30 queries，0 errors，1 warning）；write-bypass scan PASS；原 Hybrid 评测尝试失败证据保留（环境缺少 `rank-bm25`，同时 `faiss-cpu` 不可用），runner 使用明确标记的纯 Python vector-only fallback 生成真实指标，不伪造 Hybrid 指标。Vector baseline: Recall@5=0.2167、Recall@10=0.2333、MRR=0.0483、cross-user rate=0.0200；latency p50=9.563ms、p95=10.014ms、p99=10.092ms、max=10.120ms。
- Artifact/report/trace: `evaluation/run_vnext_baseline.py`, `tests/test_vnext_baseline.py`, `evaluation/results/vnext_baseline/baseline.json`, `evaluation/results/vnext_baseline/dataset_validation.json`
- Follow-up: `S0-08` 可领取；Gate S0 继续保持 TODO，等待 Golden fixtures/契约测试完成。

### S0-07 failed checkpoints

- First CLI attempt: `ModuleNotFoundError: No module named 'evaluation'`; fixed by adding repository root to runner import path.
- Second CLI attempt: Hybrid evaluator failed because `rank-bm25` was unavailable; dependency-free fallback initially failed because `faiss-cpu` was unavailable. Both failures remain represented in the final report's `hybrid_attempt` evidence; final pure-Python fallback passed.

## S0-08

- Date/time: 2026-08-22 14:03 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff
- Acceptance item: Golden fixtures and contract tests for normal, conflict, sensitive, duplicate, expired version, deletion and degraded response
- Commands:
  ```text
  python -m pytest tests/test_vnext_golden_fixtures.py -q
  python -m pytest tests/test_vnext_golden_fixtures.py tests/test_vnext_contracts.py tests/test_vnext_interface.py -q
  python -m ruff check tests/test_vnext_golden_fixtures.py memoryhub/domain/contracts.py memoryhub/adapter/vnext_schemas.py
  ```
- Result: PASS；6 定向测试通过；23 项 Golden/数据契约/API 组合回归通过；ruff passed；fixture SHA-256 校验匹配。
- Summary: `vnext/golden/v1` 覆盖正常 Authority-checked 请求、冲突 Candidate REVIEW、敏感事件 content_ref/REVIEW、重复幂等、旧 API 版本 fail-closed、DELETED 检索隔离和 PARTIAL 降级响应；没有真实 secret/raw sensitive content。
- Artifact/report/trace: `tests/fixtures/vnext/golden_scenarios.json`, `tests/fixtures/vnext/SHA256SUMS.txt`, `tests/test_vnext_golden_fixtures.py`, `docs/spec/VNEXT_GOLDEN_FIXTURES.md`
- Follow-up: S0 Gate 核验通过；领取 S1-01。

## S0 Gate

- Date/time: 2026-08-22 14:03 +08:00
- Commands:
  ```text
  python -m pytest tests/test_vnext_architecture_adr.py tests/test_vnext_contracts.py tests/test_vnext_interface.py tests/test_vnext_migration.py tests/test_vnext_feature_flags.py tests/test_vnext_golden_fixtures.py tests/test_vnext_baseline.py -q
  python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/__init__.py memoryhub/adapter/vnext_schemas.py memoryhub/config.py scripts/migrate_vnext.py evaluation/run_vnext_baseline.py tests/test_vnext_architecture_adr.py tests/test_vnext_contracts.py tests/test_vnext_interface.py tests/test_vnext_migration.py tests/test_vnext_feature_flags.py tests/test_vnext_golden_fixtures.py tests/test_vnext_baseline.py
  ```
- Result: PASS；44 tests passed，ruff passed，1 个既有 `asyncio_mode` 配置警告；S0 术语/API/Flag/迁移/基线/Golden Gate 全部有证据。
- Safety note: S0-07 Hybrid 可选依赖缺失仍是报告中的环境事实，不是安全旁路；vector-only fallback 和跨用户率检查已通过。
- Artifact/report/trace: `EVIDENCE.md#s0-01`～`EVIDENCE.md#s0-08`, `evaluation/results/vnext_baseline/baseline.json`
- Follow-up: S1-01 新表/Schema 扩展；S1 Gate 尚未开始。

## S1-01

- Date/time: 2026-08-22 14:03 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff; SQLite/SQLAlchemy
- Acceptance item: seven vNext Authority/task/retrieval tables; tenant isolation; unique keys/indexes; version/status checks; repeatable additive migration
- Commands:
  ```text
  python -m pytest tests/test_vnext_storage_schema.py -q
  python -m pytest tests/test_memory_write_contract_schema.py -q -k "capture"
  python -m ruff check memoryhub/storage/database.py memoryhub/storage/models.py tests/test_vnext_storage_schema.py
  ```
- Result: PASS；3 schema tests passed；旧写入契约非 tmp_path 用例 1 passed（2 deselected）；storage database/models/tests ruff passed；唯一警告为既有 `asyncio_mode` 未识别。
- Summary: fresh schema 两次 `init_schema()` 可重复；legacy minimal SQLite 表可增量获得 vNext columns/indexes；tenant/user 字段覆盖 7 张新表；Episode seq、idempotency key、activation version 和 candidate status/formation check 已由约束覆盖；Event/Evidence/Lineage/Outbox 增加治理/版本/投影字段。首次测试暴露并修复重复 init 未 dispose engine 导致 Windows SQLite 文件锁。
- Artifact/report/trace: `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_storage_schema.py`, `docs/spec/VNEXT_STORAGE_SCHEMA.md`
- Follow-up: S1-02 Repository 与事务测试；full old tmp_path regression 的 host permission failure 已保留，不影响本任务专用 schema 证据。

### S1-01 failed checkpoints

- Initial schema test: 2 errors before assertions because pytest/TemporaryDirectory-created paths could not be opened/cleaned on this host (`WinError 5`); test switched to an explicit repository report path and now passes.
- Idempotent-run checkpoint: SQLite file remained locked after repeated `Database.init_schema()`; fixed by disposing the previous SQLAlchemy engine before recreating it, then 3 schema tests passed.
- Existing regression command with pytest basetemp: 1 passed and 6 errors/cleanup failure from host directory permission; no assertion failure in the new schema tests.

## S1-02

- Date/time: 2026-08-22 14:03 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff; SQLite/SQLAlchemy
- Acceptance item: Working CAS, Episode monotonic seq, Candidate status transitions, Evidence deduplication and Activation writes with tenant isolation
- Commands:
  ```text
  python -m pytest tests/test_vnext_repositories.py -q
  python -m pytest tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_contracts.py tests/test_vnext_interface.py -q
  python -m pytest tests/test_memory_write_contract_schema.py -q -k "capture"
  python -m ruff check memoryhub/storage/database.py memoryhub/storage/models.py memoryhub/storage/vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_repositories.py
  ```
- Result: PASS；5 定向测试通过；Repository + storage + vNext contract/interface 25 passed；旧写入契约非 tmp_path 用例 1 passed（2 deselected）；ruff passed；1 个既有 `asyncio_mode` 警告。
- Summary: Working stale version raises `VersionConflictError` without overwrite；Episode append assigns 1,2 and rejects stale expected seq；Candidate `ACCUMULATING→REVIEW→CONFIRMED` passes and terminal reverse transition fails；same Evidence retry returns existing ID with `created=False` and only `content_ref`；Activation duplicate same version fails while newer version/other tenant succeeds。
- Artifact/report/trace: `memoryhub/storage/vnext_repositories.py`, `tests/test_vnext_repositories.py`
- Follow-up: S1-03 Event Gateway；Policy/identity/Scope/幂等/commit orchestration must call these repositories through canonical write。

### S1-02 failed checkpoints

- Initial ruff attempt found one unused `IdempotencyRecordRow` import；removed and reran with all affected storage files passing。
- Existing full `tests/test_memory_write_contract_schema.py`/projection regression remains unable to create pytest `tmp_path` on this host；non-temp legacy contract coverage passed and the new repository suite uses an explicit repository DB path。

## S1-03 implementation checkpoint

- Date/time: 2026-08-22 16:22 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff; SQLite/SQLAlchemy
- Acceptance item: Event Gateway ordered ingress, Policy action handling, tenant-scoped idempotency and atomic commit
- Commands:
  ```text
  python -m pytest tests/test_vnext_event_gateway.py -q
  python -m ruff check memoryhub/application/event_gateway.py tests/test_vnext_event_gateway.py
  ```
- Result: PASS；11 tests passed；ruff passed；唯一警告为既有 pytest 配置 `asyncio_mode` 未识别。
- Summary: Envelope 类型校验后依次执行 identity、Scope、Policy；REVIEW/DROP 在持久化前停止；MASK 若未改变 payload 则 fail-closed，只有 Policy 返回的净化 payload 才提交；幂等键按 tenant 隔离；Event ID 冲突按数据库全局主键范围检查；唯一键并发竞争回滚后重读为 IDEMPOTENT/CONFLICT，不向调用方泄漏 `IntegrityError`。重复并发提交实测 1 个 COMMITTED、7 个 IDEMPOTENT，Event 与 IdempotencyRecord 各 1 行。
- Sensitive-data evidence: REVIEW/DROP 与未净化 MASK 均未写 `events` 或 `idempotency_records`；IdempotencyRecord 只保存 request hash、event/trace 引用，不保存 payload；Gateway 无日志/队列写入。
- Artifact/report/trace: `memoryhub/application/event_gateway.py`, `tests/test_vnext_event_gateway.py`, `docs/spec/VNEXT_EVENT_GATEWAY.md`
- Follow-up: 运行 S1-03 受影响 vNext 回归、write-bypass/safety 风险测试及批次级验收；未完成前保持 S1-03 IN_PROGRESS。

## S1-03 regression checkpoint

- Date/time: 2026-08-22 16:29 +08:00
- Environment: Windows PowerShell; system `python`, pytest; SQLite/SQLAlchemy
- Commands:
  ```text
  python -m pytest tests/test_vnext_event_gateway.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_contracts.py tests/test_vnext_interface.py tests/test_vnext_golden_fixtures.py tests/test_no_production_write_bypass.py -q
  python -m pytest tests/test_safety_pipeline.py tests/test_safety_gate.py tests/test_safety_audit_log.py tests/test_safety_memory_write.py tests/test_safety_contract.py tests/test_safe_errors.py tests/test_memory_write_contract_schema.py -q
  ```
- Result: 受影响 vNext 回归 PASS，44 passed，1 个既有 `asyncio_mode` 警告。风险组合 PARTIAL，81 passed、1 skipped、70 setup errors；70 errors 均发生在 pytest fixture setup，主机拒绝创建 `C:\Users\11929\AppData\Local\Temp\pytest-of-11929\pytest-*\\.lock`，没有业务断言失败。
- Summary: Event Gateway 与既有 safety/write-bypass 边界没有回归；临时目录权限问题与 B03 代码无因果关系，拆分不依赖 `tmp_path` 的安全契约/错误测试继续验证。
- Artifact/report/trace: `tests/test_vnext_event_gateway.py`, `tests/test_vnext_repositories.py`, `tests/test_vnext_storage_schema.py`, `tests/test_vnext_contracts.py`, `tests/test_vnext_interface.py`, `tests/test_vnext_golden_fixtures.py`, `tests/test_no_production_write_bypass.py`
- Follow-up: 运行不依赖 pytest 临时目录的安全风险测试；若仍受环境阻断，保留精确命令/结果并按事实决定是否可验收。

## S1-03 safety risk checkpoint

- Date/time: 2026-08-22 16:34 +08:00
- Environment: Windows PowerShell; system `python`, pytest
- Commands:
  ```text
  python -m pytest tests/test_safety_pipeline.py -q
  python -m pytest tests/test_safety_contract.py tests/test_safe_errors.py -q
  python -m pytest tests/test_memory_write_contract_schema.py -q -k "capture"
  python -m pytest --basetemp .pytest-b03-safety-basetemp tests/test_safety_gate.py tests/test_safety_audit_log.py tests/test_safety_memory_write.py tests/test_memory_write_contract_schema.py -q
  ```
- Result: PASS（可执行拆分）：Safety Pipeline 46 passed；Safety Contract + Safe Errors 31 passed；legacy write contract capture 1 passed、2 deselected。带工作区 basetemp 的组合仍因该目录权限在 pytest session cleanup 阶段报 `WinError 5`，且其业务用例 setup 同样受目录访问限制；无 B03 业务断言失败。
- Summary: 既有 Safety Pipeline、契约、safe-error、Evidence schema 回归通过；剩余文件系统审计/隔离用例明确记录为环境 PARTIAL，不作为 B03 Event Gateway 通过依据。
- Artifact/report/trace: `tests/test_safety_pipeline.py`, `tests/test_safety_contract.py`, `tests/test_safe_errors.py`, `tests/test_memory_write_contract_schema.py`
- Follow-up: 进行最终 B03 全量验收、diff/产物归属审查；若无新增业务失败，将三项任务写 DONE、B04 写 READY 后只创建一次提交。

## S1-03 final validation checkpoint

- Date/time: 2026-08-22 16:48 +08:00
- Environment: Windows PowerShell; system `python`, pytest, ruff; SQLite/SQLAlchemy
- Commands:
  ```text
  python -m pytest tests/test_vnext_event_gateway.py -q
  python -m pytest tests/test_vnext_event_gateway.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_contracts.py tests/test_vnext_interface.py tests/test_vnext_golden_fixtures.py tests/test_no_production_write_bypass.py -q
  python -m ruff check memoryhub/application/event_gateway.py tests/test_vnext_event_gateway.py
  python -m ruff check memoryhub/application/event_gateway.py memoryhub/application/__init__.py memoryhub/storage/database.py memoryhub/storage/models.py memoryhub/storage/vnext_repositories.py tests/test_vnext_event_gateway.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py
  python -m compileall -q memoryhub/application memoryhub/storage
  git diff --check
  ```
- Result: PASS；Event Gateway 11 passed；受影响 vNext 回归 45 passed；ruff、compileall、diff-check passed；唯一测试警告为既有 `asyncio_mode` 未识别。
- Summary: 修复 SQLite 并发跨表读偏差：同租户同幂等键的已存在 Event 不再直接报 Event ID 冲突，而是在当前 Session 结束后重读 IdempotencyRecord；并发重复提交维持 1 个 COMMITTED、其余 IDEMPOTENT。Evidence/Frequency 不由 Gateway 触碰，重复提交回归保持既有 Evidence=1、Candidate frequency=3。
- Acceptance: Policy 在 Event/幂等提交前生效；敏感 REVIEW/DROP/未净化 MASK 不写 Event、队列或幂等记录；tenant-scoped idempotency、全局 Event ID、事务回滚和并发竞争均有证据；没有生产写旁路变更。
- Follow-up: 只读审查 Git diff/暂存清单；将 S1-01/S1-02/S1-03 置 DONE、B03 置 DONE、B04 置 READY，写入 `SELF (Batch-ID: B03)`，然后只创建一次本地提交。
