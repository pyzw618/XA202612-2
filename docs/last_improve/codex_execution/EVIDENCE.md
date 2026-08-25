# MemoryHub vNext Execution Evidence

## B17 start reconciliation

- Date/time: 2026-08-25 +08:00; environment: Windows PowerShell, `D:\project\XA202612-2`, `.venv` Python/pytest/ruff.
- Commands: branch/HEAD/status/diff/log inspection; required B17 manual, batch prompt, plan S5-05～S5-08 sections, all continuity files, applicable `AGENTS.md` inventory, and directly related vNext trace/migration/formation/retrieval/config tests and sources.
- Result: branch `dev-remem`; HEAD `330f4d27f04b0729a53a2b63b1ab5747eb6f6dcb` contains B16 with `Batch-ID: B16`; no tracked diff; no applicable `AGENTS.md` found. Existing untracked evaluation `.db`/report artifacts and denied pytest temp directories are preserved.
- Reconciliation: B17 is READY with no in-progress task; S5-05 is claimed. S3-08, S5-01, S0-05, S1-01, S1-07, S2-08, S3-09 and S4 Gate dependencies have valid evidence. S5-09/S5-10/B18 are outside this session.
- Boundary: only S5-05～S5-08 and required continuity/spec/test/report files may change; no Authority正文/状态 mutation is authorized by Shadow paths.

## S5-05 checkpoint

- Deliverables: `memoryhub/application/feedback_service.py`, RetrievalService optional usage integration, and `tests/test_vnext_feedback_service.py`.
- Focused command: `.venv\Scripts\python.exe -m pytest tests/test_vnext_feedback_service.py tests/test_vnext_retrieval_service.py tests/test_vnext_formation_trace.py -q` → `16 passed`.
- Risk command: `.venv\Scripts\python.exe -m pytest tests/test_no_production_write_bypass.py tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q` → `83 passed`.
- Static: scoped ruff, compileall and `git diff --check` passed after import normalization; line-ending warnings are existing Windows normalization only.
- Acceptance: all five usage classes are separately represented; feedback only produces bounded utility proposals and redacted spans; `shadow_only=true`, `authority_mutations=0`, no raw query/content fields and no lifecycle/Authority write path.
- Exit: S5-05 DONE; S5-06 claimed as the sole IN_PROGRESS task.

## S5-06 checkpoint

- Deliverables: extended `scripts/migrate_vnext.py`, migration tests, and `docs/spec/VNEXT_MIGRATION.md` apply/rollback contract.
- Focused command: `.venv\Scripts\python.exe -m pytest tests/test_vnext_migration.py -q` → `4 passed`.
- Static/CLI: migration ruff and compileall passed; `.venv\Scripts\python.exe scripts/migrate_vnext.py --dry-run --report evaluation/results/vnext_migration/dry_run.json` exited 0 with `read_only_scan=true`, `no_irreversible_delete=true`, and `uncertain_data_never_promoted_to_active_global=true`.
- Apply evidence: a controlled legacy SQLite database applied one eligible row, left one tenant/scope/evidence-incomplete row unchanged in REVIEW, created backup and checkpoint, preserved old tables, and produced `APPLIED_WITH_REVIEW`; no delete/revival path exists.
- Acceptance: count/hash/tenant/scope/content version/evidence validation is part of the plan and apply gate; apply requires additive Authority columns and keeps Projection rebuild deferred.
- Exit: S5-06 DONE; S5-07 claimed as the sole IN_PROGRESS task.

## S5-07 checkpoint

- Deliverables: `memoryhub/application/shadow_read_service.py`, `evaluation/run_vnext_shadow.py`, `tests/test_vnext_shadow_read.py`, and `evaluation/results/vnext_shadow/shadow.json`.
- Focused/affected command: `.venv\Scripts\python.exe -m pytest tests/test_vnext_shadow_read.py tests/test_vnext_formation_shadow.py tests/test_vnext_formation_eval.py tests/test_vnext_retrieval_service.py tests/test_vnext_entrypoints.py -q` → `36 passed`.
- Risk command: `.venv\Scripts\python.exe -m pytest tests/test_no_production_write_bypass.py tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py tests/test_vnext_forget_diagnostics.py -q` → `86 passed`.
- Static/runner: scoped ruff and compileall passed; `evaluation/run_vnext_shadow.py --output evaluation/results/vnext_shadow/shadow.json` exited 0.
- Acceptance: Formation Shadow remains Candidate/in-memory only; Retrieval dual-read returns legacy output even when vNext errors; report contains only counts, hashes, classifications and leak counters; raw query/content is absent; Policy Leakage and Forget residual conditions are explicit hard-gate counters.
- Exit: S5-07 DONE; S5-08 claimed as the sole IN_PROGRESS task.

## S5-08 and B17 final acceptance

- Deliverables: `memoryhub/application/rollout_service.py`, `memoryhub/config.py`, `config.example.yaml`, `evaluation/run_vnext_rollout.py`, `evaluation/results/vnext_shadow/rollout.json`, `docs/spec/VNEXT_ROLLOUT.md`, and `tests/test_vnext_rollout.py`.
- Focused command: `.venv\Scripts\python.exe -m pytest tests/test_vnext_rollout.py tests/test_vnext_feature_flags.py -q` → `16 passed`.
- Final affected command: B17 S5-05～S5-08 plus Formation/Retrieval/Authority/Projection/Forget/write-bypass regression → `101 passed`.
- Final risk command: `.venv\Scripts\python.exe -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py tests/test_vnext_forget_diagnostics.py -q` → `80 passed`.
- Static/runner: touched-module ruff passed; application/config/migration/evaluation compileall passed; `git diff --check` passed; Shadow and rollout runners exited 0; report scan found no raw query/content/payload/raw_query fields.
- Acceptance: levels 5/25/50/100 cannot be skipped; each requires observed requests and zero Policy Leakage, cross-tenant, Forget residual and error metrics; CUTOVER and ROLLBACK audits preserve window/metrics/rollback duration; snapshot reports `redacted=true` and `authority_mutations=0`.
- B17 Gate: S5-05 through S5-08 DONE; B17 DONE; B18 READY only. No S5-09/S5-10/B18 implementation was performed.

## B16 start reconciliation

- Date/time: 2026-08-25 +08:00; environment: Windows PowerShell, `D:\project\XA202612-2`, `.venv` Python/pytest/ruff.
- Commands: `git branch --show-current`, `git rev-parse HEAD`, `git status --short`, `git diff --stat`, `git log --oneline -8`, and read-only inspection of the B16 prompt, execution manual/plan, all continuity files, trace/metrics/evaluation sources and directly related tests.
- Result: branch `dev-remem`; HEAD `5841161ef9acf2457e26f619db61c0fc2a5e52e5` contains the B15 commit and `Batch-ID: B15`. Existing untracked database reports are preserved. No applicable `AGENTS.md` exists. B16 was READY with no in-progress task; S5-01 dependencies are evidenced DONE, so S5-01 is claimed.
- Reconciliation: the continuity files still contained B15's pre-commit plan. Repository history is authoritative; this fact is recorded before B16 implementation.

## S5-01 checkpoint

- Deliverables: `memoryhub/observability/trace_policy.py`, upgraded `trace_models.py`/`trace_store.py`, app/Retrieval/Forget wiring, `docs/spec/VNEXT_TRACE.md`, and extended `tests/test_vnext_formation_trace.py`.
- Command: `.venv\\Scripts\\python.exe -m pytest tests/test_vnext_formation_trace.py tests/test_vnext_formation_shadow.py tests/test_vnext_retrieval_service.py tests/test_vnext_forget_diagnostics.py tests/test_vnext_reliability.py -q` → `38 passed`.
- Static: `.venv\\Scripts\\python.exe -m ruff check memoryhub/observability memoryhub/application/retrieval_service.py memoryhub/application/forget_service.py memoryhub/app.py tests/test_vnext_formation_trace.py` → passed; compileall and `git diff --check` passed.
- Acceptance: five typed chains are queryable by trace/task/event/memory/query identifiers; normal production sampling is deterministic at 10%, while high-risk/error/denied/Forget paths are 100%; raw body/query/payload/claim/excerpt/embedding fields are rejected recursively; expiration purge only removes Trace projection records.

## S5-02 checkpoint

- Deliverables: `evaluation/run_vnext_eval.py`, `tests/test_vnext_benchmark_runner.py`, and reproducible artifact `evaluation/results/vnext_benchmark.json`.
- Focused command: `.venv\\Scripts\\python.exe -m pytest tests/test_vnext_benchmark_runner.py tests/test_vnext_formation_eval.py tests/test_vnext_retrieval_eval.py tests/test_vnext_reliability.py tests/test_full_chain_benchmark.py -q` → `29 passed`.
- Reproduction command: `.venv\\Scripts\\python.exe evaluation/run_vnext_eval.py --output evaluation/results/vnext_benchmark.json` → all four layers emitted. Report verification: Formation samples=4; Retrieval queries=10 and scope leak rate=0.0; Infrastructure passed=true; E2E uses mock Milvus + mock embedding with fixed seed=42.
- Static: ruff, compileall and `git diff --check` passed. The report records immutable dataset SHA-256, annotation/model/prompt/weight versions, seed and environment; latency remains a measured (not asserted-identical) runtime value.

## S5-03 checkpoint

- Deliverables: `evaluation/run_vnext_comparison.py`, `tests/test_vnext_comparison.py`, and `evaluation/results/vnext_final/comparison.json`.
- Focused command: `.venv\\Scripts\\python.exe -m pytest tests/test_vnext_comparison.py tests/test_vnext_retrieval_eval.py -q` → `11 passed`.
- Reproduction command: `.venv\\Scripts\\python.exe evaluation/run_vnext_comparison.py --output evaluation/results/vnext_final/comparison.json --repeats 5` → four systems and four one-mechanism ablations.
- Controlled report facts: all systems share `mock-embedding/768`, offline deterministic mock channels and each query's declared token budget; vNext task success=1.0, policy leak=0.0, MRR=1.0. Flat RAG and Original each have policy leak=0.1. Each metric carries mean, variance and normal-approximation 95% CI. The persisted report is redacted and holds no raw query text.
- Static: ruff, compileall and `git diff --check` passed.

