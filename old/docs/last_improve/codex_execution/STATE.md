# MemoryHub vNext Codex Execution State

## B17 start reconciliation — 2026-08-25

- Current batch: B17 (`S5-05` through `S5-08`), status `IN_PROGRESS`; current task: S5-05 `IN_PROGRESS`.
- Repository truth: branch `dev-remem`, HEAD `330f4d27f04b0729a53a2b63b1ab5747eb6f6dcb` (`feat(vnext): complete B16 s5 benchmark dashboard`, trailer `Batch-ID: B16`). Tracked worktree diff is empty.
- Existing untracked `evaluation/results/*.db`/report artifacts and host-denied pytest temporary directories are preserved and excluded from this batch commit.
- B17 was READY with no in-progress task; S5-05 is the smallest dependency-satisfied task. S3-08, S5-01 and prior S5 evidence are valid DONE; S5-06/S5-07/S5-08 remain untouched.
- No applicable `AGENTS.md` was found. Boundary: only S5-05 through S5-08 plus required continuity/spec/test/report artifacts; do not execute, claim, research or modify S5-09/S5-10 or B18.
- Exact next action: implement redacted Agent Usage/Utility Feedback Shadow and focused safety tests; shadow output must not mutate Authority,正文 or lifecycle state.

## S5-05 checkpoint — 2026-08-25

- Status: DONE. Added `memoryhub/application/feedback_service.py` with typed `INCLUDED`, `REFERENCED`, `ACTION_INFLUENCED`, `OUTCOME` and `CORRECTION` signals, redacted Trace spans, and deterministic non-authoritative utility proposals.
- Retrieval integration records INCLUDED/REFERENCED usage after Activation creation when an optional feedback shadow is supplied; no Authority repository, content, status or version mutation is reachable from the shadow.
- Validation: feedback/retrieval/formation Trace set 16 passed; safety/contract/error/write-bypass risk set 83 passed; scoped ruff, compileall and `git diff --check` passed.
- Evidence: `EVIDENCE.md#s5-05-checkpoint`.
- Next task: S5-06 `IN_PROGRESS`; implement apply-safe legacy migration, checkpoint/backup, count/hash/tenant/scope/version/evidence validation and explicit REVIEW output.

## S5-06 checkpoint — 2026-08-25

- Status: DONE. `scripts/migrate_vnext.py` now supports explicit `--apply` only after a fresh read-only scan, optional approved input hash, database backup, atomic Authority-compatible metadata update, SQLite checkpoint and external checkpoint JSON.
- Eligible rows preserve old tables and receive a governed `vnext_authority` envelope; missing tenant/scope/version/evidence rows remain untouched in `REVIEW`; deleted rows cannot be promoted or revived. Projection rebuild remains deferred until Authority validation.
- Validation: migration focused tests 4 passed; migration ruff/compileall passed; dry-run CLI exited 0 and emitted the existing empty-database report with read-only/no-delete/uncertain-data safeguards.
- Evidence: `EVIDENCE.md#s5-06-checkpoint`.
- Next task: S5-07 `IN_PROGRESS`; implement redacted Formation Shadow/Retrieval dual-read comparison and cutover report without changing returned legacy results.

## S5-07 checkpoint — 2026-08-25

- Status: DONE. Added `memoryhub/application/shadow_read_service.py` and `evaluation/run_vnext_shadow.py`; Formation Shadow is reused without Authority writes, while Retrieval dual-read executes vNext only as an observed branch and always returns the legacy response.
- Reports classify result-set/order/version/scope/read-error differences and count Policy/Forget leaks using ID hashes and redacted Trace metadata only. The deterministic CLI artifact is `evaluation/results/vnext_shadow/shadow.json`.
- Validation: Shadow/Formation/Retrieval/entrypoint set 36 passed; safety/contract/error/Forget/write-bypass set 86 passed; scoped ruff/compileall passed; Shadow CLI exited 0.
- Evidence: `EVIDENCE.md#s5-07-checkpoint`.
- Next task: S5-08 `IN_PROGRESS`; implement 5%→25%→50%→100% rollout gates, per-level observation evidence, explicit rollback window and read-only rollback switch.

## S5-08 and B17 final acceptance — 2026-08-25

- S5-08 DONE. Added `RolloutController`, explicit `VNextConfig` observation/rollback settings, rollout contract, deterministic cutover/rollback runner and `evaluation/results/vnext_shadow/rollout.json`.
- Rollout is fixed at legacy/0 → canary/5 → canary/25 → canary/50 → vnext/100; no skip is allowed. Every level requires an observation window and zero Policy Leakage, cross-tenant results, Forget residuals and observed errors. CUTOVER and ROLLBACK audits include window IDs, metrics and rollback minutes.
- B17 acceptance: S5-05 Usage/Feedback Shadow, S5-06 migration/REVIEW validation, S5-07 Formation/Retrieval Shadow dual-read, and S5-08 gated rollout/rollback all meet their exit criteria. Shadow and dual-read never write Authority正文/状态; migration preserves old tables and does not revive uncertain/deleted records.
- Final validation: B17 affected suite 101 passed; safety/contract/error/Forget suite 80 passed; ruff, compileall, `git diff --check`, Shadow runner and rollout runner passed. Shadow artifacts contain no raw query/content/payload fields.
- Batch status: B17 DONE; B18 READY only. Commit reference must be `SELF (Batch-ID: B17)` in the single B17 commit. Do not execute or modify S5-09/S5-10/B18.

## B16 start reconciliation — 2026-08-25

- Current batch: B16 (`S5-01` through `S5-04`), status `IN_PROGRESS`; current task: S5-01 `IN_PROGRESS`.
- Repository truth: branch `dev-remem`, HEAD `5841161ef9acf2457e26f619db61c0fc2a5e52e5` (`feat(vnext): complete B15 s4 reliability gate`, trailer `Batch-ID: B15`). BATCH_BOARD's old B15 commit-plan text was stale; no source change from B15 is pending.
- Existing untracked SQLite reports in `evaluation/results/` are test artifacts and are preserved. Host-denied pytest temporary directories are also preserved and excluded.
- Dependencies S2-09, S3-08 and S4-08 are DONE with valid Trace/metrics evidence. No B16 task was already in progress, so the smallest authorized task S5-01 is claimed.
- Boundary: only S5-01 through S5-04 and required continuity/spec/test artifacts. B17/S5-05 or later must not be read for implementation, claimed, tested, or modified.
- Exact next action: extend the redacted Trace model/store with the five typed chains, deterministic sampling and retention policy, then add focused safety/association tests.

