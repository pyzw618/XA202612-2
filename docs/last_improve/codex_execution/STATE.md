# MemoryHub vNext Codex Execution State

> Last updated: 2026-08-22 16:01 +08:00
> Updated by: Codex session 2026-08-22

## Objective

完成 A/B/C/D 一体化执行任务方案中的 S0～S5 必做任务，通过 P0/P1 与发布 Gate。

## Current position

- Overall status: ACTIVE
- Execution model: one session, one batch
- Current batch: B03 (`S1-01`～`S1-03`)
- Batch status: IN_PROGRESS
- Batch commit policy: 完整验收后创建一次本地提交；未完成不提交；不 push
- Completed batch commits: B01=`a502f9a`, B02=`1b84af1`
- Current batch commit: pending B03-only commit after full acceptance
- Current batch prompt: `docs/last_improve/codex_batches/B03_s1_storage_ingress.md`
- Completed in current batch: S1-01, S1-02
- Batch hard stop: S1-03 验收后将 B03 完成状态和 B03-only 产物纳入唯一提交，然后停止会话；不得在同一会话启动 S1-04
- Current stage: S1
- Current task: S1-03
- Task status: IN_PROGRESS
- Last completed task: S1-02
- Next checkpoint: 对账现有 Event Gateway 实现，补足 S1-03 边界测试与验收证据；完成 B03 后硬停止

## Repository snapshot

- Working directory: `D:\project\XA202612-2`
- Branch: `dev-remem`
- HEAD before execution-governance commit: `1b84af1` (B02)
- Dirty paths: `docs/last_improve/` (untracked, pre-existing user/plan artifacts)
- User-owned unrelated changes: `docs/last_improve/`；本会话不覆盖、不删除

## Recovery reconciliation

- State vs repository: RECONCILED TO BATCH MODEL
- Facts checked: 无 `AGENTS.md`；`codex_execution/` 不存在；方案要求 57 个正式任务；现有仓库已有旧 `MemoryLevel(short/mid/long)` 与事件/安全/写入基础
- Differences and resolution: 旧提示词允许同一会话连续领取 READY 任务，导致推进到 S1-03；现改为 18 个批次并新增 BATCH_BOARD。已有有效 DONE 证据保留，当前恢复到 B03，不回退重做 S0

## Current task facts

- Goal: 升级 Event Gateway，按 Envelope→身份/Scope→Policy→MASK/DROP/REVIEW→幂等→Commit 顺序接入 canonical write
- Dependencies verified: S1-02 DONE；现有 safety pipeline、MemoryWriteService/DomainMemoryWriter、vNext Event/API contracts 可复用
- Files in scope: `memoryhub/application/`, `memoryhub/core/`, `tests/test_vnext_event_gateway.py`
- Acceptance remaining: 补强 Scope 拒绝发生在 Policy 前的直接测试；核验敏感正文不进日志/队列/幂等缓存；重复事件不重复 Evidence/Frequency；写入 S1-03 证据
- Tests to run: S1-03 定向 Event Gateway/Policy/idempotency tests、write-bypass regression 和受影响存储/契约回归

## Last verified checkpoint

- Change: S1-02 新增 tenant-scoped vNext repositories 与事务测试
- Evidence: Repository/storage/contract/interface → 25 passed；ruff passed；CAS/seq/status/dedup/activation 语义验证通过
- Result: S1-02 DONE；已领取 S1-03 IN_PROGRESS

## Blockers

- None

## Exact next actions

1. 在新会话使用 `docs/last_improve/codex_batches/B03_s1_storage_ingress.md`
2. 对账现有 `memoryhub/application/event_gateway.py`、设计文档和 7 项定向测试
3. 补足边界验证并写入 S1-03 Evidence；通过后将 B03 DONE、B04 READY，然后结束会话