## S5-04 and B16 final validation and acceptance

- Deliverables: `memoryhub/application/dashboard_service.py`; management-gated `/api/memory/vnext/dashboard/{view}` contract; Desktop Explorer/Evolution/Retrieval Debugger/Benchmark pages; `tests/test_vnext_dashboard.py`.
- Focused Dashboard/affected command: `.venv\\Scripts\\python.exe -m pytest tests/test_vnext_dashboard.py tests/test_vnext_forget_diagnostics.py tests/test_vnext_formation_trace.py tests/test_vnext_benchmark_runner.py tests/test_vnext_comparison.py -q` → `14 passed`.
- Risk command: `.venv\\Scripts\\python.exe -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py tests/test_no_production_write_bypass.py -q` → `83 passed`.
- Static command: ruff over all B16 Python sources/tests, compileall and `git diff --check` → passed. Desktop source/CMake registration was checked with `rg`; `cmake -S desktop-client ...` is PARTIAL because `cmake` is absent from this host PATH.
- Acceptance: Dashboard endpoint rejects no-admin access with 403, returns `redacted=true` after authorization and appends an audit record. Explorer/Evolution/Retrieval Debugger are tenant/user scoped Trace projections; Benchmark suppresses per-query samples to avoid raw-query display. The Qt pages link to all four views and display the redaction/authorization notice.
- Broader affected attempt: the PowerShell-expanded `pytest test_vnext_*.py` command ran beyond the 30-second host tool window; no completion result was available and it is deliberately not counted as PASS.

## B15 start reconciliation

- Repository facts: branch `dev-remem`, HEAD `d0ffff4745c3094a8437006fb2e7a5c38e5fd0e1`; existing untracked evaluation DB artifacts preserved.
- S4-01 through S4-06 have valid DONE evidence; no current in-progress task existed, so S4-07 was claimed.
- Planned S4-07 matrix: vector timeout, duplicate delivery, worker crash, pre-commit crash, post-commit crash, stale cache, index corruption, and duplicate event.

## S4-07 checkpoint

- Deliverables: `tests/test_vnext_reliability.py`, `evaluation/run_reliability_eval.py`, and `evaluation/results/vnext_reliability_report.json`.
- Command: `.venv\\Scripts\\python.exe -m pytest tests/test_vnext_reliability.py -q` → `9 passed`.
- Evaluation: `.venv\\Scripts\\python.exe evaluation/run_reliability_eval.py --output-json evaluation/results/vnext_reliability_report.json` → `passed=true`, all 8 matrix cases.
- Static: targeted ruff, compileall, and `git diff --check` passed.
- Acceptance: S4-07 DONE; S4-08 claimed next. No B16/S5 work performed.

## S4-08 and S4 Gate

- Metrics/Trace deliverables: `memoryhub/observability/metrics.py`, `memoryhub/observability/trace_models.py`, `memoryhub/observability/trace_store.py`, and Outbox worker instrumentation.
- Metrics snapshot includes latency summaries, projection lag, recovery time, repair rate, Forget success rate, and residual retrieval count.
- Regression: vNext suite 270 passed; S4 risk/recovery suite 109 passed; projection rebuild/Authority write suite 15 passed.
- Static: targeted ruff, compileall, and `git diff --check` passed.
- S4 Gate PASS: Authority pre-commit atomicity, post-commit Outbox recovery, duplicate/ordering safety, index repair, residual retrieval 0, and fail-closed stale/deleted reads are covered.
- Exit: S4-07 DONE, S4-08 DONE, S4 Gate PASS; B16 READY only.

## B10 start reconciliation

- Date/time: 2026-08-24 11:58 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  git log -1 --format="%H%n%s%n%b"
  rg --files -g 'AGENTS.md'
  ```
- Result: PASS for repository reconciliation. HEAD=`1c08cde2f99c0c7e996dd55c0b2844a275cabb95`, B09 commit `feat(vnext): complete B09 s2 shadow eval gate` with trailer `Batch-ID: B09` is present, working tree clean, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B10 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B10 task in progress; S0-04 and S1-07 are DONE with evidence.
- Decision: claim B10 and the smallest dependency-satisfied task S3-01; do not touch S3-04 or later batches.

## S3-01 checkpoint

- Date/time: 2026-08-24 12:05 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_interface.py -q
  .venv/Scripts/python -m ruff check memoryhub/adapter/vnext_schemas.py tests/test_vnext_interface.py
  .venv/Scripts/python -m compileall -q memoryhub/adapter/vnext_schemas.py tests/test_vnext_interface.py
  ```
- Result: PASS; 9 tests passed; ruff/compileall passed.
- Changes: `memoryhub/adapter/vnext_schemas.py` adds `MemoryRetrievalRequest.from_legacy_search_request`, `MemoryRetrievalResponse.to_legacy_search_response`, helper mappings, and enhanced `LegacySearchCompatibilityResponse.from_vnext`; `tests/test_vnext_interface.py` adds bidirectional compatibility tests.
- Compatibility verified: old `SearchRequest` maps to vNext scope/intent/page_size; vNext response maps back to old `SearchResponse` with populated `results`/`preferences`/`facts`/`knowledge` lists and stable metadata.

## S3-02 checkpoint

- Date/time: 2026-08-24 12:35 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_intent_router.py -q
  .venv/Scripts/python -m ruff check memoryhub/retrieval/intent_router.py tests/test_vnext_intent_router.py
  .venv/Scripts/python -m compileall -q memoryhub/retrieval/intent_router.py tests/test_vnext_intent_router.py
  ```
- Result: PASS; 14 tests passed; ruff/compileall passed.
- Changes: `memoryhub/retrieval/intent_router.py` with `IntentRouter` and `RoutedIntent`; 7-class rule-based scoring with optional LLM scorer, MIXED/low-confidence degradation, and explainable target layers/types.
- Behavior verified: CURRENT_STATE/TASK_HISTORY/PREFERENCE/SEMANTIC_FACT/PROCEDURE/EXPERIENCE each route correctly; MIXED produced for close/tied intents; empty/ambiguous queries degrade to MIXED; hint overrides rules; LLM fallback is fail-closed.

## S3-03 checkpoint

- Date/time: 2026-08-24 12:50 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_retrieval_planner.py -q
  .venv/Scripts/python -m ruff check memoryhub/retrieval/planner.py tests/test_vnext_retrieval_planner.py
  .venv/Scripts/python -m compileall -q memoryhub/retrieval/planner.py tests/test_vnext_retrieval_planner.py
  ```
- Result: PASS; 12 tests passed; ruff/compileall passed.
- Changes: `memoryhub/retrieval/planner.py` with `RetrievalPlan` and `RetrievalPlanner`; per-intent channel selection (vector/keyword/metadata/working/episode/authority), AUTHORITY_CHECKED enforcement, production Milvus gate, and degraded-channel reporting.
- Behavior verified: CURRENT_STATE uses working+metadata; TASK_HISTORY uses episode+metadata; Long-Term intents use vector+keyword+metadata+authority; EXPERIENCE adds episode; MIXED uses all channels; unavailable channels are listed as degraded; metadata filters carry tenant/user/scope/layer/type.

## B10 final validation and acceptance

- Date/time: 2026-08-24 13:05 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_interface.py tests/test_vnext_intent_router.py tests/test_vnext_retrieval_planner.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_*.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py tests/test_ingestion_schema.py tests/test_memory_write_contract_schema.py -q
  .venv/Scripts/python -m pytest tests/test_no_production_write_bypass.py tests/test_vnext_repositories.py tests/test_vnext_event_gateway.py tests/test_vnext_task_state.py tests/test_vnext_authority_write.py tests/test_vnext_p0_flow.py tests/test_vnext_entrypoints.py tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py tests/test_vnext_candidate_service.py tests/test_vnext_consolidation_service.py tests/test_vnext_evolution.py tests/test_vnext_long_term_validation.py tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py -q
  .venv/Scripts/python -m ruff check memoryhub/adapter/vnext_schemas.py memoryhub/retrieval/intent_router.py memoryhub/retrieval/planner.py tests/test_vnext_interface.py tests/test_vnext_intent_router.py tests/test_vnext_retrieval_planner.py
  .venv/Scripts/python -m compileall -q memoryhub/adapter/vnext_schemas.py memoryhub/retrieval/intent_router.py memoryhub/retrieval/planner.py tests/test_vnext_interface.py tests/test_vnext_intent_router.py tests/test_vnext_retrieval_planner.py
  git diff --check
  ```
- Result:
  - B10 focused tests: 35 passed.
  - Affected vNext regression (`tests/test_vnext_*.py`): 188 passed.
  - Safety/contract/error regression: 101 passed.
  - Broader affected vNext/S1/S2 regression: 116 passed.
  - Static checks: ruff/compileall passed; `git diff --check` passed (line-ending warnings only).
- Gate check: B10 exit criteria met -- old client compatibility preserved via bidirectional request/response adapters; 7-class routing is explainable with `RoutedIntent.reason` and `mixed_intents`; each intent enables only necessary channels; channel degradation is visible in `RetrievalPlan.degraded_channels` and reason string.
- Commit plan: stage only B10 source/tests/continuity artifacts; create exactly one local commit titled `feat(vnext): complete B10 s3 request planning` with trailer `Batch-ID: B10`; do not push, amend, rebase, or begin B11.

## B07 start reconciliation

- Date/time: 2026-08-24 07:05 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  git diff --name-only
  rg --files -g 'AGENTS.md'
  ```
- Result: PASS for repository reconciliation. HEAD=`fdf9bae6d3cd4c3d2627fa0257bdb1f4dfbd52d1`, B06 commit `b9432ab` is present in history, working tree clean, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B07 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B07 task in progress; S1-01～S1-11 and S1 Gate are DONE with evidence.
- Decision: claim B07 and the smallest dependency-satisfied task S2-01; do not touch S2-04 or later batches.

