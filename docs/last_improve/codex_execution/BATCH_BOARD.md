# MemoryHub vNext Batch Board

## B17 start reconciliation — 2026-08-25

- Repository truth is `dev-remem` at `330f4d27f04b0729a53a2b63b1ab5747eb6f6dcb`, the B16 commit with `Batch-ID: B16`.
- B17 is the sole active batch. No B17 task was previously in progress, so S5-05 is claimed as the smallest dependency-satisfied task.
- Pre-existing untracked evaluation reports/databases and inaccessible pytest temporary directories are preserved and excluded.
- S5-05 is DONE with focused and safety evidence; S5-06 is the sole in-progress formal task. S5-07/S5-08 remain TODO.
- S5-06 is DONE with migration apply/review evidence; S5-07 is now the sole in-progress formal task. S5-08 remains TODO.
- S5-07 is DONE with Formation/Retrieval Shadow and dual-read evidence; S5-08 is now DONE with gated rollout and rollback evidence.

## B16 start reconciliation — 2026-08-25

- Repository truth is `dev-remem` at `5841161ef9acf2457e26f619db61c0fc2a5e52e5`; the B15 commit with `Batch-ID: B15` is present. The prior board text that described a pending B15 commit was stale.
- B16 is the sole active batch. S5-01 is the smallest dependency-satisfied task and is now `IN_PROGRESS`; B17 remains untouched.
- Pre-existing untracked `evaluation/results/*.db` files and inaccessible pytest temporary directories are preserved and excluded from B16.

## B16 final validation and acceptance — 2026-08-25

- S5-01 through S5-04 are DONE. Trace chains are safe and correlatable; `evaluation/run_vnext_eval.py` produces the four-layer reproducible benchmark in one command; four-system comparison/ablations use a shared measurement contract; four Dashboard views default to redacted and require management authorization with audit records.
- B16 artifacts have focused, affected and safety regression evidence in `EVIDENCE.md#b16-final-validation-and-acceptance`. The combined `test_vnext_*.py` invocation exceeded the host's 30-second tool window and was not counted as PASS; direct affected suites and risk suite passed.
- B17 is READY only. No B17 source, test, research, task claim or modification was performed.

## B15 live reconciliation — 2026-08-25

- B15 was the sole active batch for this session; S4-07 and S4-08 are DONE and S4 Gate is PASS.
- B15 scope was limited to S4-07, S4-08, and S4 Gate. B16 remains untouched and is READY only.
- Start branch/HEAD: `dev-remem` / `d0ffff4745c3094a8437006fb2e7a5c38e5fd0e1`.

状态：TODO | READY | IN_PROGRESS | BLOCKED | DONE

> 一个会话只允许执行一个批次。批次完成后仅将下一批次置为 READY，并结束当前会话。

