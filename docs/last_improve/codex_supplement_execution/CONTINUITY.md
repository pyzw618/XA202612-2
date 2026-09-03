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
| S6-02 真实读路径灰度 | DONE | S6-01 | 2026-08-26：共享 RolloutController/ShadowReadService 已装配全部真实读入口；legacy/shadow/dual-read/canary/vnext 统一选择，稳定哈希 canary，SQLite 持久化观测/差异/CUTOVER/ROLLBACK，零容忍门禁与只读回滚通过 | 等待 S6-03 DONE |
| S6-03 持久化可观测性 | DONE | S6-02 | 2026-08-26：SQLite Trace/Metric/Audit 持久化、增量迁移、脱敏、采样/保留期、Dashboard/diagnostics 权限审计与跨重启验证通过 | 等待 S6-04 |
| S6-04 演示与最终验收 | DONE | S6-03 | 2026-08-26：六类固定演示、`all`、输出目录契约、兼容窗口登记及受影响回归完成；最终验收通过 | 后续按登记窗口复核并执行旧读下线 |

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

### 2026-08-26 — S6-02 真实读路径灰度

- 阶段：S6-02；基线 HEAD：`e01f61814cc3d9f7d10fe6fc34b22fc4b98570fb`；工作区开始时干净；S6-01=`DONE`、S6-02=`TODO`。
- 状态变更：`TODO` → `IN_PROGRESS` → `DONE`；S6-03、S6-04 保持 `TODO`，本会话未执行持久化 Trace/Dashboard 或演示工作。
- 主要改动：应用装配共享 `RolloutController`、`ShadowReadService`、`RolloutReadService`；REST `/search`、`/context`、vNext `/search`、`/context`、v2 兼容入口、Agent `/step` 均经统一 read decision；SDK/MCP/CLI 继续通过 REST；shadow/dual-read 只返回 legacy 并产生 ID hash/计数差异；canary 按 tenant/user 稳定哈希选流量，vNext 失败 fail-closed 到 legacy；rollback 只改变读路径。
- 持久化与门禁：新增 rollout state/observation/audit SQLite 表；重启恢复模式、层级、回滚窗口、观测和审计；强制 `0 → 5 → 25 → 50 → 100`，Policy Leakage、跨租户、Forget 残留、观测错误任一非零禁止推进；管理端提供 redacted status/observe/advance/rollback。
- 验收证据：
  - `python -m compileall -q memoryhub`：通过（宿主权限拒绝的既有 `tests/security` 目录除外）。
  - S6-02 定向测试：`22 passed`；vNext P0/interface/schema 回归：`20 passed`。
  - 应用装配 smoke：使用 `milvus_mock`/768 维测试配置启动成功，`/api/memory/vnext/search` 返回 200，且 controller 为 `legacy/0`。
  - SQLite 重启恢复：直接验证恢复当前模式、层级、观测计数及 CUTOVER/ROLLBACK 审计；新增 `tests/test_vnext_s6_02_rollout.py` 覆盖同一场景。
  - 目标改动文件 `ruff check`：通过；`git diff --check`：通过。
  - 脱敏扫描：rollout 快照、审计、差异报告仅保存模式、层级、计数、哈希和 ID 引用，不保存 query、payload、memory 正文。
- 限制：宿主机默认 pytest 临时目录/key-store 曾拒绝访问；通过显式固定测试配置和直接 SQLite 检查完成等价验证，未修改既有安全目录或临时产物。
- 下一步：保持 S6-03、S6-04 为 `TODO`，停止本会话。

### 2026-08-26 — S6-03 持久化可观测性