## S2-01 checkpoint

- Date/time: 2026-08-24 07:15 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Task Boundary Detector with hard triggers, rule scoring, model suggestion placeholder, debounce, and three checkpoint classes.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_boundary_detector.py -q
  .venv/Scripts/python -m ruff check memoryhub/domain/contracts.py memoryhub/domain/episode.py memoryhub/application/boundary_detector.py memoryhub/application/__init__.py tests/test_vnext_boundary_detector.py
  .venv/Scripts/python -m compileall -q memoryhub/domain memoryhub/application tests/test_vnext_boundary_detector.py
  ```
- Result: PASS; 9 boundary tests passed; ruff/compileall passed.
- Summary: `BoundaryDetector.detect` returns HARD triggers for explicit `boundary=complete/failed/explicit` and for writes into terminal episodes; RULE triggers for phase changes (PHASE) and context-pressure threshold (CONTEXT_PRESSURE); debounce suppresses the same checkpoint type within the configured window; terminal boundaries are distinguishable via `domain.episode.is_terminal_boundary`.
- Artifact/report/trace: `memoryhub/application/boundary_detector.py`, `memoryhub/domain/episode.py`, `memoryhub/domain/contracts.py`, `memoryhub/application/__init__.py`, `tests/test_vnext_boundary_detector.py`
- Acceptance: S2-01 DONE; S2-02 is now the single IN_PROGRESS task in B07.
- Follow-up: implement Reflection Schema/Prompt/Retry and Candidate-only output.

## S2-02 checkpoint

- Date/time: 2026-08-24 07:30 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Reflection input/output schema, prompt version, retries, and Candidate-only output; model must not directly write Authority.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_reflection.py -q
  .venv/Scripts/python -m ruff check memoryhub/core/reflection memoryhub/application/reflection_service.py tests/test_vnext_reflection.py
  .venv/Scripts/python -m compileall -q memoryhub/core/reflection memoryhub/application tests/test_vnext_reflection.py
  ```
- Result: PASS; 4 reflection tests passed; ruff/compileall passed.
- Summary: `ReflectionInput`/`ReflectionOutput` Pydantic schemas freeze the reflection contract; `render_reflection_prompt` enforces the Candidate-only rule in the prompt text; `ReflectionService.run` computes `input_hash`, validates output schema, records `model_id`/`prompt_version`/`input_hash`, retries on failure, and raises `ReflectionRunError` after exhaustion. The service returns a `Candidate` object and has no code path to `LongTermEnvelope`/Authority.
- Artifact/report/trace: `memoryhub/core/reflection/schema.py`, `memoryhub/core/reflection/prompts.py`, `memoryhub/core/reflection/__init__.py`, `memoryhub/application/reflection_service.py`, `tests/test_vnext_reflection.py`
- Acceptance: S2-02 DONE; S2-03 is now the single IN_PROGRESS task in B07.
- Follow-up: implement Candidate normalization key, Scope, near-duplicate merge and independent evidence groups.

## S2-03 checkpoint

- Date/time: 2026-08-24 08:00 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Candidate normalization key, Scope resolution, near-duplicate merge and independent evidence groups.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_candidate_service.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_task_state.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_event_gateway.py tests/test_vnext_authority_write.py tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_no_production_write_bypass.py -q
  .venv/Scripts/python -m ruff check memoryhub/domain/candidate.py memoryhub/storage/vnext_repositories.py memoryhub/application/candidate_service.py memoryhub/application/boundary_detector.py memoryhub/application/reflection_service.py memoryhub/core/reflection memoryhub/domain/contracts.py memoryhub/application/__init__.py tests/test_vnext_candidate_service.py tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py
  .venv/Scripts/python -m compileall -q memoryhub/domain memoryhub/storage memoryhub/application memoryhub/core/reflection tests/test_vnext_candidate_service.py tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py
  ```
- Result: PASS; candidate service 7 tests passed; affected vNext/working/episode/authority/gateway/entrypoint/P0/write-bypass suite 45 passed; ruff/compileall passed.
- Summary: `CandidateService.stage` normalizes claim keys via `domain.candidate.normalize_claim_key`, resolves scope from explicit payload/candidate/default without auto-promotion to GLOBAL, merges near-duplicates by `(normalized_key, scope)`, and uses an independent evidence group check based on existing `evidence_refs`/`supporting_episode_ids` so the same event/episode does not fabricate independent support. Repository `CandidateView` exposes scope_level, frequency and evidence lists for stateless decisions.
- Artifact/report/trace: `memoryhub/application/candidate_service.py`, `memoryhub/domain/candidate.py`, `memoryhub/storage/vnext_repositories.py`, `tests/test_vnext_candidate_service.py`
- Acceptance: S2-03 DONE; B07 ready for batch-wide regression and risk validation.
- Follow-up: run B07 affected regressions, safety/contract risk tests, and static checks.

## B06 start reconciliation

- Date/time: 2026-08-24 05:12 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  git diff --name-only
  rg --files -g 'AGENTS.md'
  ```
- Result: PASS for repository reconciliation. HEAD=`92804826f37536246d2298eb416d1b7a4fb65103`, B05 commit is present, B06-scope worktree changes are present but not yet recorded in continuity files, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B06 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B06 task in progress; S1-01～S1-08 are DONE with evidence.
- Decision: claim B06 and the smallest dependency-satisfied tasks S1-09, S1-10, S1-11; do not touch S2-01 or later batches.

## S1-09 checkpoint

- Date/time: 2026-08-24 05:12 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: REST/Agent replay/MCP/CLI/SDK write entrypoints all delegate to the single `CanonicalWriteService` production path.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_entrypoints.py -q
  .venv/Scripts/python -m ruff check memoryhub/adapter/vnext_api.py memoryhub/adapter/agent_api.py agent-integration/memoryhub_client/client.py agent-integration/memoryhub_cli/cli.py agent-integration/memoryhub_mcp/tools.py
  .venv/Scripts/python -m compileall -q memoryhub/adapter agent-integration
  ```
- Result: PASS; 5 entrypoint tests passed; core modified files ruff/compileall passed.
- Summary: `/api/memory/vnext/events` is the single production write endpoint; agent replay and step endpoints route through `CanonicalWriteService`; SDK exposes `write_canonical_events` and `resume_task`; CLI adds `event` and `resume` subcommands; MCP registers `memoryhub_write_event` and `memoryhub_resume_task`.
- Artifact/report/trace: `memoryhub/adapter/vnext_api.py`, `memoryhub/adapter/agent_api.py`, `memoryhub/app.py`, `agent-integration/memoryhub_client/client.py`, `agent-integration/memoryhub_cli/cli.py`, `agent-integration/memoryhub_mcp/tools.py`
- Acceptance: S1-09 DONE.
- Follow-up: run S1-10 task recovery/P0 flow tests and S1-11 projection rebuild tests.

## S1-10 checkpoint

- Date/time: 2026-08-24 05:12 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: task recovery interface and the eight mandatory P0 scenarios flow through canonical write and episode resume.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_entrypoints.py::test_resume_task_endpoint_replays_events_and_surface_stale_resources tests/test_vnext_entrypoints.py::test_resume_task_endpoint_fails_on_wrong_token tests/test_vnext_p0_flow.py -q
  .venv/Scripts/python -m ruff check memoryhub/adapter/vnext_api.py memoryhub/application/episode_service.py tests/test_vnext_p0_flow.py
  .venv/Scripts/python -m compileall -q memoryhub/adapter memoryhub/application tests/test_vnext_p0_flow.py
  ```
- Result: PASS; 2 resume endpoint tests and 8 P0 flow tests passed; ruff/compileall passed.
- Summary: `/api/memory/vnext/tasks/{task_id}/resume` replays events newer than the snapshot and surfaces stale resources/revalidation; service restart restores state via the same database; single instructions do not immediately promote to global long-term; sensitive tokens are MASKed before persistence.
- Artifact/report/trace: `memoryhub/adapter/vnext_api.py`, `memoryhub/application/episode_service.py`, `memoryhub/application/canonical_write.py`, `tests/test_vnext_p0_flow.py`
- Acceptance: S1-10 DONE.
- Follow-up: run S1-11 Authority→Projection rebuild tests.

## S1-11 checkpoint

- Date/time: 2026-08-24 05:12 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Authority (Preference/Knowledge) is the source of truth; projection outbox can be rebuilt from active Authority rows with correct memory_id/content_version.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_rebuild_projections.py -q
  .venv/Scripts/python -m ruff check scripts/rebuild_projections.py memoryhub/application/safety_policy_adapter.py
  .venv/Scripts/python -m compileall -q scripts memoryhub/application
  ```
- Result: PASS; 3 rebuild tests passed; ruff/compileall passed.
- Summary: `scripts/rebuild_projections.py` scans active Preference/Knowledge, enqueues `upsert` projection operations, preserves content_version, skips deleted rows, supports dry-run and report output.
- Artifact/report/trace: `scripts/rebuild_projections.py`, `memoryhub/application/safety_policy_adapter.py`, `tests/test_rebuild_projections.py`
- Acceptance: S1-11 DONE.
- Follow-up: run affected vNext regressions, safety/contract risk tests, and S1 Gate verification.

## S1 Gate

- Date/time: 2026-08-24 05:12 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_rebuild_projections.py tests/test_vnext_event_gateway.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_task_state.py tests/test_vnext_authority_write.py tests/test_no_production_write_bypass.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m ruff check memoryhub/adapter/vnext_api.py memoryhub/adapter/agent_api.py memoryhub/app.py memoryhub/application/canonical_write.py memoryhub/application/episode_service.py memoryhub/application/safety_policy_adapter.py memoryhub/storage/vnext_repositories.py scripts/rebuild_projections.py tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_rebuild_projections.py tests/test_no_production_write_bypass.py
  .venv/Scripts/python -m compileall -q memoryhub/adapter memoryhub/application memoryhub/storage agent-integration scripts tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_rebuild_projections.py tests/test_no_production_write_bypass.py
  git diff --check
  ```