## S5-01 checkpoint — 2026-08-25

- Status: DONE. `TraceSpan`/`TraceStore` now support the FORMATION, EVOLUTION, RETRIEVAL, FORGET and INFRASTRUCTURE chains, with trace/task/event/memory/query association indexes.
- Normal application traces use deterministic SHA-256 10% sampling and seven-day retention; high/critical, failure/denial and Forget traces are mandatory with 30-day retention. Direct/test stores keep 100% sampling for backward-compatible diagnostics.
- Recursive Trace validation rejects raw content-bearing fields; Forget stores only a hash of affected IDs. App wiring shares the redacted TraceStore across Retrieval, Forget, Diagnostics and Projection Outbox.
- Evidence: `EVIDENCE.md#s5-01-checkpoint`; focused trace/formation/retrieval/Forget/reliability suite: 38 passed; ruff, compileall and diff check passed.
- Next task: S5-02 `IN_PROGRESS`; implement the four-layer reproducible Benchmark runner.

## S5-02 checkpoint — 2026-08-25

- Status: DONE. Added `evaluation/run_vnext_eval.py`, the single-command four-layer runner for Formation, Retrieval, Infrastructure and E2E evaluation; emitted `evaluation/results/vnext_benchmark.json`.
- Report pins vNext dataset SHA-256 values, seed 42, mock embedding/model version, formation prompt version, retrieval weight version and runtime environment. The E2E path uses a fixed mock Milvus/embedding setup without hidden external fallback.
- Evidence: `EVIDENCE.md#s5-02-checkpoint`; focused benchmark/evaluator/reliability/E2E suite: 29 passed; the runner command produced all four layers with infrastructure pass and retrieval scope leak rate 0.0; ruff, compileall and diff check passed.
- Next task: S5-03 `IN_PROGRESS`; execute four-system comparison and one-mechanism-at-a-time ablations using the same benchmark manifest.

## S5-03 checkpoint — 2026-08-25

- Status: DONE. Added `evaluation/run_vnext_comparison.py` and `evaluation/results/vnext_final/comparison.json` for No Memory, Flat RAG, Original and vNext under the same fixed mock model, offline tools, dataset budgets and five repeated measurements.
- The report provides mean, variance and two-sided 95% confidence intervals for task success, policy-leak rate, MRR, Context tokens and latency; it contains aggregate/query IDs only and is explicitly redacted.
- Controlled outcome: Flat RAG and Original each have policy leak rate 0.1; vNext is 0.0 at task success 1.0 and MRR 1.0. The ablation section independently removes router, scope resolver, reranker and Context budget without combining removals.
- Evidence: `EVIDENCE.md#s5-03-checkpoint`; comparison/retrieval focused suite: 11 passed; comparison command completed; ruff, compileall and diff check passed.
- Next task: S5-04 `IN_PROGRESS`; deliver the four controlled, default-redacted dashboard pages wired to the diagnostics/benchmark data.

## S5-04 and B16 final acceptance — 2026-08-25

- S5-04 DONE: `DashboardService` serves Explorer, Evolution, Retrieval Debugger and Benchmark projections only after management authorization; every result is redacted and every access is audited. The Benchmark view strips per-query samples before presentation.
- Desktop client registers four cross-navigable vNext Dashboard pages and CMake sources. All views visibly state default redaction and management authorization; the local environment lacks `cmake`, so native Qt build verification is PARTIAL, not a source/test failure.
- B16 acceptance: S5-01 Trace safety/correlation, S5-02 one-command four-layer benchmark, S5-03 controlled four-system comparison/ablation, and S5-04 redacted permission-controlled Dashboard all meet their exit criteria. B17 is READY only; do not start it in this session.
- Validation: focused Dashboard/Trace/Benchmark/Comparison tests passed; safety/write-bypass suite 83 passed; ruff, compileall and diff check passed. The attempted all-file `test_vnext_*.py` invocation exceeded the host command window and remains PARTIAL.
- Exact next action: stage only B16 code/tests/docs/reports/continuity artifacts, make the one local `Batch-ID: B16` commit, read-only verify HEAD, then stop and hand off B17.

## B15 start reconciliation — 2026-08-25

- Current batch: B15 (`S4-07` to `S4-08` plus S4 Gate), status `IN_PROGRESS`.
- Branch/HEAD: `dev-remem` / `d0ffff4745c3094a8437006fb2e7a5c38e5fd0e1`.
- Existing untracked `evaluation/results/*.db` artifacts are preserved; no source diff was present at start.
- S4-01 through S4-06 are DONE with evidence. No task was already IN_PROGRESS, so S4-07 is claimed.
- Scope boundary: only S4-07, S4-08, and S4 Gate. B16/S5 must not be executed or modified.
- Exact next action: add and validate the seven-case fault-injection matrix.

## S4-07 checkpoint — 2026-08-25

- Status: DONE. Added `tests/test_vnext_reliability.py` and `evaluation/run_reliability_eval.py`.
- Matrix covers vector timeout, duplicate delivery, worker crash, pre/post commit crash, stale cache, index corruption, and duplicate event.
- Evidence: focused matrix `9 passed`; evaluation runner emitted `evaluation/results/vnext_reliability_report.json`; targeted ruff, compileall, and diff-check passed.
- Next task: S4-08 IN_PROGRESS; add Infrastructure Trace and reliability metrics integration/evidence.

## S4-08 and S4 Gate checkpoint — 2026-08-25

- S4-08 DONE: metrics cover Write/Search/Context latency, Projection lag, Recovery time, Repair rate, Forget success, and residual retrieval; redacted Infrastructure Trace spans are supported and Outbox worker outcomes are emitted.
- Evidence: vNext regression 270 passed; S4 risk/recovery set 109 passed; projection rebuild/Authority write set 15 passed; targeted ruff, compileall, and diff-check passed.
- S4 Gate PASS: pre-commit atomicity, post-commit Outbox recovery, duplicate/ordering safety, index repair, residual retrieval count 0, and fail-closed stale/deleted reads are evidenced.
- B15 DONE; B16 READY only. No B16 content was executed or modified.

## B14 final validation and acceptance