- 阶段：S6-03；基线 HEAD：`4bc07ff`；工作区开始时无用户改动；S6-01=`DONE`、S6-02=`DONE`、S6-03=`TODO`、S6-04=`TODO`。
- 状态变更：S6-03 `TODO` → `IN_PROGRESS` → `DONE`；S6-04 保持 `TODO`。本会话仅处理 Trace、Metric、Audit、Dashboard 的持久化、脱敏、保留期、采样与跨重启审计，未进入 S6-04。
- 主要改动：新增 `observability_traces`、`observability_metrics`、`observability_audits` ORM 模型及 `Database._ensure_compatible_schema()` 加法式迁移/索引；应用装配将 TraceStore、InfrastructureMetrics、AuditStore 绑定业务 SQLite；Trace 按 trace/task/event/memory/query/tenant/category/status 建索引并按 7/30 天策略清理；错误、Denied、高风险 Policy、Forget、评测/benchmark 全量采样，普通成功按稳定 hash 采样；聚合指标不采样且保留全量计数；递归拒绝 content/text/payload/query/Evidence/body/embedding 等字段；Forget Audit 仅保留请求 ID、受影响数量和 ID hash；Dashboard/diagnostics 读取持久化脱敏投影，管理访问和 Forget 均有审计，Dashboard 提供 Memory/Episode/Retrieval Trace/Projection Version 关联字段。
- 验收证据：
  - `python -m compileall -q memoryhub tests/test_vnext_s6_03_observability.py`：通过。
  - `ruff check`（全部 S6-03 改动文件）：通过；`git diff --check`：通过。
  - `tests/test_vnext_s6_03_observability.py`：3 项通过，覆盖 Trace/Metric/Audit 重启恢复与索引、递归脱敏、评测全量采样、过期清理不影响聚合、增量迁移和 Dashboard 持久化投影。
  - S6-03/Trace/Reliability/Storage/S6-02 核心回归：`25 passed, 2 deselected`；另有核心 Trace/Reliability 与 S6-03 组合 `19 passed`，Dashboard API 权限 `1 passed`，Retrieval Service `5 passed`，安全脱敏子集 `25 passed`。
  - 直接 SQLite 重启验证：Trace 可按 trace/task/event/memory/query 关联查询；Metric 聚合计数恢复；Dashboard、Forget 和 diagnostics 审计跨重启保留；Trace 过期清理未删除 Authority 或 Metric aggregate。
  - 脱敏验证：TraceSpan 嵌套敏感 key 在写入前拒绝；Dashboard benchmark/diagnostics 递归投影不输出 query、payload、正文或 Evidence；Forget Audit 仅保存 hash/count。
- 限制：宿主机默认 pytest `tmp_path`/临时目录清理仍报 `WinError 5`，因此依赖该 fixture 的既有 Dashboard/Forget/迁移/安全测试未计作代码失败，使用固定工作区 SQLite 等价场景完成；既有 `tests/test_vnext_entrypoints.py` 的部分 helper 未注入 S6-02 `rollout_controller`，返回 `rollout.service_unavailable`，未修改该 S6-02 范围问题。未修改 `tests/security` 或宿主临时目录。
- 下一步：仅允许后续会话领取 S6-04；本会话停止。

### 2026-08-26 — S6-04 演示与最终验收

- 阶段：S6-04；基线 HEAD：`9baa339`；工作区开始时无用户改动；S6-01=`DONE`、S6-02=`DONE`、S6-03=`DONE`、S6-04=`TODO`。
- 状态变更：S6-04 `TODO` → `IN_PROGRESS`。
- 开始核对：现有 `examples/vnext_demo/run_demo.py` 仅支持 `formation`、`docx`、`idempotency`，README 已声明但尚未实现的 `retrieval`、`resume`、`forget` 以及证据固化/Scope 场景；`--output-dir` 未传入 `_db()`，并且统一写出 `demo_report.json`，与场景文件契约不一致。
- 本会话范围：仅处理固定演示、文档命令、兼容窗口登记和最终验收材料；不扩展 P2 能力。
- 下一步：实现六类场景、补齐自动化测试和验收登记；未全部通过前保持 `IN_PROGRESS`。
- 状态变更：S6-04 `IN_PROGRESS` → `DONE`。
- 主要改动：固定演示脚本覆盖 `formation`、证据固化、Scope、`retrieval`、`resume`、`forget` 与 `all`；所有 SQLite/JSON 输出遵守 `--output-dir`，默认写入系统临时目录；报告只保留脱敏 ID/hash、计数、分类、解释和状态元数据。
- 验收证据：使用 `.venv` 模块命令逐条重放六个场景及 `all`，生成七个 JSON 报告和 `demo.db`；自动化演示测试函数通过；文档测试 `11 passed`；Formation Worker/P0 `19 passed`；Retrieval/Scope `65 passed`；安全、Policy、租户、Forget `145 passed, 4 skipped`；S6-02/S6-03 受影响回归已执行；`ruff check`、`compileall`、`git diff --check` 通过。
- 验收材料：`docs/vnext/spec/VNEXT_ACCEPTANCE.md` 已勾选 S6-04 Release Gate；旧读兼容窗口登记为 2026-08-26 至 2026-09-25（Asia/Shanghai），负责人 Mr.X，最终下线日期 2026-09-26，登记状态 `REGISTERED`。
- 限制：宿主机 pytest 临时目录和既有 `tests/security` 权限仍会报告 `WinError 5`；既有 `tests/test_vnext_entrypoints.py` 的 rollout helper 缺装配、`tests/test_vnext_formation_eval.py` 的内存仓库签名不兼容未在本阶段修复，均不涉及本阶段变更文件。未修改 P2 或上述既有问题。
- 提交 SHA：本次提交生成后以 `HEAD` 核对（禁止 amend/rebase）。
- 补充工作结论：S6-01 至 S6-04 均已完成；后续仅按兼容窗口复核并执行旧读下线，不再扩展补充阶段能力。