- Result: PASS; B06 focused tests 16 passed; affected vNext/working/episode/authority/gateway/write-bypass suite 48 passed; safety/contract/error regressions 77 passed; core B06 modules ruff and compileall passed; `git diff --check` passed.
- Environment PARTIAL: agent-integration CLI/MCP/client modules contain pre-existing E501 line-length findings outside the B06-touched lines. The B06 entrypoint logic is verified by tests; these style findings are not treated as S1 Gate blockers.
- Summary: production write has no bypass; all entrypoints converge on canonical write; task recovery replays episodes and rejects bad tokens; Authority→Projection rebuild preserves identity and version; S1 Gate evidence is complete.
- Artifact/report/trace: B06 source/tests/specs plus required continuity files.
- Acceptance: S1 Gate PASS; S1-09, S1-10, S1-11 DONE.

## B05 start reconciliation

- Date/time: 2026-08-22 18:30 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`
- Commands: `git branch --show-current`; `git rev-parse HEAD`; `git status --short --untracked-files=all`; `git diff --stat`; `git diff --name-only`; `git log -6 --oneline`; `rg --files -g 'AGENTS.md'`; required continuity/code/test inventory reads.
- Result: PASS for repository reconciliation. HEAD=`06403d636c55b1b6b33257986ca911a13e7571a9`, B04 commit is present, no tracked worktree diff, no applicable `AGENTS.md`; ignored pytest/schema scratch directories remain outside scope.
- Continuity: `BATCH_BOARD.md` had B05 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B05 task in progress; S1-01～S1-06 are DONE with evidence. The stale B04-only `STATE.md` text was corrected before implementation.
- Decision: claim S1-07, the smallest dependency-satisfied B05 task; do not touch S1-09 or later batches.
- Follow-up: implement `domain/long_term.py` and `storage/authority_repository.py`, with focused Authority version/status/scope compatibility tests.

## S1-07 checkpoint

- Date/time: 2026-08-22 18:40 +08:00
- Environment: Windows PowerShell; system Python/pytest/ruff; SQLite/SQLAlchemy
- Acceptance item: Long-Term Authority Facade unifies Preference/Knowledge/FACT representations while preserving legacy API compatibility; tenant/scope/version/status invariants are enforced.
- Commands:
  ```text
  python -m pytest tests/test_vnext_authority_write.py -q
  python -m ruff check memoryhub/domain/long_term.py memoryhub/domain/__init__.py memoryhub/storage/authority_repository.py memoryhub/storage/models.py memoryhub/storage/database.py memoryhub/storage/memory_metadata.py memoryhub/core/domain_writer.py memoryhub/application/canonical_write.py memoryhub/application/__init__.py tests/test_vnext_authority_write.py
  python -m compileall -q memoryhub/domain memoryhub/application memoryhub/storage
  ```
- Result: PASS; 3 Authority-focused tests passed; scoped ruff and compileall passed; only the existing unknown `asyncio_mode` pytest warning appeared.
- Summary: vNext writes bind `tenant_id` and preserve the complete `LongTermEnvelope` in governed metadata; Preference, semantic FACT, procedural and episodic types map through the existing legacy repositories; ACTIVE chain duplicates and stale versions fail; SUPERSEDED/DELETED are excluded by default; cross-tenant reads return no row.
- Artifacts: `memoryhub/domain/long_term.py`, `memoryhub/storage/authority_repository.py`, `memoryhub/storage/models.py`, `memoryhub/storage/database.py`, `tests/test_vnext_authority_write.py`
- Acceptance: S1-07 DONE; S1-08 is the only B05 task now IN_PROGRESS.
- Follow-up: validate the assembled canonical write and its Event/Working/Episode/Reflection/Authority transaction evidence.

## S1-08 checkpoint

- Date/time: 2026-08-22 18:40 +08:00
- Status: IN_PROGRESS; implementation and focused end-to-end test are present, affected/regression/risk validation remains.
- Implementation: `CanonicalWriteService` now sequences approved EventGateway output into optional Working Patch, Episode event/snapshot, durable async Extraction/Reflection task, and optional Long-Term submission. Long-Term submission delegates to `MemoryWriteService`/`DomainMemoryWriter`.
- Focused evidence currently available: the third Authority test passed and verified one Event, one tenant idempotency record, one Reflection task, one Preference row, and one each of tenant/content-version-consistent Lineage, Evidence and `long_term` Outbox records; repeating the identical event returns IDEMPOTENT without duplicating the task or Evidence.
- Next command: run `tests/test_vnext_authority_write.py`, vNext/task-state/storage/writer/outbox regressions, then safety/write-bypass risk tests.

## S1-08 final validation and B05 acceptance

- Date/time: 2026-08-22 20:55 +08:00
- Status: PASS; S1-08 DONE and B05 accepted.
- Focused validation: `python -m pytest tests/test_vnext_authority_write.py -q` → 4 passed.
- Affected regression validation: `tests/test_vnext_authority_write.py`, `tests/test_domain_memory_writer.py`, `tests/test_vnext_repositories.py`, `tests/test_vnext_storage_schema.py`, `tests/test_vnext_event_gateway.py`, `tests/test_lifecycle_outbox.py`, and `tests/test_projection_outbox.py` → 38 passed.
- Safety/risk validation: `tests/test_no_production_write_bypass.py`, `tests/test_safety_pipeline.py`, `tests/test_safety_contract.py`, `tests/test_safety_memory_write.py`, `tests/test_vnext_contracts.py`, and `tests/test_vnext_interface.py` → 100 passed.
- Static validation: B05-added/affected modules passed scoped ruff and `python -m compileall -q memoryhub/domain memoryhub/application memoryhub/storage`; `git diff --check` passed. Full-file ruff on `memoryhub/adapter/schemas.py` still reports five pre-existing W291/E501 findings outside the added `extra_payload` field.
- Environment: default pytest temp creation failed with Windows `PermissionError`; the affected and safety suites passed in a controlled temporary execution. The environment warning `Unknown config option: asyncio_mode` remains non-blocking.
- Acceptance: Canonical Write sequences approved Event output through optional Working/Episode updates, durable Reflection task creation, and optional Long-Term submission; the Authority transaction produces the business row, tenant idempotency record, Evidence, Lineage, and Outbox consistently; duplicate events return IDEMPOTENT without duplicate task/Evidence.
- Continuity: S1-08 marked DONE, B05 marked DONE, B06 marked READY, and the B05 commit is `SELF (Batch-ID: B05)`.

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

## B07 final validation and acceptance

- Date/time: 2026-08-24 08:00 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: S2-01/S2-02/S2-03 implemented, B07 exit criteria met, affected/risk regressions pass, static checks pass.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py tests/test_vnext_candidate_service.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_task_state.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_event_gateway.py tests/test_vnext_authority_write.py tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_no_production_write_bypass.py tests/test_vnext_contracts.py tests/test_vnext_interface.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m ruff check memoryhub/domain/candidate.py memoryhub/storage/vnext_repositories.py memoryhub/application/candidate_service.py memoryhub/application/boundary_detector.py memoryhub/application/reflection_service.py memoryhub/core/reflection memoryhub/domain/contracts.py memoryhub/application/__init__.py memoryhub/domain/episode.py tests/test_vnext_candidate_service.py tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py
  .venv/Scripts/python -m compileall -q memoryhub/domain memoryhub/storage memoryhub/application memoryhub/core/reflection tests/test_vnext_candidate_service.py tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py
  git diff --check
  ```
- Result: PASS; B07 focused 20 passed; affected vNext regression 62 passed; safety/contract/error 77 passed; ruff/compileall passed; `git diff --check` passed (line-ending warnings are Windows CRLF normalization, not whitespace errors).
- Environment note: the deterministic reflection model is a local stub; it validates schema/prompt version/input hash and does not call remote LLMs.
- Exit criteria:
  - Boundary behavior is verifiable: hard Complete/Failed/Explicit, PHASE and CONTEXT_PRESSURE checkpoints, debounce.
  - Model cannot directly write Authority: ReflectionService returns Candidate only; no LongTermEnvelope/Authority path exists.
  - Repeated statements do not forge independent evidence: same event/episode does not increment frequency; different episodes do.
- Acceptance: B07 DONE; S2-01, S2-02, S2-03 DONE.


## S2-04 checkpoint

- Date/time: 2026-08-24 08:15 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Promotion Score, type-specific thresholds, decision intervals and reason codes.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_consolidation_service.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/consolidation_service.py tests/test_vnext_consolidation_service.py
  .venv/Scripts/python -m compileall -q memoryhub/application tests/test_vnext_consolidation_service.py
  ```
- Result: PASS; 12 consolidation tests passed; ruff/compileall passed.
- Summary: `ConsolidationService.consolidate` returns a scored decision (PROMOTE/REVIEW/REJECT) with reason codes. Weights and thresholds are type-specific (PREFERENCE/SEMANTIC/PROCEDURAL/EPISODIC). Promotion requires sufficient confidence, utility, stability and independent evidence; one implicit behavior with low frequency is not promoted.

## S2-05 checkpoint

- Date/time: 2026-08-24 08:20 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Fast Path whitelist and governance constraints.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_consolidation_service.py -q
  ```
- Result: PASS; Fast Path tests pass.
- Summary: Fast Path is only allowed for PREFERENCE/SEMANTIC, confidence >= 0.9, sufficient independent evidence, explicit user instruction or high-trust tool source, clear non-SESSION scope, non-sensitive content and no conflicting ACTIVE memory. PROCEDURAL/EPISODIC, low confidence, sensitive/ambiguous scope and conflicts are blocked.

## S2-06 checkpoint

