# B03：S1 存储与入口

## 可直接发送给 Codex 的提示词

你正在执行 MemoryHub vNext 的 **B03** 批次。本会话唯一授权范围是 **S1-01～S1-03**。

开始前完整读取：

1. `docs/last_improve/MemoryHub vNext：Codex 跨会话执行提示词.md`；
2. 本批次提示词；
3. `docs/last_improve/MemoryHub vNext：A_B_C_D 一体化执行任务方案.md` 中本批次任务与 Gate；
4. `docs/last_improve/codex_execution/` 下全部连续性文件；
5. 当前作用域内所有适用的 `AGENTS.md`，以及当前任务直接相关的代码和测试。

先核对 Git branch、HEAD、status、diff、产物和测试证据，再恢复本批次内唯一的 `IN_PROGRESS` 任务；若没有，则领取本批次内依赖已满足的最小编号任务。已有有效证据的 DONE 任务不重做。

本批次任务：S1-01 Authority 相关 Schema；S1-02 Repository 与事务语义；S1-03 Event Gateway 的 Envelope→身份/Scope→Policy→动作→幂等→Commit。

按总控手册执行实现、定向测试、受影响回归、风险测试和证据固化。每个检查点立即更新 `STATE.md`、`TASK_BOARD.md`、`EVIDENCE.md`；会话结束前更新 `BATCH_BOARD.md` 并追加 `SESSION_LOG.md`。

Git 提交硬规则：本批次完整验收前不得提交；验收通过后先把完成状态、下一批次 READY 状态及 `SELF (Batch-ID: B03)` 写入连续性文件，然后创建且只创建一次本地提交，标题建议为 `feat(vnext): complete B03 s1 storage ingress`，正文 trailer 必须包含 `Batch-ID: B03`。提交只能包含 B03 产物和必须的连续性文件，不得纳入其他批次或用户无关修改。提交后只读核对 HEAD SHA 并在最终答复中报告；不 push、不 amend、不进入下一批次。

批次退出标准：三项任务均 DONE；敏感正文不先落盘；租户隔离、事务、并发和幂等证据有效。

硬停止：本会话不得执行、领取、试做、预研或修改下一批次内容。当前批次完成后，只把下一批次标记为 READY，在最终答复中告知下一提示词 `B04_s1_task_state.md`，然后立即停止。如果本批次未完成，则准确记录检查点，下一个新会话继续使用本提示词。
