# MemoryHub vNext 补充完善连续性记录

> 唯一状态源：本文件记录 S6-01 至 S6-04 的实际执行状态。
> 主清单：`../MemoryHub vNext：补充完善工作清单.md`。
> 跨会话提示词：`MemoryHub vNext：补充完善跨会话执行提示词.md`。

## 执行不变量

- 一次会话只执行一个阶段。
- 以 Git、实际代码与测试结果为准，不以旧验收声明替代验证。
- 任何生产写入仍必须经过 Canonical Write/Authority；任何读取必须保留租户、Policy、Forget 和脱敏边界。
- 每个阶段仅在验收全部通过后才能标记为 `DONE` 并单独提交。

## 阶段看板

状态值：`TODO`、`IN_PROGRESS`、`BLOCKED`、`DONE`。

| 阶段 | 状态 | 依赖 | 当前证据 | 下一步 |
|---|---|---|---|---|
| S6-01 Formation 生产链 | DONE | 无 | 2026-08-25：Canonical Write Path 已接入 Boundary→Working/Episode/checkpoint→可重试 extraction task；worker 已接通 Reflection→Candidate/Evidence→Consolidation→Authority，默认 `candidate-only`；定向与受影响回归通过 | 等待 S6-02 DONE |
| S6-02 真实读路径灰度 | TODO | S6-01 | 审查确认 rollout/shadow/dual-read 未装配到读入口 | 等待 S6-01 DONE |
| S6-03 持久化可观测性 | TODO | S6-02 | 审查确认 Trace/Dashboard 为进程内数据 | 等待 S6-02 DONE |
| S6-04 演示与最终验收 | TODO | S6-03 | 审查确认演示命令与脚本不一致，兼容窗口未真实登记 | 等待 S6-03 DONE |

## 初始基线

- 建立日期：2026-08-25。
- 依据：对《A_B_C_D 一体化改进方案》与当前 B01–B18 实现的复核。
- 当前结论：补充工作尚未开始；所有 S6 阶段均为 `TODO`。
- 已知工作区注意事项：`evaluation/results/` 可能含本地测试数据库，及宿主机拒绝访问的 pytest 临时目录；开始阶段前必须区分这些产物与本阶段改动，禁止误提交。

## 会话日志

### 2026-08-25 — 初始化

- 阶段：无；建立补充完善的提示词和连续性记录。
- 状态变更：新增 S6-01 至 S6-04 看板，全部为 `TODO`。
- 代码改动：无。
- 下一步：新会话依照提示词核对仓库状态后，领取 S6-01。

### 2026-08-25 — S6-01 Formation 生产链

- 阶段：S6-01；基线 HEAD：`c763d9b`；基线核对确认无既有 S6-01 提交。
- 状态变更：`IN_PROGRESS` → `DONE`；S6-02、S6-03、S6-04 保持 `TODO`，本会话未执行其灰度、持久化 Trace 或演示工作。
- 主要改动：Canonical Write Path 负责受控 Working/Episode/checkpoint 编排与租户绑定的 extraction task；FormationWorker 支持 `shadow`、默认 `candidate-only`、显式 `authority`；Candidate/Evidence 幂等落库；阈值满足后经 Consolidation 与 Canonical Authority writer 固化；Procedure 与 REINFORCE/REVISE/SUPERSEDE/COEXIST/REVIEW 决策接入；任务状态 API 返回 `candidate_ids`、Candidate 状态和 `memory_ids`。
- 验收证据：
  - `python -m compileall -q memoryhub`：通过。
  - 受影响定向回归（Formation、Authority、Candidate、Consolidation、Context、Evolution、Feature Flag、P0、入口、任务状态、Scope、Reliability）：`91 passed`。
  - `tests/test_vnext_formation_worker.py`：4 个验收通过，覆盖一次性 Candidate-only、独立证据阈值固化、两次成功加一次失败形成 Procedure、重复投递幂等。
  - extraction retry 5 项、Forget diagnostics 3 项、Retrieval log 持久化 1 项：通过固定工作区目录手动调用；pytest 临时目录在宿主机被拒绝访问，故未将该环境错误计作代码失败。
  - `ruff check`（全部 S6-01 改动文件）：通过；`git diff --check`：通过。
  - 原文泄露扫描：Formation/Evidence 写入仅保存 `content_ref=event:<event_id>` 与空 excerpt，未发现新增日志、query、payload 或 Evidence 正文输出。
- 变更文件：`memoryhub/config.py`、`memoryhub/app.py`、`memoryhub/adapter/schemas.py`、`memoryhub/adapter/vnext_api.py`、`memoryhub/adapter/vnext_schemas.py`、`memoryhub/application/__init__.py`、`memoryhub/application/candidate_service.py`、`memoryhub/application/canonical_write.py`、`memoryhub/application/episode_service.py`、`memoryhub/application/event_gateway.py`、`memoryhub/application/formation_worker.py`、`memoryhub/application/reflection_service.py`、`memoryhub/core/ingestion/retry.py`、`memoryhub/storage/authority_repository.py`、`memoryhub/storage/database.py`、`memoryhub/storage/models.py`、`memoryhub/storage/vnext_repositories.py`、`tests/test_vnext_formation_worker.py`。
- 限制：pytest 的默认临时目录及部分已存在临时目录受宿主机权限限制；本阶段未进行 S6-02 读路径灰度，也未新增持久化 Trace/Dashboard 或演示。
- 下一步：保持 S6-02 为 `TODO`，由后续会话单独领取。
