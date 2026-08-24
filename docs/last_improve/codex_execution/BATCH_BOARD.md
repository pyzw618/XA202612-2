# MemoryHub vNext Batch Board

状态：TODO | READY | IN_PROGRESS | BLOCKED | DONE

> 一个会话只允许执行一个批次。批次完成后仅将下一批次置为 READY，并结束当前会话。

| Batch | Status | Formal tasks / Gate | Prompt | Commit reference | Note |
|---|---|---|---|---|---|
| B01 | DONE | S0-01～S0-04 | `../codex_batches/B01_s0_contracts.md` | `a502f9a` | 65 tests passed；独立提交完成 |
| B02 | DONE | S0-05～S0-08；S0 Gate | `../codex_batches/B02_s0_delivery_gate.md` | `1b84af1` | 46 passed、6 deselected；S0 Gate PASS |
| B03 | DONE | S1-01～S1-03 | `../codex_batches/B03_s1_storage_ingress.md` | `SELF (Batch-ID: B03)` | 11 定向、45 受影响回归通过；敏感正文、租户隔离、事务、并发、幂等证据有效；安全文件系统组合 PARTIAL 已记录 |
| B04 | DONE | S1-04～S1-06 | `../codex_batches/B04_s1_task_state.md` | `SELF (Batch-ID: B04)` | B04 完成；下一批次 B05 已置为 READY |
| B05 | DONE | S1-07～S1-08 | `../codex_batches/B05_s1_authority_write.md` | `SELF (Batch-ID: B05)` | S1-07/S1-08 验收通过；下一批次 B06 已置为 READY |
| B06 | DONE | S1-09～S1-11；S1 Gate | `../codex_batches/B06_s1_entrypoints_gate.md` | `SELF (Batch-ID: B06)` | S1 Gate PASS；下一批次 B07 已置为 READY |
| B07 | READY | S2-01～S2-03 | `../codex_batches/B07_s2_reflection_candidates.md` | — | 等待新会话领取 |
| B08 | TODO | S2-04～S2-07 | `../codex_batches/B08_s2_consolidation_evolution.md` | — | |
| B09 | TODO | S2-08～S2-10；S2 Gate | `../codex_batches/B09_s2_shadow_eval_gate.md` | — | |
| B10 | TODO | S3-01～S3-03 | `../codex_batches/B10_s3_request_planning.md` | — | |
| B11 | TODO | S3-04～S3-07 | `../codex_batches/B11_s3_fusion_context.md` | — | |
| B12 | TODO | S3-08～S3-10；S3 Gate | `../codex_batches/B12_s3_entrypoints_eval_gate.md` | — | |
| B13 | TODO | S4-01～S4-03 | `../codex_batches/B13_s4_projection_repair.md` | — | |
| B14 | TODO | S4-04～S4-06 | `../codex_batches/B14_s4_forget_diagnostics.md` | — | |
| B15 | TODO | S4-07～S4-08；S4 Gate | `../codex_batches/B15_s4_reliability_gate.md` | — | |
| B16 | TODO | S5-01～S5-04 | `../codex_batches/B16_s5_benchmark_dashboard.md` | — | |
| B17 | TODO | S5-05～S5-08 | `../codex_batches/B17_s5_migration_cutover.md` | — | |
| B18 | TODO | S5-09～S5-10；S5/P0/P1/Release Gate | `../codex_batches/B18_release.md` | — | |

## Invariant check

- IN_PROGRESS count: 0
- READY count: 1（B06）
- Overlapping formal task IDs: None
- Missing formal task IDs: None
- Current prompt: `../codex_batches/B05_s1_authority_write.md` completed；next prompt is B06 only in a new session
- Hard stop after current batch: create the single B05 commit, read-only verify, then end the session
- Commit invariant: B01/B02 已独立提交；B03～B18 各要求唯一 `Batch-ID` 提交
