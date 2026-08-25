# MemoryHub vNext 灰度与回滚契约

版本：`vnext/rollout/v1`

`RolloutController` 只切换读路径/Formation 开关，不写 Authority，不删除或回滚
已经正确提交的业务事实。可观测级别固定为 `legacy(0) → canary-5 → canary-25 →
canary-50 → vnext-100`，不得跳级。

每一级必须先记录至少 `observation_window_requests` 个请求，并满足硬门槛：

- Policy Leakage = 0；
- 跨租户结果 = 0；
- Forget residual retrieval = 0；
- 观测错误 = 0。

通过后才记录 `CUTOVER` 审计；每次审计包含 level、window、metrics、模式切换和
`rollback_window_minutes`。回滚演练记录 `ROLLBACK`，默认切回 legacy 读路径，
保留 Authority 数据。快照只含计数、分类和审计元数据，不含正文或查询。
