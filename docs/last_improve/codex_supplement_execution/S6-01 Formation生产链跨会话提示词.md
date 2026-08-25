# S6-01：Formation 生产链跨会话提示词

你正在执行 MemoryHub vNext 补充完善阶段 **S6-01：Formation 生产链**。本会话唯一授权范围是将 Formation、Candidate、Evidence、Promotion、Procedure 与 Evolution 受控接入真实 Canonical Write Path。不得执行 S6-02、S6-03、S6-04 的灰度、持久化 Trace 或演示工作。

## 开始前必须阅读

1. `docs/last_improve/MemoryHub vNext：A_B_C_D 一体化改进方案.md`
2. `docs/last_improve/MemoryHub vNext：补充完善工作清单.md`
3. `docs/last_improve/codex_supplement_execution/CONTINUITY.md`
4. 本文件，以及当前任务直接相关的代码、测试、迁移和适用的 `AGENTS.md`。

先只读核对分支、HEAD、`git status --short`、与上次 S6-01 提交的 diff。`CONTINUITY.md` 是唯一状态源：若 S6-01 为 `IN_PROGRESS`，恢复该检查点；若为 `TODO`，在完成基线核对后将其改为 `IN_PROGRESS`。不得重做已有有效证据的工作。

## 必须完成

1. 让 Canonical Write Path 在受控条件下执行 Formation orchestration：依据 Boundary 决策更新 Working/Episode/checkpoint，并投递可重试的 Reflection 任务。
2. 实现或接通 worker：消费 extraction task，运行 Reflection，写入 Candidate 和独立 Evidence；达到策略阈值后经 Consolidation 写入 Long-Term Authority。
3. 把 Candidate 状态和 `candidate_ids` 提供给 API 响应或可查询任务状态；不得长期固定为空。
4. 将 Procedure 形成及 `REINFORCE / REVISE / SUPERSEDE / COEXIST / REVIEW` 演化动作接入受控 worker。
5. 首次上线默认使用 Feature Flag 的 Shadow 或 Candidate-only 模式；所有 Authority 写入继续保持 Canonical Write/Authority 事务、幂等、租户隔离、Policy fail-closed 与 Forget 边界。

## 验收

- 一次性格式偏好仅产生 Candidate，不产生 Global ACTIVE Memory。
- 多个独立证据满足阈值后自动固化，且有 Evidence/Lineage。
- 两次成功和一次失败的修复可形成带前置条件、步骤、验证、失败恢复的 Procedure。
- Candidate、REVIEW、DELETED、SUPERSEDED、跨租户记录不能进入普通 Context。
- worker 重试/重复投递不会重复写入 Candidate、Evidence、Lineage 或 Projection。

运行定向测试、受影响回归、安全/租户/Forget/写入旁路测试，以及相关 lint、compile、diff 检查。对新增 Trace、日志、报告扫描原文、query、payload、Evidence 正文泄露。

## 结束规则

通过全部验收后，更新 `CONTINUITY.md` 的证据、命令结果、改动文件、限制和下一阶段状态；创建一个且仅一个本地提交，推荐：`feat(vnext): complete S6-01 formation production path`，正文含 `Supplement-Phase: S6-01`。不得 push、amend、rebase 或进入 S6-02。

未完成则保留 `IN_PROGRESS`，记录失败命令、精确检查点和下一条可执行动作；不得声明完成。