- Date: 2026-08-24; branch `dev-remem`; B14 was the sole READY batch and no B14 task was previously IN_PROGRESS. No applicable `AGENTS.md` was found; existing untracked `evaluation/results/*.db` artifacts were preserved and excluded.
- Current batch: B14 (`S4-04`～`S4-06`); batch status: DONE; current task: none.
- S4-04 DONE: `ForgetService` writes an Authority `DELETED` tombstone first, enqueues high-priority projection deletes in one transaction, persists state/idempotency/audit metadata, and advances to `VERIFIED` only after outbox success.
- S4-05 DONE: vNext Forget execute/status/history routes enforce explicit confirmation and fail closed for high-risk selectors without management authorization; tenant/user scoping and idempotency are enforced.
- S4-06 DONE: diagnostics cover memory/evidence/lineage/projection/candidate/retrieval trace surfaces, are tenant-scoped, require admin authorization, and redact sensitive fields by default.
- Validation: B14/affected focused suite 43 passed; safety/isolation/write-bypass risk suite 58 passed; ruff, compileall and diff-check passed. Full repository run is PARTIAL because `tests/test_api_acceptance.py::test_api_02_events_write_round_trip` failed its retrieval assertion before any B14-specific failure; this is unrelated to Forget/diagnostics.
- Next batch: B15 READY; next prompt is `docs/last_improve/codex_batches/B15_s4_reliability_gate.md`.
- Boundary: only S4-04～S4-06 and required continuity/API documentation were changed; no S4-07 or later work was executed.

> Last updated: 2026-08-24 16:05 +08:00
> Updated by: Codex session 2026-08-24 (B13)

## B13 final validation and acceptance

- Last updated: 2026-08-24 16:05 +08:00; updated by Codex session 2026-08-24 (B13)
- Current batch: B13 (`S4-01`～`S4-03`); batch status: DONE
- Current task: none; S4-01, S4-02, S4-03 DONE
- Dependencies: S1-01, S1-07 DONE with valid evidence; S3-08 DONE with valid evidence
- Final validation: branch `dev-remem`; HEAD `fc3286f8d3b880659f8ded062ea42cac8d38df9a` (B12 commit `feat(vnext): complete B12 s3 entrypoints eval gate`); B13-scope changes staged; untracked test DB artifacts in `evaluation/results/`; no applicable `AGENTS.md`
- Acceptance:
  - S4-01 Versioned Outbox: `memoryhub/storage/models.py` outbox lease/backoff/dead-letter/delete-priority columns and partial unique index; `memoryhub/storage/memory_metadata.py` claim/mark/replay with lease verification, priority ordering, and dead-letter replay.
  - S4-02 Projection Version & Authority Checked: `PreferenceRow`/`KnowledgeRow` `projection_version`; `AuthorityRepository` preserves projection_version; `ProjectionOutboxWorker` bumps projection_version after success; `CanonicalWriteService` enqueues vector projection; `ScopeResolver` rejects stale projections and triggers repair enqueue; `RetrievalService`/`ContextService` wire authority_checked.
  - S4-03 Point & Offline Repair: `memoryhub/storage/repair.py` `RepairService`/`RepairWorker` diagnose missing/stale/orphan/incompatible and enqueue upsert/delete; `scripts/repair_projections.py` supports `--memory-id`, `--dry-run`, `--run-worker`, tenant/user scan and offline worker.
  - B13 focused tests 13 passed; affected vNext regression 258 passed; safety/contract/error + write-bypass 83 passed; static checks passed; `git diff --check` passed (CRLF warnings only).
  - Batches B01～B12 acceptance remains valid; no S4-04 or later code modified.
- Next batch: B14 READY; next prompt is `docs/last_improve/codex_batches/B14_s4_forget_diagnostics.md`.
- Boundary: only S4-01, S4-02, S4-03; no S4-04 or later batches.
- Commit plan: create exactly one local commit titled `feat(vnext): complete B13 s4 projection repair` with trailer `Batch-ID: B13`; do not push, amend, rebase, or enter B14.

## B12 final validation and acceptance

- Last updated: 2026-08-24 14:00 +08:00; updated by Codex session 2026-08-24 (B12)
- Current batch: B12 (`S3-08`～`S3-10` and S3 Gate); batch status: DONE
- Current task: none; S3-08, S3-09, S3-10 DONE; S3 Gate PASS
- Dependencies: S3-01, S3-02, S3-03 DONE with valid evidence; S2-06 DONE with valid evidence
- Final validation: branch `dev-remem`; HEAD `29ec946a83d10372a2e8fc3fed98254de9b15726` (B11 commit `feat(vnext): complete B11 s3 fusion context`); B12-scope changes staged; untracked test DB artifacts in `evaluation/results/`; no applicable `AGENTS.md`
- Acceptance:
  - S3-08 Activation/Retrieval Log/Trace: `memoryhub/application/retrieval_service.py` orchestrates the full pipeline and records Activation, Retrieval Log and Retrieval Trace.
  - S3-09 Entrypoint convergence: `memoryhub/adapter/vnext_api.py`, `memoryhub/adapter/api.py`, `agent-integration/memoryhub_client/client.py` and `memoryhub/app.py` route `/search`, `/context`, SDK and legacy reads through the single `RetrievalService`.
  - S3-10 Segmented evaluation: `evaluation/metrics/vnext_retrieval_eval.py`, `evaluation/datasets/vnext_retrieval_eval.json`, `tests/test_vnext_retrieval_eval.py` provide Router/Recall/Ranking/Scope/Context metrics and reproducible regression.
  - B12 focused tests 77 passed; affected vNext regression 245 passed; safety/contract/error 77 passed; write-bypass 6 passed; static checks passed; `git diff --check` passed.
  - S3 Gate checklist verified: 7 intents annotated; exact/paraphrase/semantic unified pool/ranking; Candidate/DELETED/SUPERSEDED/other-tenant blocked; budget protects constraints/current step; no per-entrypoint Context assembly.
- Next batch: B13 READY; next prompt is `docs/last_improve/codex_batches/B13_s4_projection_repair.md`.
- Boundary: only S3-08, S3-09, S3-10 and S3 Gate; no S4-01 or later batches.
- Commit plan: create exactly one local commit titled `feat(vnext): complete B12 s3 entrypoints eval gate` with trailer `Batch-ID: B12`; do not push, amend, rebase, or enter B13.

> Last updated: 2026-08-24 13:15 UTC
> Updated by: Codex session 2026-08-24 (B12)