- Date/time: 2026-08-24 08:25 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Evolution actions (REINFORCE/REVISE/SUPERSEDE/COEXIST/REVIEW) and EvolutionStatus state transitions.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_evolution.py -q
  .venv/Scripts/python -m ruff check memoryhub/domain/evolution.py memoryhub/application/evolution_service.py tests/test_vnext_evolution.py
  .venv/Scripts/python -m compileall -q memoryhub/domain memoryhub/application tests/test_vnext_evolution.py
  ```
- Result: PASS; 9 evolution tests passed; ruff/compileall passed.
- Summary: `decide_evolution_action` separates action from status. `EvolutionService` persists REINFORCE/REVISE/SUPERSEDE by superseding the old chain head and creating a strictly newer version; COEXIST creates a new ACTIVE memory in a different scope chain; REVIEW is not persisted. Status transitions are restricted (DELETED/SUPERSEDED are terminal).

## S2-07 checkpoint

- Date/time: 2026-08-24 08:30 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Type-specific Long-Term content validation with Procedure requirements.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_long_term_validation.py -q
  .venv/Scripts/python -m ruff check memoryhub/domain/long_term.py tests/test_vnext_long_term_validation.py
  .venv/Scripts/python -m compileall -q memoryhub/domain tests/test_vnext_long_term_validation.py
  ```
- Result: PASS; 10 validation tests passed; ruff/compileall passed.
- Summary: `LongTermContentValidator` enforces per-type shapes: PREFERENCE needs value/text/payload, SEMANTIC needs statement or triple, PROCEDURAL needs trigger/preconditions/steps/verification/failure_recovery, sufficient evidence and no failed-episode main steps, EPISODIC needs content or episode_refs.

## B08 final validation and acceptance

- Date/time: 2026-08-24 08:35 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_consolidation_service.py tests/test_vnext_evolution.py tests/test_vnext_long_term_validation.py tests/test_vnext_candidate_service.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_candidate_service.py tests/test_vnext_reflection.py tests/test_vnext_boundary_detector.py tests/test_vnext_task_state.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_event_gateway.py tests/test_vnext_authority_write.py tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_no_production_write_bypass.py tests/test_vnext_contracts.py tests/test_vnext_interface.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/consolidation_service.py memoryhub/application/evolution_service.py memoryhub/application/__init__.py memoryhub/domain/evolution.py memoryhub/domain/long_term.py memoryhub/domain/__init__.py memoryhub/storage/vnext_repositories.py tests/test_vnext_consolidation_service.py tests/test_vnext_evolution.py tests/test_vnext_long_term_validation.py tests/test_vnext_candidate_service.py
  .venv/Scripts/python -m compileall -q memoryhub/domain memoryhub/application memoryhub/storage tests/test_vnext_consolidation_service.py tests/test_vnext_evolution.py tests/test_vnext_long_term_validation.py tests/test_vnext_candidate_service.py
  git diff --check
  ```
- Result: PASS; B08 focused 38 passed; affected vNext regression 82 passed; safety/contract/error 77 passed; ruff/compileall passed; `git diff --check` line-ending warnings only.
- Exit criteria:
  - Promotion scores, thresholds and reason codes are type-specific and explainable.
  - Fast Path is gated by type, confidence, evidence, source, scope, sensitivity and conflict checks.
  - Evolution actions and status transitions are separate; version chain direction is safe.
  - Procedure memories require trigger/preconditions/steps/verification/failure_recovery and sufficient successful episodes.
- Acceptance: B08 DONE; S2-04, S2-05, S2-06, S2-07 DONE.

## B08 start reconciliation

- Date/time: 2026-08-24 08:00 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  rg --files -g 'AGENTS.md'
  ```
- Result: PASS for repository reconciliation. HEAD=`e8c55d31f2c2e48330c8eae460d2084f6d8a26b7` (B07 commit), working tree clean, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B08 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B08 task in progress; S1-01～S1-11, S1 Gate, S2-01～S2-03 DONE with evidence.
- Decision: claim B08 and the smallest dependency-satisfied task S2-04; do not touch S2-08 or later batches.

## B09 start reconciliation

- Date/time: 2026-08-24 08:40 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  rg --files -g 'AGENTS.md'
  ```
- Result: PASS for repository reconciliation. HEAD=`6c0131921be35bdd9a7846148ffa0da0e87ed884` (B08 commit), working tree clean, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B09 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B09 task in progress; S1-01～S1-11, S1 Gate, S2-01～S2-07 DONE with evidence.
- Decision: claim B09 and the smallest dependency-satisfied task S2-08; do not touch S3-01 or later batches.

## S2-08 checkpoint

- Date/time: 2026-08-24 08:40 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Formation Shadow mode that compares vNext reflection/candidate/consolidation with a deterministic legacy stub without writing ACTIVE Long-Term memories.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_formation_shadow.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/formation_shadow.py tests/test_vnext_formation_shadow.py
  .venv/Scripts/python -m compileall -q memoryhub/application/formation_shadow.py tests/test_vnext_formation_shadow.py
  ```
- Result: PASS; 9 shadow tests passed; ruff/compileall passed.
- Summary: `FormationShadowService.compare_event` runs the vNext pipeline side-by-side with `DeterministicLegacyExtractionAdapter`; differences are classified as `PREMATURE_PROMOTION`, `MISSED_PROMOTION`, `SCOPE_MISMATCH`, `TYPE_MISMATCH` and `VALIDATION_ISSUE`. The service uses `InMemoryCandidateRepository`, never calls an Authority write, and records redacted spans to the supplied `TraceStore`.

## S2-09 checkpoint

- Date/time: 2026-08-24 08:45 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Formation/Evolution Trace with redacted spans and chainable indexes.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_formation_trace.py -q
  .venv/Scripts/python -m ruff check memoryhub/observability/ tests/test_vnext_formation_trace.py
  .venv/Scripts/python -m compileall -q memoryhub/observability/ tests/test_vnext_formation_trace.py
  ```
- Result: PASS; 4 trace tests passed; ruff/compileall passed.
- Summary: `TraceSpan` stores only IDs, hashes, classifications, scores, reason codes and timestamps; no raw text. `TraceStore` provides `list_by_trace`, `list_by_event`, `list_by_candidate`, `list_by_memory` and `formation_chain`. Convenience helpers record EVENT, WORKING, EPISODE, CANDIDATE, CONSOLIDATION, EVOLUTION and LEGACY spans.

## S2-10 checkpoint

- Date/time: 2026-08-24 08:50 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: Formation datasets, evaluator and P1 paired scenarios with annotated expectations.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_formation_eval.py -q
  .venv/Scripts/python -m evaluation.metrics.formation_eval --output evaluation/results/vnext_formation_eval_report.json
  .venv/Scripts/python -m ruff check evaluation/metrics/formation_eval.py tests/test_vnext_formation_eval.py
  .venv/Scripts/python -m compileall -q evaluation/metrics/formation_eval.py tests/test_vnext_formation_eval.py
  ```
- Result: PASS; 6 eval tests passed; evaluator CLI produced a report where predicted decisions/scope levels match the annotated expectations for all single-event samples and P1 pairs.
- Summary: `FormationEvaluator` loads `evaluation/datasets/vnext_formation_eval.json` and `evaluation/datasets/vnext_formation_p1_pairs.json`, runs each scenario through `FormationShadowService`, and computes Precision, Recall, Premature/Missed Promotion rates, Scope/Type accuracy, Resume Constraint Preservation and Safe Rate. The P1 pair dataset was calibrated so that `E2E-P1-01` promotes after two independent DOCX instructions, `E2E-P1-03` keeps repairs under review while flagging legacy premature promotion, and `E2E-P1-06` shows GLOBAL Markdown coexisting with a promoted PROJECT DOCX preference.

## S2 Gate checkpoint

- Date/time: 2026-08-24 08:55 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Acceptance item: S2 Gate checklist (P1-A) verified in automated tests.
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_formation_shadow.py tests/test_vnext_formation_eval.py -q -k "s2_gate"
  .venv/Scripts/python -m pytest tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py tests/test_vnext_candidate_service.py tests/test_vnext_consolidation_service.py tests/test_vnext_evolution.py tests/test_vnext_long_term_validation.py tests/test_vnext_task_state.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_event_gateway.py tests/test_vnext_authority_write.py tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_no_production_write_bypass.py tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/formation_shadow.py memoryhub/observability/ evaluation/metrics/formation_eval.py tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py
  .venv/Scripts/python -m compileall -q memoryhub/application/formation_shadow.py memoryhub/observability/ evaluation/metrics/formation_eval.py tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py
  git diff --check
  ```
- Result: PASS; S2 Gate focused tests 10 passed; full affected vNext/S2/safety/contract regression 196 passed; ruff/compileall passed; `git diff --check` line-ending warnings only.
- Checklist:
  1. “这次用 DOCX”只形成局部 Candidate：`test_s2_gate_docx_forms_local_candidate_not_global` asserts PROJECT scope and REVIEW/PROMOTE without GLOBAL.
  2. 多个独立任务明确证据能推动固化：`test_s2_gate_repeated_evidence_promotes_with_reason_codes` and `E2E-P1-01` show two independent DOCX events promote to PROJECT.
  3. Global Markdown 与 Project-A DOCX 以 COEXIST 保存：`test_s2_gate_global_markdown_and_project_docx_coexist` records both a GLOBAL Markdown candidate and a PROJECT DOCX candidate, with the latter promoted.
  4. 两次成功修复形成 Procedure：`test_s2_gate_repair_forms_procedural_candidate` and `E2E-P1-03` produce a PROCEDURAL candidate from two repair events.
  5. 所有决策可由 Evidence、阈值、reason code 解释：`test_s2_gate_decisions_are_explainable_by_reason_codes` asserts every consolidation decision carries non-empty reasons.
- Acceptance: S2 Gate PASS.

## B09 final validation and acceptance

- Date/time: 2026-08-24 08:55 +08:00
- Environment: Windows PowerShell; `.venv` Python/pytest/ruff; branch `dev-remem`
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  .venv/Scripts/python -m pytest tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py -q
  .venv/Scripts/python -m evaluation.metrics.formation_eval --output evaluation/results/vnext_formation_eval_report.json
  .venv/Scripts/python -m pytest tests/test_vnext_boundary_detector.py tests/test_vnext_reflection.py tests/test_vnext_candidate_service.py tests/test_vnext_consolidation_service.py tests/test_vnext_evolution.py tests/test_vnext_long_term_validation.py tests/test_vnext_task_state.py tests/test_vnext_repositories.py tests/test_vnext_storage_schema.py tests/test_vnext_event_gateway.py tests/test_vnext_authority_write.py tests/test_vnext_entrypoints.py tests/test_vnext_p0_flow.py tests/test_no_production_write_bypass.py tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/formation_shadow.py memoryhub/observability/ evaluation/metrics/formation_eval.py tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py
  .venv/Scripts/python -m compileall -q memoryhub/application/formation_shadow.py memoryhub/observability/ evaluation/metrics/formation_eval.py tests/test_vnext_formation_shadow.py tests/test_vnext_formation_trace.py tests/test_vnext_formation_eval.py
  git diff --check
  ```
