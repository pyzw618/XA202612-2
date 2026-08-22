# MemoryHub vNext Codex Execution State

> Last updated: 2026-08-22 16:55 +08:00
> Updated by: Codex session 2026-08-22

## Objective

完成 A/B/C/D 一体化执行任务方案中的 S0～S5 必做任务，通过 P0/P1 与发布 Gate。

## B04 authoritative position

- Last updated: 2026-08-22 18:20 +08:00; updated by Codex session 2026-08-22 (B04)
- Current batch: B04 (`S1-04`～`S1-06`); batch status: IN_PROGRESS
- Current batch prompt: `docs/last_improve/codex_batches/B04_s1_task_state.md`
- Current task: none; S1-04, S1-05, and S1-06 DONE; B04 ready to commit
- Dependencies: S1-02 and S1-03 DONE with valid evidence
- Start reconciliation: branch `dev-remem`; HEAD `476cb5a79af7afd15541a0d54aaf01c7d0e308f4`; no tracked worktree diff; no applicable `AGENTS.md`
- Next checkpoint: after the single B04 commit, read-only verify HEAD SHA and stop; next session uses B05 prompt
- Hard stop: do not execute or modify S1-07 or any later batch; after B04 acceptance only mark B05 READY and stop after the single B04 commit

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

## Legacy B03 exact next actions

1. 只暂存 B03 产物和六份连续性文件，创建唯一普通本地提交，正文包含 Batch-ID: B03。
2. 提交后只读核对 HEAD SHA、提交文件和工作区状态；不 push、amend、rebase 或进入 B04。
3. 新会话使用 docs/last_improve/codex_batches/B04_s1_task_state.md。