## B12 start reconciliation

- Last updated: 2026-08-24 13:15 UTC; updated by Codex session 2026-08-24 (B12)
- Current batch: B12 (`S3-08`～`S3-10` and S3 Gate); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B12_s3_entrypoints_eval_gate.md`
- Current task: S3-08 IN_PROGRESS; S3-09, S3-10 TODO; S3 Gate TODO
- Dependencies: S3-01, S3-02, S3-03, S3-04, S3-05, S3-06, S3-07 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `29ec946a83d10372a2e8fc3fed98254de9b15726` (B11 commit `feat(vnext): complete B11 s3 fusion context`); working tree has untracked test DB artifacts in `evaluation/results/`; no applicable `AGENTS.md`; BATCH_BOARD was B12 READY and TASK_BOARD had no B12 task in progress
- Reconciliation: B11 commit is present and BATCH_BOARD/TASK_BOARD facts authorize B12. Untracked DB artifacts are test outputs, not user-owned business changes; they will not be staged.
- Acceptance: prior B11 acceptance remains valid.
- Boundary: only S3-08, S3-09, S3-10 and S3 Gate; no S4-01 or later batches.
- Exact next action: implement S3-08 Activation/Retrieval Log/Trace in `memoryhub/application/retrieval_service.py` and supporting observability/repository modules.

# MemoryHub vNext Codex Execution State

> Last updated: 2026-08-24 13:25 +08:00
> Updated by: Codex session 2026-08-24 (B11)

## B10 start reconciliation

- Last updated: 2026-08-24 11:58 +08:00; updated by Codex session 2026-08-24 (B10)
- Current batch: B10 (`S3-01`～`S3-03`); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B10_s3_request_planning.md`
- Current task: S3-03 DONE; S3-01 DONE; S3-02 DONE
- Dependencies: S0-04 DONE with valid evidence; S1-07 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `1c08cde2f99c0c7e996dd55c0b2844a275cabb95` (B09 commit `feat(vnext): complete B09 s2 shadow eval gate`); working tree clean; no applicable `AGENTS.md`; BATCH_BOARD was B10 READY and TASK_BOARD had no B10 task in progress
- Reconciliation: B09 commit is present and BATCH_BOARD/TASK_BOARD facts authorize B10. No user-owned unrelated changes observed.
- Acceptance: prior B09 acceptance remains valid.
- Boundary: only S3-01, S3-02, S3-03; no S3-04 or later batches.
- Exact next action: run B10 focused tests, affected vNext regressions, and static checks; then finalize B10 commit.

### S3-03 checkpoint

- Status: DONE; Retrieval Planner produces channel plans per intent with necessary channels only, authority-checked enforcement, production Milvus gate, and degraded-channel visibility.
- Implementation: `memoryhub/retrieval/planner.py` with `RetrievalPlan`, `RetrievalPlanner`, per-intent channel sets, scope/layer/type metadata filters, and safe fallbacks.
- Evidence: `tests/test_vnext_retrieval_planner.py` 12 passed; ruff/compileall passed.
- Next checkpoint: B10 batch validation and single local commit.

### S3-02 checkpoint

- Status: DONE; 7-class Intent Router with rule-based scoring, optional LLM scorer, MIXED/low-confidence degradation, and explainable target layers/types.
- Implementation: `memoryhub/retrieval/intent_router.py` with `IntentRouter`, `RoutedIntent`, confidence bands, and fail-closed fallback.
- Evidence: `tests/test_vnext_intent_router.py` 14 passed; ruff/compileall passed.
- Next checkpoint: S3-03 Retrieval Planner and multi-channel recall.

### S3-01 checkpoint

- Status: DONE; bidirectional compatibility between `MemoryRetrievalRequest/Response` and legacy `SearchRequest/Response` verified.
- Implementation: `MemoryRetrievalRequest.from_legacy_search_request`, `MemoryRetrievalResponse.to_legacy_search_response`, enhanced `LegacySearchCompatibilityResponse.from_vnext`, and helper mappings in `memoryhub/adapter/vnext_schemas.py`.
- Evidence: `tests/test_vnext_interface.py` 9 passed; ruff/compileall passed.
- Next checkpoint: S3-02 Query Understanding and 7-class Intent Router.

## B09 final validation and acceptance

- Last updated: 2026-08-24 08:55 +08:00; updated by Codex session 2026-08-24 (B09)
- Current batch: B09 (`S2-08`～`S2-10` and S2 Gate); batch status: DONE
- Current task: none; S2-08, S2-09, S2-10 DONE; S2 Gate PASS
- Dependencies: S1-01～S1-11 DONE; S1 Gate PASS; S2-01～S2-07 DONE with valid evidence
- Reconciliation: branch `dev-remem`; HEAD `6c0131921be35bdd9a7846148ffa0da0e87ed884` (B08 commit); B09 work staged for single local commit; no applicable `AGENTS.md`
- Acceptance:
  - S2-08 Formation Shadow: `memoryhub/application/formation_shadow.py` with in-memory candidate repo, no ACTIVE Long-Term write, classified differences.
  - S2-09 Formation/Evolution Trace: `memoryhub/observability/trace_models.py`, `trace_store.py`, redacted by default, chainable indexes.
  - S2-10 Formation datasets/evaluator: `evaluation/datasets/vnext_formation_eval.json`, `vnext_formation_p1_pairs.json`, `evaluation/metrics/formation_eval.py`, focused tests.
  - B09 focused tests 23 passed; affected vNext/S2 regression 196 passed; ruff/compileall/diff-check passed; evaluator CLI report matches annotated expectations.
  - S2 Gate checklist verified in tests: DOCX stays local, repeated evidence promotes, Markdown GLOBAL and DOCX PROJECT coexist, repairs form procedural candidate, decisions carry reason codes.
- Next batch: B10 READY; next prompt is `docs/last_improve/codex_batches/B10_s3_request_planning.md`.
- Boundary: only S2-08, S2-09, S2-10 and S2 Gate; no S3-01 or later batches touched.
- Commit plan: create exactly one local commit titled `feat(vnext): complete B09 s2 shadow eval gate` with trailer `Batch-ID: B09`; do not push, amend, rebase or enter B10.

## B09 start reconciliation