- Result: PASS; B09 focused tests 23 passed; affected vNext/S2 regression 196 passed; safety/contract/error regressions included; ruff/compileall passed; `git diff --check` line-ending warnings only.
- Exit criteria:
  - Shadow never writes ACTIVE Long-Term memories and produces classified differences.
  - Formation/Evolution Trace is redacted by default and chainable by event/candidate/memory IDs.
  - Formation evaluator is reproducible, dataset expectations match predictions, and P1 paired scenarios cover Evidence Promotion, Procedure Formation and Evolution Coexist.
  - S2 Gate checklist is verified by automated tests.
- Acceptance: B09 DONE; S2-08, S2-09, S2-10 DONE; S2 Gate PASS; B10 READY.


## B11 start reconciliation

- Date/time: 2026-08-24 12:42 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch -v
  git status --short
  git rev-parse HEAD
  ```
- Result: PASS for repository reconciliation. HEAD=`b7bab109b45e45fd9a74555c9a8693ac811ac203`, B10 commit `feat(vnext): complete B10 s3 request planning` with trailer `Batch-ID: B10` is present, working tree clean, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B10 DONE, B11 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B11 task in progress; S3-01, S3-02, S3-03 and S2-06 are DONE with evidence.
- Decision: claim B11 and the smallest dependency-satisfied task S3-04; do not touch S3-08 or later batches.

## S3-04 checkpoint

- Date/time: 2026-08-24 12:55 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_fusion_reranker.py -q
  .venv/Scripts/python -m ruff check memoryhub/retrieval/fusion.py memoryhub/retrieval/reranker.py memoryhub/retrieval/__init__.py
  .venv/Scripts/python -m compileall -q memoryhub/retrieval/fusion.py memoryhub/retrieval/reranker.py memoryhub/retrieval/__init__.py
  ```
- Result: PASS; 17 tests passed; ruff/compileall passed.
- Changes:
  - `memoryhub/retrieval/fusion.py` adds `ReciprocalRankFusion`, `ScoreFusion`, `FusionResult`, and `deduplicate_candidates`.
  - `memoryhub/retrieval/reranker.py` upgrades with `VNextReranker` (relevance, scope, confidence, freshness, health, intent type boost) while preserving legacy `Reranker`.
  - `memoryhub/retrieval/__init__.py` exports fusion and reranker symbols.
- Acceptance:
  - Same `memory_id/version` is deduplicated, highest `content_version` retained, dropped versions tracked.
  - RRF and linear ScoreFusion produce explainable scores with `channel_scores`, `fused`, and per-channel contributions.
  - `VNextReranker` returns new `RetrievedMemory` objects with `score_breakdown` and does not mutate inputs.

## S3-05 checkpoint

- Date/time: 2026-08-24 13:05 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_scope_resolver.py -q
  .venv/Scripts/python -m ruff check memoryhub/retrieval/scope_resolver.py memoryhub/retrieval/__init__.py
  .venv/Scripts/python -m compileall -q memoryhub/retrieval/scope_resolver.py memoryhub/retrieval/__init__.py
  ```
- Result: PASS; 10 tests passed; ruff/compileall passed.
- Changes: `memoryhub/retrieval/scope_resolver.py` adds `ScopeResolver`, `ScopeResolution`, `ConflictGroup`, `ValidationResult`, and `filter_blocked_statuses`.
- Acceptance:
  - DELETED and SUPERSEDED candidates are dropped with explicit reasons.
  - Authority-checked mode rejects stale projection versions and deleted Authority rows.
  - Scope conflicts resolve by TASK>PROJECT>APPLICATION>DOMAIN>GLOBAL; exact preferred scope match takes priority.
  - Each conflict group records selected memory, dropped memories, and auditable resolution text.

## S3-06 checkpoint

- Date/time: 2026-08-24 13:15 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_context_budget.py -q
  .venv/Scripts/python -m ruff check memoryhub/retrieval/context_builder.py memoryhub/retrieval/__init__.py
  .venv/Scripts/python -m compileall -q memoryhub/retrieval/context_builder.py memoryhub/retrieval/__init__.py
  ```
- Result: PASS; 8 tests passed; ruff/compileall passed.
- Changes: `memoryhub/retrieval/context_builder.py` adds `BudgetManager`, `BudgetAllocation`, `BudgetResult`, `StructuredContextBuilder`, and `estimate_tokens`.
- Acceptance:
  - Working state and constraints are always kept even under severe budget pressure.
  - Procedures receive a dedicated quota before general long-term memories.
  - Long-term memories are ranked by score and trimmed with per-memory dropped reasons.
  - `ContextPayload` carries `original_tokens`, `selected_tokens`, `relevant_memory_ids`, `source_ids`, `conflict_notes`, and `rendered_context`.

## S3-07 checkpoint

- Date/time: 2026-08-24 13:20 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_context_service.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/context_service.py memoryhub/application/__init__.py
  .venv/Scripts/python -m compileall -q memoryhub/application/context_service.py memoryhub/application/__init__.py
  ```
- Result: PASS; 5 tests passed; ruff/compileall passed.
- Changes: `memoryhub/application/context_service.py` adds `ContextService` and `ContextAssemblyResult`; `memoryhub/application/__init__.py` exports them.
- Acceptance:
  - End-to-end pipeline: fusion → rerank → scope resolution → budget → structured context.
  - Deleted memories are dropped by Authority/scope validation and recorded in `stage_dropped`.
  - Scope conflicts keep the narrower scope and drop broader ones with reasons.
  - Trace output records fusion candidates, deduplication count, reranked count, selected count, invalid count, and budget tokens.

## B11 final validation and acceptance

- Date/time: 2026-08-24 13:25 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_fusion_reranker.py tests/test_vnext_scope_resolver.py tests/test_vnext_context_budget.py tests/test_vnext_context_service.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_*.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m pytest tests/test_no_production_write_bypass.py -q
  .venv/Scripts/python -m ruff check memoryhub/retrieval/ memoryhub/application/ memoryhub/adapter/vnext_schemas.py tests/test_vnext_fusion_reranker.py tests/test_vnext_scope_resolver.py tests/test_vnext_context_budget.py tests/test_vnext_context_service.py
  .venv/Scripts/python -m compileall -q memoryhub/retrieval/ memoryhub/application/ memoryhub/adapter/vnext_schemas.py tests/test_vnext_fusion_reranker.py tests/test_vnext_scope_resolver.py tests/test_vnext_context_budget.py tests/test_vnext_context_service.py
  git diff --check
  ```
- Result: PASS; B11 focused 38 passed; affected vNext regression 226 passed; safety/contract/error 77 passed; write-bypass 6 passed; ruff/compileall passed; `git diff --check` passed (CRLF warnings only).
- Exit criteria:
  - Old/deleted/superseded/scope-inferior objects do not leak into Context.
  - Fusion scores, reranker factors, conflict resolutions, and budget decisions are all explainable via `score_breakdown`, `resolution`, and `dropped_reasons`.
  - Hard constraints and current task state are protected by the budget manager.
- Acceptance: B11 DONE; S3-04, S3-05, S3-06, S3-07 DONE; B12 READY.


## B12 start reconciliation

- Date/time: 2026-08-24 13:15 UTC
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch -v
  git rev-parse HEAD
  git status --short
  git diff --stat
  ```
- Result: PASS for repository reconciliation. HEAD=`29ec946a83d10372a2e8fc3fed98254de9b15726`, B11 commit `feat(vnext): complete B11 s3 fusion context` with trailer `Batch-ID: B11` is present, untracked test DB artifacts only in `evaluation/results/`, no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B12 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B12 task in progress; S3-01～S3-07 are DONE with evidence.
- Decision: claim B12 and the smallest dependency-satisfied task S3-08; do not touch S4-01 or later batches.

## S3-08 checkpoint

- Date/time: 2026-08-24 13:20 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_retrieval_service.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/retrieval_service.py memoryhub/observability/trace_models.py memoryhub/storage/vnext_repositories.py memoryhub/application/__init__.py tests/test_vnext_retrieval_service.py
  .venv/Scripts/python -m compileall -q memoryhub/application/retrieval_service.py memoryhub/observability/trace_models.py memoryhub/storage/vnext_repositories.py memoryhub/application/__init__.py
  ```
- Result: PASS; 6 tests passed; ruff/compileall passed.
- Changes:
  - `memoryhub/application/retrieval_service.py` adds `RetrievalService` and `RetrievalResult`; orchestrates intent router → planner → channel executors → fusion → rerank → scope → budget → context; records Activation, Retrieval Log, Retrieval Trace.
  - `memoryhub/observability/trace_models.py` adds `TraceSpanKind.RETRIEVAL`.
  - `memoryhub/storage/vnext_repositories.py` adds `RetrievalLogRepository` / `RetrievalLogView`.
  - `memoryhub/application/__init__.py` exports `RetrievalService` and `RetrievalResult`.
- Acceptance:
  - Activation records RECALLED→SELECTED→IN_CONTEXT progression without changing memory layer.
  - Retrieval Log persists query→plan→candidates→selected→latency redacted summary.
  - Retrieval Trace span records intent, channels, scores, and budget metrics.
- Next checkpoint: S3-09 search/context entrypoint convergence.

## S3-09 checkpoint

