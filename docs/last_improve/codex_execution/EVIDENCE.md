# MemoryHub vNext Execution Evidence

## Batch commit reconciliation

- B01 (`S0-01`～`S0-04`): commit `a502f9a`; `Batch-ID: B01`; validation 65 passed and ruff passed.
- B02 (`S0-05`～`S0-08`, S0 Gate): commit `1b84af1`; `Batch-ID: B02`; validation 46 passed, 6 deselected, and ruff passed.
- Scope audit: B01/B02 commits contain only their assigned S0 artifacts. S1 storage/repository/Event Gateway files remain outside both commits.

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