- Last updated: 2026-08-24 08:40 +08:00; updated by Codex session 2026-08-24 (B09)
- Current batch: B09 (`S2-08`～`S2-10` and S2 Gate); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B09_s2_shadow_eval_gate.md`
- Current task: S2-08 IN_PROGRESS; S2-09, S2-10 TODO; S2 Gate TODO
- Dependencies: S1-01～S1-11 DONE with valid evidence; S1 Gate PASS; S2-01, S2-02, S2-03, S2-04, S2-05, S2-06, S2-07 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `6c0131921be35bdd9a7846148ffa0da0e87ed884` (B08 commit `feat(vnext): complete B08 s2 consolidation evolution`); working tree clean; no applicable `AGENTS.md`; BATCH_BOARD was B09 READY and TASK_BOARD had no B09 task in progress
- Reconciliation: B08 commit is present and BATCH_BOARD/TASK_BOARD facts authorize B09. No user-owned unrelated changes observed.
- Acceptance: prior B08 acceptance remains valid.
- Boundary: only S2-08, S2-09, S2-10 and S2 Gate; no S3-01 or later batches.
- Exact next action: implement S2-08 Formation Shadow mode in `application/reflection_service.py` / feature flag.

## B08 start reconciliation

- Last updated: 2026-08-24 08:00 +08:00; updated by Codex session 2026-08-24 (B08)
- Current batch: B08 (`S2-04`～`S2-07`); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B08_s2_consolidation_evolution.md`
- Current task: S2-04 IN_PROGRESS; S2-05, S2-06, S2-07 TODO
- Dependencies: S1-01～S1-11 DONE with valid evidence; S1 Gate PASS; S2-01, S2-02, S2-03 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `e8c55d31f2c2e48330c8eae460d2084f6d8a26b7` (B07 commit `feat(vnext): complete B07 s2 reflection candidates`); working tree clean; no applicable `AGENTS.md`; BATCH_BOARD was B08 READY and TASK_BOARD had no B08 task in progress
- Reconciliation: B07 commit is present and BATCH_BOARD/TASK_BOARD facts authorize B08. No user-owned unrelated changes observed.
- Acceptance: prior B07 acceptance remains valid.
- Boundary: only S2-04, S2-05, S2-06, S2-07; no S2-08 or later batches.
- Exact next action: implement S2-04 Promotion Score/阈值/reason codes in `application/consolidation_service.py`.

## B07 start reconciliation

- Last updated: 2026-08-24 07:05 +08:00; updated by Codex session 2026-08-24 (B07)
- Current batch: B07 (`S2-01`～`S2-03`); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B07_s2_reflection_candidates.md`
- Current task: S2-01 IN_PROGRESS; S2-02 and S2-03 TODO
- Dependencies: S1-01～S1-11 DONE with valid evidence; S1 Gate PASS
- Start reconciliation: branch `dev-remem`; HEAD `fdf9bae6d3cd4c3d2627fa0257bdb1f4dfbd52d1` (merge of B06 commit `b9432ab` and upstream docs); working tree clean; no applicable `AGENTS.md`; BATCH_BOARD was B07 READY and TASK_BOARD had no B07 task in progress
- Reconciliation: prior STATE text listed HEAD `9280482` because it was written before the upstream merge; B06 commit `b9432ab` is present in history and BATCH_BOARD/TASK_BOARD facts authorize B07. Working tree contains no uncommitted B07 work yet.
- Boundary: only S2-01, S2-02, S2-03; no S2-04 or later batches.
- Exact next action: implement S2-01 Task Boundary Detector, then update continuity and claim S2-02.

## B06 entrypoints gate position

- Last updated: 2026-08-24 05:12 +08:00; updated by Codex session 2026-08-24 (B06)
- Current batch: B06 (`S1-09`～`S1-11` and S1 Gate); batch status: DONE
- Current batch prompt: `docs/last_improve/codex_batches/B06_s1_entrypoints_gate.md`
- Current task: None; S1-09, S1-10, S1-11 DONE; S1 Gate PASS
- Dependencies: S1-01～S1-08 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `92804826f37536246d2298eb416d1b7a4fb65103` (B05 commit); tracked worktree diff present for B06 scope; no applicable `AGENTS.md`; BATCH_BOARD was B06 READY and TASK_BOARD had no B06 task in progress
- Reconciliation: prior STATE text was B05 handoff; B05 commit `9280482` is present and BATCH_BOARD/TASK_BOARD facts authorize B06. B06 work was already present in the working tree but not yet recorded in continuity files.
- Acceptance: S1-09 entrypoint convergence, S1-10 task recovery/P0 flow, S1-11 Authority→Projection rebuild, affected/risk regressions, safety/contract regressions, static checks, continuity update, and the single B06 commit are complete.
- Next batch: B07 READY; next prompt is `docs/last_improve/codex_batches/B07_s2_reflection_candidates.md`.
- Hard stop: do not execute or modify S2-01 or any later batch in this session; stop after read-only verification of the single B06 commit.

### S1 Gate

- Status: PASS; production write has no bypass; task recovery and projection rebuild are verified; S1-09/S1-10/S1-11 evidence is valid.
- Validation: B06 focused tests 16 passed; affected vNext/working/episode/authority/gateway/write-bypass suite 48 passed; safety/contract/error regressions 77 passed; core B06 modules ruff and compileall passed; `git diff --check` passed.
- Environment note: agent-integration CLI/MCP/client modules contain pre-existing E501 line-length findings outside the B06-touched lines; these are recorded as PARTIAL style evidence and do not block S1 Gate because the entrypoint logic is covered by tests.
- Commit: `SELF (Batch-ID: B06)`; no push, amend, rebase, or B07 implementation performed.

### S1-11 checkpoint

- Status: DONE; Authority→Projection rebuild verified.
- Implementation: `scripts/rebuild_projections.py` scans active Preference/Knowledge rows and enqueues projection upserts into `MemoryProjectionOutboxRepository`; dry-run mode reports without writing; deleted memories are skipped; content_version is preserved.
- Evidence: `EVIDENCE.md#s1-11-checkpoint`
- Validation: rebuild tests 3 passed; scoped ruff and compileall passed.

### S1-10 checkpoint

- Status: DONE; task recovery interface and P0 flow verified.
- Implementation: `memoryhub/adapter/vnext_api.py` exposes `/api/memory/vnext/tasks/{task_id}/resume` using `EpisodeService.resume_by_task`; P0 E2E flow covers start-with-constraints, phase transition, no-immediate-global-promotion, resume-after-restart, projection-rebuild consistency, multi-entrypoint idempotency, duplicate-event suppression, and sensitive-content MASK.
- Evidence: `EVIDENCE.md#s1-10-checkpoint`
- Validation: P0 flow tests 8 passed; resume endpoint tests 2 passed; scoped ruff and compileall passed.

