# B06：S1 入口收敛与 Gate

## 可直接发送给 Codex 的提示词

你正在执行 MemoryHub vNext 的 **B06** 批次。本会话唯一授权范围是 **S1-09～S1-11 及 S1 Gate**。

开始前完整读取：

1. `docs/last_improve/MemoryHub vNext：Codex 跨会话执行提示词.md`；
2. 本批次提示词；
3. `docs/last_improve/MemoryHub vNext：A_B_C_D 一体化执行任务方案.md` 中本批次任务与 Gate；
4. `docs/last_improve/codex_execution/` 下全部连续性文件；
5. 当前作用域内所有适用的 `AGENTS.md`，以及当前任务直接相关的代码和测试。

先核对 Git branch、HEAD、status、diff、产物和测试证据，再恢复本批次内唯一的 `IN_PROGRESS` 任务；若没有，则领取本批次内依赖已满足的最小编号任务。已有有效证据的 DONE 任务不重做。

本批次任务：S1-09 REST/Agent replay/MCP/CLI/SDK 写入口收敛；S1-10 任务恢复接口和 P0 流程；S1-11 Authority→Projection 重建；核验 S1 Gate。

按总控手册执行实现、定向测试、受影响回归、风险测试和证据固化。每个检查点立即更新 `STATE.md`、`TASK_BOARD.md`、`EVIDENCE.md`；会话结束前更新 `BATCH_BOARD.md` 并追加 `SESSION_LOG.md`。

Git 提交硬规则：本批次完整验收前不得提交；验收通过后先把完成状态、下一批次 READY 状态及 `SELF (Batch-ID: B06)` 写入连续性文件，然后创建且只创建一次本地提交，标题建议为 `feat(vnext): complete B06 s1 entrypoints gate`，正文 trailer 必须包含 `Batch-ID: B06`。提交只能包含本批次产物和必须的连续性文件，不得夹带其他批次或用户无关修改。提交后只读核对 HEAD SHA 并在最终答复中报告；不 push、不 amend、不进入下一批次。

批次退出标准：生产写入无旁路；恢复和重建通过；S1 Gate 有证据并标记 PASS。

硬停止：本会话不得执行、领取、试做、预研或修改下一批次内容。当前批次完成后，只把下一批次标记为 READY，在最终答复中告知下一提示词 `B07_s2_reflection_candidates.md`，然后立即停止。如果本批次未完成，则准确记录检查点，下一个新会话继续使用本提示词。