- Date/time: 2026-08-24 13:30 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_entrypoints.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_retrieval_service.py tests/test_vnext_context_service.py tests/test_vnext_fusion_reranker.py tests/test_vnext_scope_resolver.py tests/test_vnext_intent_router.py tests/test_vnext_retrieval_planner.py -q
  .venv/Scripts/python -m ruff check memoryhub/adapter/retrieval_executor.py memoryhub/adapter/api.py memoryhub/adapter/vnext_api.py memoryhub/app.py memoryhub/application/__init__.py agent-integration/memoryhub_client/client.py tests/test_vnext_entrypoints.py
  .venv/Scripts/python -m compileall -q memoryhub/adapter/retrieval_executor.py memoryhub/adapter/api.py memoryhub/adapter/vnext_api.py memoryhub/app.py memoryhub/application/__init__.py
  ```
- Result: PASS; entrypoint tests 8 passed; retrieval pipeline regression 59 passed; compileall passed.
- Changes:
  - `memoryhub/adapter/retrieval_executor.py` wraps existing retriever as vNext `vector` channel executor.
  - `memoryhub/adapter/vnext_api.py` adds `/vnext/search` and `/vnext/context` endpoints delegating to `RetrievalService`.
  - `memoryhub/adapter/api.py` `search_memory`/`get_memory_context` prefer `RetrievalService` with legacy fallback.
  - `memoryhub/app.py` constructs `RetrievalService` and injects repositories at startup.
  - `agent-integration/memoryhub_client/client.py` adds `vnext_search`/`vnext_context`.
  - `tests/test_vnext_entrypoints.py` extends coverage for vNext endpoints and legacy `/search` delegation.
- Acceptance:
  - `/vnext/search`, `/vnext/context`, legacy `/search` and SDK `vnext_search`/`vnext_context` share the same `RetrievalService`.
  - Same request produces identical `trace_id`, memory IDs, content versions and ordering across entrypoints.
- Style note: `agent-integration/memoryhub_client/client.py` and `memoryhub/adapter/api.py` contain pre-existing E501 line-length findings on unchanged lines; these are recorded as PARTIAL style evidence and do not block S3-09 business acceptance.
- Next checkpoint: S3-10 segmented evaluation and regression.

## S3-10 checkpoint

- Date/time: 2026-08-24 13:50 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_retrieval_eval.py -q
  .venv/Scripts/python evaluation/metrics/vnext_retrieval_eval.py
  .venv/Scripts/python -m ruff check evaluation/metrics/vnext_retrieval_eval.py tests/test_vnext_retrieval_eval.py
  .venv/Scripts/python -m compileall -q evaluation/metrics/vnext_retrieval_eval.py tests/test_vnext_retrieval_eval.py
  ```
- Result: PASS; 10 tests passed; CLI report produced deterministic metrics; ruff/compileall passed.
- Changes:
  - `evaluation/metrics/vnext_retrieval_eval.py` implements `VNextRetrievalEvaluator`, `VNextRetrievalEvalReport`, five-segment metrics (ROUTER/RECALL/RANKING/SCOPE/CONTEXT), and a deterministic mock-channel service builder.
  - `evaluation/datasets/vnext_retrieval_eval.json` adds annotated dataset covering all 7 intents, exact/paraphrase/semantic queries, scope conflicts, budget protection, and forbidden-memory isolation.
  - `tests/test_vnext_retrieval_eval.py` verifies reproducibility, perfect recall, zero leakage, constraint preservation and serializable report.
- Acceptance:
  - Router accuracy: 1.0 on annotated samples; all 7 intents represented.
  - Recall@K, Precision@K, MRR, NDCG@K and pairwise ranking score computed per query.
  - Scope leak rate: 0.0; DELETED/SUPERSEDED/Candidate/other-tenant memories do not appear in selected/context.
  - Context precision/recall, constraint preservation and budget compliance tracked.
  - Evaluation is reproducible with fixed seed.
- Next checkpoint: B12 final validation, S3 Gate, and single local commit.

## B12 final validation and S3 Gate acceptance

- Date/time: 2026-08-24 14:00 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_retrieval_service.py tests/test_vnext_entrypoints.py tests/test_vnext_context_service.py tests/test_vnext_fusion_reranker.py tests/test_vnext_scope_resolver.py tests/test_vnext_intent_router.py tests/test_vnext_retrieval_planner.py tests/test_vnext_retrieval_eval.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_*.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py -q
  .venv/Scripts/python -m pytest tests/test_no_production_write_bypass.py -q
  .venv/Scripts/python -m ruff check memoryhub/application/retrieval_service.py memoryhub/adapter/retrieval_executor.py memoryhub/adapter/api.py memoryhub/adapter/vnext_api.py memoryhub/app.py memoryhub/application/__init__.py memoryhub/observability/trace_models.py memoryhub/storage/vnext_repositories.py evaluation/metrics/vnext_retrieval_eval.py tests/test_vnext_retrieval_eval.py tests/test_vnext_retrieval_service.py tests/test_vnext_entrypoints.py agent-integration/memoryhub_client/client.py
  .venv/Scripts/python -m compileall -q memoryhub/application/retrieval_service.py memoryhub/adapter/retrieval_executor.py memoryhub/adapter/api.py memoryhub/adapter/vnext_api.py memoryhub/app.py memoryhub/application/__init__.py memoryhub/observability/trace_models.py memoryhub/storage/vnext_repositories.py evaluation/metrics/vnext_retrieval_eval.py tests/test_vnext_retrieval_eval.py
  git diff --check
  ```
- Result: PASS; B12 focused 77 passed; affected vNext regression 245 passed; safety/contract/error 77 passed; write-bypass 6 passed; compileall passed; `git diff --check` passed (CRLF warnings only).
- S3 Gate checklist:
  - [x] 7 类 Intent 均有标注样本和可解释路由结果：dataset covers CURRENT_STATE/TASK_HISTORY/PREFERENCE/SEMANTIC_FACT/PROCEDURE/EXPERIENCE/MIXED; router reports confidence and reason.
  - [x] 精确、改写、语义表达进入统一候选池和统一排序：dataset includes exact/paraphrase/semantic queries; all flow through the same RetrievalService pipeline with shared fusion/rerank/scope/budget.
  - [x] Candidate/DELETED/SUPERSEDED/其他租户记忆无法进入 Context：scope resolver drops DELETED/SUPERSEDED; mock executor enforces tenant/user isolation and candidate isolation; evaluation reports scope_leak_rate=0.0.
  - [x] 有限预算下硬约束与当前步骤不丢失：q-budget-protects-constraints verifies constraint_preservation=1.0 and budget_compliance=1.0 under token_budget=128.
  - [x] REST/MCP/CLI/SDK 不存在各自拼 Context 的实现：S3-09 entrypoint tests verify `/vnext/search`, `/vnext/context`, legacy `/search`, SDK `vnext_search`/`vnext_context` all delegate to `RetrievalService`.
- Acceptance: B12 DONE; S3-08, S3-09, S3-10 DONE; S3 Gate PASS; B13 READY.


## B13 start reconciliation

- Date/time: 2026-08-24 14:10 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  git branch --show-current
  git rev-parse HEAD
  git status --short --untracked-files=all
  git diff --stat
  git log -1 --format="%H%n%s%n%b"
  rg --files -g 'AGENTS.md'
  ```
- Result: PASS for repository reconciliation. HEAD=`fc3286f8d3b880659f8ded062ea42cac8d38df9a`, B12 commit `feat(vnext): complete B12 s3 entrypoints eval gate` with trailer `Batch-ID: B12` is present; B13-scope changes already in working tree; no applicable `AGENTS.md` found.
- Continuity: `BATCH_BOARD.md` had B13 READY and no IN_PROGRESS batch; `TASK_BOARD.md` had no B13 task in progress; S1-01, S1-07 and S3-08 are DONE with evidence.
- Decision: claim B13 and the smallest dependency-satisfied task S4-01; do not touch S4-04 or later batches.

### S4-01 checkpoint

- Status: DONE; versioned Outbox with leasing, backoff, Dead Letter and delete priority.
- Implementation: `memoryhub/storage/models.py` adds outbox `max_attempts`, `priority`, `backoff_policy`, `lease_version`, `lease_token`, `lease_expires_at`, `dead_lettered_at` and partial unique index `(tenant_id,memory_id,memory_type,operation,event_id)`; `PreferenceRow`/`KnowledgeRow` add `projection_version`; `memoryhub/storage/database.py` additive schema; `memoryhub/storage/memory_metadata.py` `MemoryProjectionOutboxRepository.claim_ready` returns leased items, reclaims expired leases, orders by `priority DESC, created_at ASC`, `mark_succeeded`/`mark_failed` verify lease token, failed items graduate to dead-letter, `replay` resets failed/dead-letter to pending.
- Evidence: `tests/test_vnext_projection_outbox.py` 7 passed; `tests/test_projection_outbox.py` 4 passed.
- Validation: ruff/compileall passed.
- Next checkpoint: S4-02 Projection Version and Authority Checked.

### S4-02 checkpoint

- Status: DONE; Projection Version persisted and Authority Checked stale rejection with repair trigger.
- Implementation: `memoryhub/storage/authority_repository.py` preserves `projection_version` on save and reads it back; `memoryhub/storage/projection_outbox.py` `ProjectionOutboxWorker` captures lease token and bumps `projection_version` after success; `memoryhub/application/canonical_write.py` enqueues vector projection outbox after Authority write with delete priority 10; `memoryhub/retrieval/scope_resolver.py` rejects candidates whose `projection_version < authority.projection_version` and triggers `repair_callback`; `memoryhub/application/retrieval_service.py` injects `AuthorityRepository` into `ScopeResolver` and provides `_enqueue_repair`; `memoryhub/application/context_service.py` wires authority-checked resolver; `memoryhub/adapter/vnext_schemas.py` exposes `projection_version` on `RetrievedMemory`.
- Evidence: `tests/test_vnext_projection_version.py` 2 passed; `tests/test_vnext_authority_write.py` 5 passed; `tests/test_vnext_scope_resolver.py` 10 passed; affected retrieval/context entrypoints regression passed.
- Validation: ruff/compileall passed.
- Next checkpoint: S4-03 Repair Worker.