### S1-09 checkpoint

- Status: DONE; REST/Agent replay/MCP/CLI/SDK write entrypoints converge on `CanonicalWriteService`.
- Implementation: `memoryhub/adapter/vnext_api.py` provides the single production `/api/memory/vnext/events` endpoint; `memoryhub/adapter/agent_api.py` replay/step endpoints delegate to `CanonicalWriteService`; SDK `MemoryHubClient.write_canonical_events`/`resume_task` and CLI `event`/`resume` subcommands call the REST endpoint; MCP tools register `memoryhub_write_event` and `memoryhub_resume_task`.
- Evidence: `EVIDENCE.md#s1-09-checkpoint`
- Validation: entrypoint tests 5 passed; P0 multi-entrypoint consistency passed; scoped ruff and compileall passed.

## B05 authoritative position

完成 A/B/C/D 一体化执行任务方案中的 S0～S5 必做任务，通过 P0/P1 与发布 Gate。

## B05 authoritative position

- Last updated: 2026-08-22 20:55 +08:00; updated by Codex session 2026-08-22 (B05)
- Current batch: B05 (`S1-07`～`S1-08`); batch status: DONE
- Current batch prompt: `docs/last_improve/codex_batches/B05_s1_authority_write.md`
- Current task: None; S1-07 and S1-08 DONE
- Dependencies: S0-03, S1-02, S1-03, S1-04, S1-05, and S1-06 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `06403d636c55b1b6b33257986ca911a13e7571a9`; no tracked worktree diff; no applicable `AGENTS.md`; BATCH_BOARD was B05 READY and TASK_BOARD had no B05 task in progress
- Reconciliation: prior STATE text was stale B04 handoff; B04 commit `06403d6` is present and BATCH_BOARD/TASK_BOARD facts authorize B05. No user-owned unrelated changes observed.
- Acceptance: S1-08 end-to-end, affected/risk regressions, safety/contract regressions, static checks, continuity update, and the single B05 commit are complete.
- Next batch: B06 READY; next prompt is `docs/last_improve/codex_batches/B06_s1_entrypoints_gate.md`.
- Hard stop: do not execute or modify S1-09 or any later batch in this session; stop after read-only verification of the single B05 commit.

### S1-08 final validation and B05 acceptance

- Status: DONE; B05 is DONE and B06 is READY.
- Validation: focused Authority tests 4 passed; affected storage/writer/outbox regressions 38 passed; safety, write-bypass, and contract/interface regressions 100 passed; B05 modules ruff and compileall passed; `git diff --check` passed.
- Environment note: the default pytest temp directory was blocked by Windows permissions; the same regression sets passed in a controlled temporary run. Existing `memoryhub/adapter/schemas.py` contains five pre-existing full-file ruff findings outside the B05-added field.
- Commit: `SELF (Batch-ID: B05)`; no push, amend, rebase, or B06 implementation performed.

### S1-07 checkpoint

- Status: DONE; S1-08 is now the single IN_PROGRESS task in B05.
- Implementation: added tenant-scoped Long-Term Authority Facade/Repository; unified Preference, Semantic FACT, Procedural and Episodic legacy representations under `LongTermEnvelope`; ACTIVE chain uniqueness and monotonic content versions are enforced; inactive versions are hidden by default.
- Compatibility: existing Preference/Knowledge rows remain the storage adapter; additive tenant/metadata fields carry vNext identity without a second Authority table.
- Evidence: `EVIDENCE.md#s1-07-checkpoint`
- Validation: Authority-focused tests 3 passed; scoped ruff and compileall passed.
- Next checkpoint: validate Canonical Write event→Working→Episode→Reflection→Long-Term and transaction metadata consistency.

### S1-04 checkpoint

- Status: DONE; S1-05 is now the single IN_PROGRESS task in B04.
- Implementation: field-level Working Patch/CAS, source-priority protection, semantic list merge, structured compression, and persisted field-source metadata.
- Evidence: `EVIDENCE.md#s1-04-checkpoint`
- Next checkpoint: validate Episode append/snapshot/resume/close and resource staleness, then update all continuity evidence before S1-06.

### S1-05 checkpoint

- Status: DONE; S1-06 is now the single IN_PROGRESS task in B04.
- Implementation: append-only Episode events with source-event replay protection, snapshot CAS, hashed resume tokens, deterministic replay, close transitions, and stale-resource/revalidation reporting.
- Evidence: `EVIDENCE.md#s1-05-checkpoint`
- Next checkpoint: validate Candidate transition boundaries and default retrieval isolation, then run the B04 affected/risk regression set.

### S1-06 and B04 acceptance checkpoint

- S1-06 status: DONE; Candidate transitions are closed and default repository search returns no Candidate rows.
- B04 status: ready for final continuity update and single local commit.
- Evidence: `EVIDENCE.md#s1-06-and-b04-final-validation`
- Blockers/risks: no B04 business failures. Optional `rank-bm25` is absent for six legacy user-isolation tests; two legacy tmp_path tests are blocked by host pytest temp-directory permissions. Both are recorded as PARTIAL environment evidence.
- Exact next action: update BATCH_BOARD/SESSION_LOG, mark B05 READY, perform staged scope audit, create exactly one `Batch-ID: B04` commit, then read-only verify SHA and stop.

## Legacy B03 handoff

- Overall status: ACTIVE
- Execution model: one session, one batch
- Current batch: B03 (`S1-01`～`S1-03`)
- Batch status: DONE
- Batch commit policy: 完整验收后创建一次本地提交；未完成不提交；不 push
- Completed batch commits: B01=`a502f9a`, B02=`1b84af1`
- Current batch commit: SELF (Batch-ID: B03); one local B03-only commit pending
- Current batch prompt: `docs/last_improve/codex_batches/B03_s1_storage_ingress.md`
- Completed in current batch: S1-01, S1-02, S1-03
- Batch hard stop: S1-03 验收后将 B03 完成状态和 B03-only 产物纳入唯一提交，然后停止会话；不得在同一会话启动 S1-04
- Current stage: S1
- Current task: None; B03 handoff
- Task status: DONE
- Last completed task: S1-03
- Next checkpoint: 提交后只读核对 HEAD SHA 和提交文件，报告 B04_s1_task_state.md 后停止；不得在本会话启动 B04