| Batch | Status | Formal tasks / Gate | Prompt | Commit reference | Note |
|---|---|---|---|---|---|
| B01 | DONE | S0-01～S0-04 | `../codex_batches/B01_s0_contracts.md` | `a502f9a` | 65 tests passed；独立提交完成 |
| B02 | DONE | S0-05～S0-08；S0 Gate | `../codex_batches/B02_s0_delivery_gate.md` | `1b84af1` | 46 passed、6 deselected；S0 Gate PASS |
| B03 | DONE | S1-01～S1-03 | `../codex_batches/B03_s1_storage_ingress.md` | `SELF (Batch-ID: B03)` | 11 定向、45 受影响回归通过；敏感正文、租户隔离、事务、并发、幂等证据有效；安全文件系统组合 PARTIAL 已记录 |
| B04 | DONE | S1-04～S1-06 | `../codex_batches/B04_s1_task_state.md` | `SELF (Batch-ID: B04)` | B04 完成；下一批次 B05 已置为 READY |
| B05 | DONE | S1-07～S1-08 | `../codex_batches/B05_s1_authority_write.md` | `SELF (Batch-ID: B05)` | S1-07/S1-08 验收通过；下一批次 B06 已置为 READY |
| B06 | DONE | S1-09～S1-11；S1 Gate | `../codex_batches/B06_s1_entrypoints_gate.md` | `b9432ab` | S1 Gate PASS；下一批次 B07 已置为 READY |
| B07 | DONE | S2-01～S2-03 | `../codex_batches/B07_s2_reflection_candidates.md` | `e8c55d3` | 边界、Reflection、Candidate 归一完成；B08 已置 READY |
| B08 | DONE | S2-04～S2-07 | `../codex_batches/B08_s2_consolidation_evolution.md` | `SELF (Batch-ID: B08)` | 固化与演化可解释、Fast Path 受约束、Procedure 来源受约束；B09 已置 READY |
| B09 | DONE | S2-08～S2-10；S2 Gate | `../codex_batches/B09_s2_shadow_eval_gate.md` | `1c08cde` | Shadow 不写 ACTIVE；Trace 默认脱敏；Formation 评测可复现；S2 Gate PASS；B10 已置 READY |
| B10 | DONE | S3-01～S3-03 | `../codex_batches/B10_s3_request_planning.md` | `SELF (Batch-ID: B10)` | 旧客户端兼容；7 类 Intent Router 可解释；Planner 多通道降级可见；B11 已置 READY |
| B11 | DONE | S3-04～S3-07 | `../codex_batches/B11_s3_fusion_context.md` | `SELF (Batch-ID: B11)` | Fusion/Reranker 可解释；Authority/Scope 冲突可解释；Budget 保护硬约束；Context Builder 结构化；B12 已置 READY |
| B12 | DONE | S3-08～S3-10；S3 Gate | `../codex_batches/B12_s3_entrypoints_eval_gate.md` | SELF (Batch-ID: B12) | S3 Gate PASS；所有入口一致 ID/版本/顺序/trace；评测可复现 |
| B13 | DONE | S4-01～S4-03 | `../codex_batches/B13_s4_projection_repair.md` | SELF (Batch-ID: B13) | Outbox lease/backoff/Dead Letter/delete priority; Projection Version; Repair Worker |
| B14 | DONE | S4-04～S4-06 | `../codex_batches/B14_s4_forget_diagnostics.md` | SELF (Batch-ID: B14) | Forget tombstone/read block, managed authorization, redacted diagnostics; full suite has unrelated API acceptance failure |
| B15 | DONE | S4-07～S4-08；S4 Gate | `../codex_batches/B15_s4_reliability_gate.md` | SELF (Batch-ID: B15) | Fault matrix automated; Infrastructure Trace/metrics; S4 Gate PASS |
| B16 | DONE | S5-01～S5-04 | `../codex_batches/B16_s5_benchmark_dashboard.md` | SELF (Batch-ID: B16) | Trace/Benchmark/Comparison/Dashboard accepted |
| B17 | DONE | S5-05～S5-08 | `../codex_batches/B17_s5_migration_cutover.md` | SELF (Batch-ID: B17) | Feedback/migration/Shadow dual-read/灰度回滚验收通过 |
| B18 | READY | S5-09～S5-10；S5/P0/P1/Release Gate | `../codex_batches/B18_release.md` | — | Next batch only; do not enter in this session |

## Invariant check

- IN_PROGRESS count: 0
- READY count: 1（B18）
- Overlapping formal task IDs: None
- Missing formal task IDs: None
- Current prompt: `../codex_batches/B17_s5_migration_cutover.md` completed; next prompt is `../codex_batches/B18_release.md` only in a new session.
- Hard stop after current batch: create the single B17 commit, read-only verify, then end the session; do not enter B18.
- Commit invariant: B01～B16 已独立提交；B17 is represented by this single `SELF (Batch-ID: B17)` commit; B18 remains unexecuted.