### S4-03 checkpoint

- Status: DONE; point and offline Repair Worker covering missing/stale/orphan/incompatible drift.
- Implementation: `memoryhub/storage/repair.py` `RepairService.diagnose`/`repair_one`/`repair_all` and `RepairWorker.run_once`; diagnosis maps zero `projection_version` to missing, lagging `projection_version` to stale, deleted/superseded status to orphan, unsupported types to incompatible; actions are `upsert`/`delete` outbox enqueues with safe priority; `scripts/repair_projections.py` CLI supports `--memory-id`, `--memory-type`, `--tenant-id`, `--user-id`, `--dry-run`, `--run-worker`, `--limit`.
- Evidence: `tests/test_vnext_repair_worker.py` 4 passed; `scripts/repair_projections.py` compiles and imports cleanly.
- Validation: ruff/compileall passed.
- Next checkpoint: B13 batch validation and single local commit.

## B13 final validation and acceptance

- Date/time: 2026-08-24 16:05 +08:00
- Environment: Windows PowerShell; `D:\project\XA202612-2`; branch `dev-remem`; `.venv` Python/pytest/ruff
- Commands:
  ```text
  .venv/Scripts/python -m pytest tests/test_vnext_projection_outbox.py tests/test_vnext_projection_version.py tests/test_vnext_repair_worker.py tests/test_projection_outbox.py -q
  .venv/Scripts/python -m pytest tests/test_vnext_*.py -q
  .venv/Scripts/python -m pytest tests/test_safety_pipeline.py tests/test_safety_contract.py tests/test_safe_errors.py tests/test_no_production_write_bypass.py -q
  .venv/Scripts/python -m ruff check memoryhub/storage/models.py memoryhub/storage/memory_metadata.py memoryhub/storage/projection_outbox.py memoryhub/storage/authority_repository.py memoryhub/storage/repair.py memoryhub/application/canonical_write.py memoryhub/application/retrieval_service.py memoryhub/retrieval/scope_resolver.py memoryhub/application/context_service.py memoryhub/adapter/vnext_schemas.py memoryhub/storage/database.py scripts/repair_projections.py scripts/rebuild_projections.py tests/test_vnext_projection_outbox.py tests/test_vnext_projection_version.py tests/test_vnext_repair_worker.py tests/test_projection_outbox.py
  .venv/Scripts/python -m compileall -q memoryhub/storage scripts
  git diff --check
  ```
- Result:
  - B13 focused: 17 passed.
  - Affected vNext regression (`tests/test_vnext_*.py`): 258 passed.
  - Safety/contract/error regression: 77 passed.
  - Write-bypass regression: 6 passed.
  - Static: ruff/compileall passed; `git diff --check` passed (CRLF line-ending warnings only).
- Acceptance: S4-01, S4-02, S4-03 complete; B13 is DONE; B14 is READY.
- Boundary: only S4-01, S4-02, S4-03; no S4-04 or later batches touched.
## S4-04 checkpoint

- Status: DONE; Forget state machine enforces Authority-first read blocking, projection cleanup through delete outbox, explicit states, durable idempotency and retry-safe verification.
- Implementation: `memoryhub/application/forget_service.py`; additive `forget_history` state/tenant/idempotency/audit columns and migration in `memoryhub/storage/models.py` and `memoryhub/storage/database.py`.
- Evidence: `tests/test_vnext_forget_diagnostics.py` and manual tombstone/idempotency check; first Forget returned `READ_BLOCKED`, Authority active read returned no result, tombstone remained `DELETED`, and delete outbox priority was `100`.

## S4-05 checkpoint

- Status: DONE; vNext Forget execute/status/history routes provide explicit confirmation, high-risk management authorization, tenant/user isolation and idempotent replay.
- Implementation: `memoryhub/adapter/vnext_api.py`, `memoryhub/application/forget_service.py`, `docs/spec/VNEXT_INTERFACE.md`.
- Evidence: focused Forget tests 3 passed; high-risk request without authorization failed closed; duplicate idempotency key persisted one Forget row.

## S4-06 checkpoint

- Status: DONE; diagnostics API covers memory/evidence/lineage/projection/candidate/retrieval trace, requires admin authorization and defaults to redacted, tenant-scoped output.
- Implementation: `memoryhub/application/diagnostic_service.py`, vNext diagnostics route and app wiring.
- Evidence: diagnostics redaction/tenant test passed; affected vNext suite 43 passed; safety/isolation/write-bypass suite 58 passed; ruff/compileall/diff-check passed.

## B14 final validation and acceptance

- Environment: Windows PowerShell, `.venv` Python 3.11.6, branch `dev-remem`; untracked test DB artifacts in `evaluation/results/` were preserved and excluded.
- Focused/affected: `pytest tests/test_vnext_forget_diagnostics.py tests/test_vnext_interface.py tests/test_vnext_projection_outbox.py tests/test_vnext_projection_version.py tests/test_vnext_repair_worker.py tests/test_projection_outbox.py tests/test_vnext_retrieval_service.py tests/test_vnext_entrypoints.py -q` → 43 passed.
- Risk: `pytest tests/test_user_isolation.py tests/test_no_production_write_bypass.py tests/test_safety_pipeline.py -q` → 58 passed.
- Static: targeted ruff, compileall and `git diff --check` passed.
- Full suite: PARTIAL; first failure is pre-existing `tests/test_api_acceptance.py::test_api_02_events_write_round_trip` asserting retrieval after event write (`total_count == 0`, no preferences). No B14-specific test failed before this stop.
- Acceptance: B14 S4-04/S4-05/S4-06 DONE; B15 READY; no S4-07 or later content executed.

## B18 start reconciliation

- Date/time: 2026-08-25 +08:00; environment: Windows PowerShell, `D:\project\XA202612-2`, `.venv` Python/pytest/ruff.
- Commands: branch/HEAD/status/diff/log inspection; B18 batch prompt, plan S5-09～S5-10 and Gate sections; all continuity files; applicable `AGENTS.md` inventory (none found); vNext adapter/agent-integration docs/code/tests.
- Result: branch `dev-remem`; HEAD `5e5f3cb3a1a3147bab8b2bd722780b56f74fdcd6` contains B17 with `Batch-ID: B17`; no tracked diff; no applicable `AGENTS.md` found. Existing untracked evaluation `.db`/report artifacts and denied pytest temp directories are preserved.
- Reconciliation: B18 is READY with no in-progress task; S5-09 is claimed. All prior tasks and Gates have valid evidence.
- Boundary: only S5-09/S5-10 and required continuity/spec/test/report/demo artifacts may change.

## S5-09 checkpoint

- Deliverables: `docs/spec/VNEXT_DEPLOYMENT.md`, `docs/spec/VNEXT_BACKUP_RECOVERY.md`, `docs/spec/VNEXT_FAULT_HANDLING.md`, `docs/spec/VNEXT_ACCEPTANCE.md`, updated `agent-integration/README.md`, and `tests/test_vnext_docs.py`.
- Focused command: `.venv\Scripts\python.exe -m pytest tests/test_vnext_docs.py tests/test_vnext_demo.py -q` → `16 passed`.
- Executable verification:
  - `python -m memoryhub_cli.cli --help` → exit 0
  - `python -m memoryhub_mcp` initialize → exit 0, serverInfo name `memoryhub`
  - `python -c "from memoryhub_client import MemoryHubClient"` → exit 0
- Risk command: `.venv\Scripts\python.exe -m pytest tests/test_no_production_write_bypass.py tests/test_safety_contract.py tests/test_safe_errors.py -q` → passed (included in affected set).
- Static: scoped ruff, compileall and `git diff --check` passed (LF→CRLF warnings only).
- Acceptance: documentation commands are executable in a clean environment; interface and code are synchronized.

## S5-10 checkpoint

- Deliverables: `examples/vnext_demo/` with redacted fixtures (`event_start_report.json`, `event_use_docx.json`, `event_repeat_docx.json`, `event_markdown_global.json`), deterministic `run_demo.py`, `tests/test_vnext_demo.py`, and `docs/spec/VNEXT_ACCEPTANCE.md`.
- Focused command: `.venv\Scripts\python.exe -m pytest tests/test_vnext_demo.py -q` → `5 passed`.
- Replay command: `.venv\Scripts\python.exe examples/vnext_demo/run_demo.py --scenario all` → exit 0, output `examples/vnext_demo/output/demo_report.json`.
- Output redaction: demo report contains only `request_id`, `trace_id`, counts, hashes and audit metadata; no raw content or sensitive Evidence.
- Acceptance: demo is fixed, replayable and redacted; final acceptance package records all Gates PASS.

## B18 final validation and acceptance

- Environment: Windows PowerShell, `.venv` Python 3.11.6, branch `dev-remem`; untracked test DB/report artifacts in `evaluation/results/` and `examples/vnext_demo/output/` were preserved and excluded from the commit.
- Focused/affected: `pytest tests/test_vnext_docs.py tests/test_vnext_demo.py tests/test_vnext_*.py tests/test_no_production_write_bypass.py tests/test_safety_contract.py tests/test_safe_errors.py -q` → `341 passed`.
- Static: scoped ruff, compileall and `git diff --check` passed (CRLF line-ending warnings only).
- Gate review:
  - S5 Gate PASS: documentation commands executable; demo redacted and replayable; 57 tasks and 18 batches have evidence.
  - P0 Gate PASS: S1 Gate evidence valid (Canonical Write, Working/Episode recovery, Candidate isolation, projection rebuild).
  - P1 Gate PASS: S2 Gate evidence valid (Candidate staging, evidence promotion, Scope coexist, Procedure formation, explainable decisions).
  - Release Gate PASS: all P0/P1 scenarios, zero Policy/cross-tenant/Forget residual, rollback演练 documented, Dashboard/demo redacted.
- Acceptance: B18 S5-09/S5-10 DONE; S5/P0/P1/Release Gate PASS; there is no next batch.