## Repository snapshot

- Working directory: `D:\project\XA202612-2`
- Branch: `dev-remem`
- HEAD before B03 worktree changes: 5032c61f93bb16a724d6d9acb5be1269ae7cb2a9
- Dirty paths before final B03 staging: B03 source/tests/specs plus codex_execution continuity files only
- User-owned unrelated changes: none observed in the B03-scoped status audit；ignored pytest basetemp directories were not staged

## Recovery reconciliation

- State vs repository: RECONCILED TO BATCH MODEL
- Facts checked: 无 `AGENTS.md`；`codex_execution/` 不存在；方案要求 57 个正式任务；现有仓库已有旧 `MemoryLevel(short/mid/long)` 与事件/安全/写入基础
- Differences and resolution: 旧提示词允许同一会话连续领取 READY 任务，导致推进到 S1-03；现改为 18 个批次并新增 BATCH_BOARD。已有有效 DONE 证据保留，当前恢复到 B03，不回退重做 S0

## Legacy B03 task facts

- Goal: 升级 Event Gateway，按 Envelope→身份/Scope→Policy→MASK/DROP/REVIEW→幂等→Commit 顺序接入 canonical write
- Dependencies verified: S1-02 DONE；现有 safety pipeline、MemoryWriteService/DomainMemoryWriter、vNext Event/API contracts 可复用
- Files in scope: `memoryhub/application/`, `memoryhub/core/`, `tests/test_vnext_event_gateway.py`
- Acceptance remaining: None within B03；安全文件系统风险组合的主机权限 PARTIAL 已在 EVIDENCE 记录，不是 B03 业务断言失败
- Tests to run: S1-03 定向 Event Gateway/Policy/idempotency tests、write-bypass regression 和受影响存储/契约回归

## B04 start checkpoint

- Change: B04 start reconciliation and S1-04 claim
- Evidence: `EVIDENCE.md#b04-start-reconciliation`
- Result: B04 was READY with no in-progress task, so the smallest dependency-satisfied task S1-04 was claimed; existing S1-01～S1-03 DONE evidence is retained.

## Last verified B03 checkpoint

- Change: B03 final validation of S1-01～S1-03
- Evidence: EVIDENCE.md#s1-03-final-validation-checkpoint
- Result: Event Gateway 11 passed；受影响 vNext 回归 45 passed；S1-01/S1-02 evidence remains valid；B03 ready for the single local commit

### S1-03 implementation checkpoint

- Change: Event Gateway 完成 Envelope→identity→Scope→Policy→action→idempotency→atomic Event commit；补足唯一键竞争后的幂等重读和 MASK fail-closed。
- Evidence: `EVIDENCE.md#s1-03-implementation-checkpoint`
- Result: 定向测试 11 passed；ruff passed；并发重复提交只保留 1 个 Event/IdempotencyRecord；REVIEW/DROP、Scope 拒绝和未净化 MASK 均无持久化；重复提交不改变既有 Evidence/Frequency。

### S1-03 regression checkpoint

- Change: 完成受影响 vNext 回归和 write-bypass 扫描；首次安全风险组合被主机 pytest 临时目录权限阻断。
- Evidence: `EVIDENCE.md#s1-03-regression-checkpoint`
- Result: 44 passed；安全组合 81 passed、1 skipped、70 setup errors，错误均为 pytest 临时目录 `.lock` 的 `PermissionError`，无业务断言失败；将拆分重跑可复现安全用例。

### S1-03 final validation checkpoint

- Change: 修复 SQLite 并发跨表读偏差；同租户同幂等键的已存在 Event 在 Session 结束后统一 reconciliation。
- Evidence: `EVIDENCE.md#s1-03-final-validation-checkpoint`
- Result: Event Gateway 11 passed；受影响 vNext 回归 45 passed；ruff/compileall/diff-check passed；S1-03 三项敏感/租户/事务/并发/幂等证据齐全；S1-01～S1-03 DONE。

## Blockers

- None for B03; unrelated filesystem-based Safety Gate/Audit/Memory Write tests remain PARTIAL because the host denies pytest temporary-directory access.

## B04 exact next actions

1. Implement and validate S1-04, then update STATE/TASK_BOARD/EVIDENCE and claim S1-05.
2. Complete S1-05 and S1-06 with targeted, regression, and risk evidence before batch acceptance.
3. Only after full acceptance update BATCH_BOARD/SESSION_LOG, mark B05 READY, create the single B04 commit, and read-only verify its SHA; do not push, amend, rebase, or enter B05.

## B11 start reconciliation

