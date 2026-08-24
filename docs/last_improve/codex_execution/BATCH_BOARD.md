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
| B06 | DONE | S1-09～S1-11；S1 Gate | `../codex_batches/B06_s1_entrypoints_gate.md` | `b9432ab` | S1 Gate PASS；下一批次 B07 已置为 READY |
| B07 | DONE | S2-01～S2-03 | `../codex_batches/B07_s2_reflection_candidates.md` | `e8c55d3` | 边界、Reflection、Candidate 归一完成；B08 已置 READY |
| B08 | DONE | S2-04～S2-07 | `../codex_batches/B08_s2_consolidation_evolution.md` | `SELF (Batch-ID: B08)` | 固化与演化可解释、Fast Path 受约束、Procedure 来源受约束；B09 已置 READY |
| B09 | DONE | S2-08～S2-10；S2 Gate | `../codex_batches/B09_s2_shadow_eval_gate.md` | `1c08cde` | Shadow 不写 ACTIVE；Trace 默认脱敏；Formation 评测可复现；S2 Gate PASS；B10 已置 READY |
| B10 | DONE | S3-01～S3-03 | `../codex_batches/B10_s3_request_planning.md` | `SELF (Batch-ID: B10)` | 旧客户端兼容；7 类 Intent Router 可解释；Planner 多通道降级可见；B11 已置 READY |
| B11 | DONE | S3-04～S3-07 | `../codex_batches/B11_s3_fusion_context.md` | `SELF (Batch-ID: B11)` | Fusion/Reranker 可解释；Authority/Scope 冲突可解释；Budget 保护硬约束；Context Builder 结构化；B12 已置 READY |
| B12 | DONE | S3-08～S3-10；S3 Gate | `../codex_batches/B12_s3_entrypoints_eval_gate.md` | SELF (Batch-ID: B12) | S3 Gate PASS；所有入口一致 ID/版本/顺序/trace；评测可复现 |
| B13 | DONE | S4-01～S4-03 | `../codex_batches/B13_s4_projection_repair.md` | SELF (Batch-ID: B13) | Outbox lease/backoff/Dead Letter/delete priority; Projection Version; Repair Worker |
| B14 | READY | S4-04～S4-06 | `../codex_batches/B14_s4_forget_diagnostics.md` | — | |
| B15 | TODO | S4-07～S4-08；S4 Gate | `../codex_batches/B15_s4_reliability_gate.md` | — | |
| B16 | TODO | S5-01～S5-04 | `../codex_batches/B16_s5_benchmark_dashboard.md` | — | |
| B17 | TODO | S5-05～S5-08 | `../codex_batches/B17_s5_migration_cutover.md` | — | |
| B18 | TODO | S5-09～S5-10；S5/P0/P1/Release Gate | `../codex_batches/B18_release.md` | — | |

## Invariant check

- IN_PROGRESS count: 0
- READY count: 1（B14）
- Overlapping formal task IDs: None
- Missing formal task IDs: None
- Current prompt: `../codex_batches/B13_s4_projection_repair.md` completed；next prompt is `../codex_batches/B14_s4_forget_diagnostics.md` only in a new session
- Hard stop after current batch: create the single B13 commit, read-only verify, then end the session；不得进入 B14
- Commit invariant: B01/B02/B06/B07/B08/B09/B10/B11/B12 已独立提交；B13 待创建唯一 `Batch-ID: B13` 提交；B03～B18 各要求唯一 `Batch-ID` 提交