- Last updated: 2026-08-24 12:42 +08:00; updated by Codex session 2026-08-24 (B11)
- Current batch: B11 (`S3-04`～`S3-07`); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B11_s3_fusion_context.md`
- Current task: S3-04 IN_PROGRESS; S3-05, S3-06, S3-07 TODO
- Dependencies: S3-01, S3-02, S3-03 DONE with valid evidence; S2-06 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `b7bab109b45e45fd9a74555c9a8693ac811ac203` (B10 commit `feat(vnext): complete B10 s3 request planning`); working tree clean; no applicable `AGENTS.md`; BATCH_BOARD was B11 READY and TASK_BOARD had no B11 task in progress
- Reconciliation: B10 commit is present and BATCH_BOARD/TASK_BOARD facts authorize B11. No user-owned unrelated changes observed.
- Acceptance: prior B10 acceptance remains valid.
- Boundary: only S3-04, S3-05, S3-06, S3-07; no S3-08 or later batches.
- Exact next action: implement S3-04 candidate deduplication, Fusion and unified Reranker in `memoryhub/retrieval/fusion.py` and upgrade `memoryhub/retrieval/reranker.py`.

## Legacy B03 exact next actions

1. 只暂存 B03 产物和六份连续性文件，创建唯一普通本地提交，正文包含 Batch-ID: B03。
2. 提交后只读核对 HEAD SHA、提交文件和工作区状态；不 push、amend、rebase 或进入 B04。
3. 新会话使用 docs/last_improve/codex_batches/B04_s1_task_state.md。


## B11 final validation and acceptance

- Last updated: 2026-08-24 13:25 +08:00; updated by Codex session 2026-08-24 (B11)
- Current batch: B11 (`S3-04`～`S3-07`); batch status: DONE
- Current task: none; S3-04, S3-05, S3-06, S3-07 DONE
- Dependencies: S3-01, S3-02, S3-03 DONE with valid evidence; S2-06 DONE with valid evidence
- Final validation: branch `dev-remem`; HEAD `b7bab109b45e45fd9a74555c9a8693ac811ac203` (B10 commit); B11-scope changes staged; no user-owned unrelated changes observed.
- Acceptance:
  - S3-04 Fusion/Reranker: `memoryhub/retrieval/fusion.py` with RRF/ScoreFusion and deduplication; `memoryhub/retrieval/reranker.py` upgraded with `VNextReranker` preserving legacy `Reranker`.
  - S3-05 Authority/Scope Resolver: `memoryhub/retrieval/scope_resolver.py` filters DELETED/SUPERSEDED, validates against Authority, resolves conflicts by TASK>PROJECT>APPLICATION>DOMAIN>GLOBAL.
  - S3-06 Budget: `memoryhub/retrieval/context_builder.py` protects working state/constraints/procedures, trims long-term memory, records dropped reasons.
  - S3-07 Context Builder: `memoryhub/application/context_service.py` orchestrates fusion→rerank→scope→budget→structured context with full traceability.
  - B11 focused tests 38 passed; affected vNext regression 226 passed; safety/contract/error regression 77 passed; write-bypass 6 passed; static checks passed; `git diff --check` passed.
- Next batch: B12 READY; next prompt is `docs/last_improve/codex_batches/B12_s3_entrypoints_eval_gate.md`.
- Boundary: only S3-04, S3-05, S3-06, S3-07; no S3-08 or later batches.
- Commit plan: create exactly one local commit titled `feat(vnext): complete B11 s3 fusion context` with trailer `Batch-ID: B11`; do not push, amend, rebase, or enter B12.

### S3-04 checkpoint

- Status: DONE; candidate deduplication, RRF/ScoreFusion and unified vNext Reranker with explainable score breakdown.
- Implementation: `memoryhub/retrieval/fusion.py`, `memoryhub/retrieval/reranker.py`, `memoryhub/retrieval/__init__.py`.
- Evidence: `tests/test_vnext_fusion_reranker.py` 17 passed; ruff/compileall passed.
- Next checkpoint: S3-05 Authority validation and Scope conflict resolution.

### S3-05 checkpoint

- Status: DONE; Authority validity check, DELETED/SUPERSEDED filtering, scope precedence conflict resolution with auditable reason codes.
- Implementation: `memoryhub/retrieval/scope_resolver.py`.
- Evidence: `tests/test_vnext_scope_resolver.py` 10 passed; ruff/compileall passed.
- Next checkpoint: S3-06 Context Budget Manager.

### S3-06 checkpoint

- Status: DONE; categorized budget quotas, hard constraint protection, procedure priority, long-term memory trimming and dropped-reason tracking.
- Implementation: `memoryhub/retrieval/context_builder.py`.
- Evidence: `tests/test_vnext_context_budget.py` 8 passed; ruff/compileall passed.
- Next checkpoint: S3-07 structured Context Builder service.

### S3-07 checkpoint

- Status: DONE; end-to-end Context Service wires fusion→rerank→scope→budget→rendered ContextPayload with trace/dropped diagnostics.
- Implementation: `memoryhub/application/context_service.py`, `memoryhub/application/__init__.py`.
- Evidence: `tests/test_vnext_context_service.py` 5 passed; ruff/compileall passed.

## B18 start reconciliation — 2026-08-25

- Current batch: B18 (`S5-09` through `S5-10` plus S5/P0/P1/Release Gate), status `IN_PROGRESS`; current task: S5-09 `IN_PROGRESS`.
- Repository truth: branch `dev-remem`, HEAD `5e5f3cb3a1a3147bab8b2bd722780b56f74fdcd6` (`feat(vnext): complete B17 s5 migration cutover`, trailer `Batch-ID: B17`). Tracked worktree diff is empty.
- B17 is DONE; B18 is the sole READY batch. No B18 task was previously in progress, so S5-09 is claimed.
- No applicable `AGENTS.md` was found. Boundary: only S5-09/S5-10, required continuity/spec/test/report artifacts, and final Gate review; do not execute or modify any batch beyond B18.
- Exact next action: update REST/CLI/MCP/SDK, deployment, migration, backup/recovery and fault-handling docs; verify documented commands execute in a clean environment.

## S5-09 checkpoint — 2026-08-25

- Status: DONE. Added `docs/vnext/spec/VNEXT_DEPLOYMENT.md`, `docs/vnext/spec/VNEXT_BACKUP_RECOVERY.md`, `docs/vnext/spec/VNEXT_FAULT_HANDLING.md`, `docs/vnext/spec/VNEXT_ACCEPTANCE.md` and updated `agent-integration/README.md`.
- REST/CLI/MCP/SDK commands documented and verified executable in clean environment: `memoryhub --help`, `python -m memoryhub_mcp`, `from memoryhub_client import MemoryHubClient`.
- Deployment, migration, backup/recovery and fault-handling runbooks include executable commands, rollback steps and hard-stop conditions.
- Evidence: `EVIDENCE.md#s5-09-checkpoint`; focused docs/demo tests 16 passed; ruff/compileall passed.
- Next task: S5-10 `IN_PROGRESS`; create fixed, redacted, replayable demo and final acceptance package.

## S5-10 and B18 final acceptance — 2026-08-25

- S5-10 DONE. Added `examples/vnext_demo/` with redacted fixtures, deterministic `run_demo.py`, and `tests/test_vnext_demo.py` replayable scenarios.
- Demo output contains only IDs, hashes, counts and audit metadata; no raw content or sensitive Evidence.
- `docs/vnext/spec/VNEXT_ACCEPTANCE.md` records all 57 tasks, 18 batches and S0/S1/S2/S3/S4/S5/P0/P1/Release Gate PASS.
- B18 acceptance: S5-09 documentation and S5-10 demo/acceptance package meet exit criteria. All tasks and Gates have valid evidence.
- Final validation: B18 focused tests 16 passed; affected vNext regression 341 passed; safety/contract/error suite passed; ruff, compileall, `git diff --check` passed; demo CLI exited 0.
- Batch status: B18 DONE; there is no next batch.
- Commit reference must be `SELF (Batch-ID: B18)` in the single B18 commit. Do not push, amend, rebase or enter another batch.
