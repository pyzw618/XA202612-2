# MemoryHub vNext：补充完善工作清单

> 依据：`MemoryHub vNext：A_B_C_D 一体化改进方案.md` 的实现复核结果。
> 目的：补齐已实现但尚未接入真实运行链路的能力，使方案从“模块与测试齐备”达到“端到端可运行、可切流、可审计”。

## 结论与范围

P0 的基础设施（统一写入/检索、Authority、Outbox、Forget、基础评测）已具备；P2 的自适应权重、记忆衰减、图检索等仍为可选增强，本清单不将其列为发布阻塞。

后续工作的发布阻塞项是：

1. P1 形成、证据固化与演化链必须进入生产 Canonical Write Path。
2. Shadow、双读、灰度切流和只读回滚必须真正控制生产读取路径。
3. Trace、指标和 Dashboard 必须具备可持久化、可跨重启审计的存储。
4. 固定演示必须覆盖方案声明的完整闭环，并与命令文档一致。

## P0 — 将 P1 形成/固化链接入生产写入路径

### 当前缺口

`CanonicalWriteService` 当前提交事件、Working/Episode 后只创建 extraction task；`BoundaryDetector`、`ReflectionService`、`ConsolidationService`、`EvolutionService` 主要作为独立组件或 Shadow 链路存在。常规 API 写入不会自动产出 Candidate、积累 Evidence、执行 Promotion 或形成 Procedure。

相关位置：

- `memoryhub/application/canonical_write.py`
- `memoryhub/adapter/vnext_api.py`
- `memoryhub/application/boundary_detector.py`
- `memoryhub/application/reflection_service.py`
- `memoryhub/application/consolidation_service.py`
- `memoryhub/application/evolution_service.py`

### 需要补充

1. 为 Canonical Write Path 增加受控的 Formation orchestration：事件写入后按 Boundary 决策创建/更新 Working、Episode 与 checkpoint，并投递可重试的 Reflection 任务。
2. 实现任务 worker：读取 extraction task，执行 Reflection，写入 Candidate 与独立 Evidence；达到阈值后通过 Consolidation 写入 Long-Term Authority。
3. 将 Candidate 的 `ACCUMULATING / CONFIRMED / REJECTED / REVIEW` 状态和 `candidate_ids` 回写到 API 响应或可查询的任务状态中；不得再长期返回空列表。
4. 将重复成功 Episode 的 Procedure 形成、以及 `REINFORCE / REVISE / SUPERSEDE / COEXIST / REVIEW` 演化动作接入 worker；所有 Authority 变更仍只能通过 Canonical Write/Authority 事务。
5. 保留 Feature Flag：初次上线应先采用 Shadow 或仅生成 Candidate 的模式，禁止未经验收直接自动固化。

### 验收标准

- 一次格式偏好仅生成 Candidate，不生成 Global ACTIVE Memory。
- 多个独立任务的证据满足阈值后，自动生成带 Evidence/Lineage 的 Authority Memory。
- 两次成功与一次失败的修复案例可形成包含前置条件、步骤、验证和失败恢复的 Procedure。
- Candidate、DELETED、SUPERSEDED、跨租户记录均不能进入普通 Context。
- worker 重试与重复投递不重复写入 Candidate、Evidence、Lineage 或 Projection。

## P0 — 接通 Shadow、双读、灰度与回滚

### 当前缺口

`VNextConfig`、`RolloutController` 与 `ShadowReadService` 已存在，但没有装配到应用/API/检索入口。配置变更不会实际选择 legacy、shadow、dual-read、canary 或 vNext 读取路径；切流审计也只保存在进程内。

相关位置：

- `memoryhub/config.py`
- `memoryhub/application/rollout_service.py`
- `memoryhub/application/shadow_read_service.py`
- `memoryhub/app.py`
- `memoryhub/adapter/api.py`
- `memoryhub/application/retrieval_service.py`

### 需要补充

1. 在应用装配层创建共享的 RolloutController 与 ShadowReadService，并注入 `/search`、`/context`、SDK、MCP、CLI 等所有读入口。
2. 明确并实现五种模式：`legacy`、`shadow`、`dual-read`、`canary`、`vnext`；只有一个模式可决定返回结果。
3. `shadow` 与 `dual-read` 必须始终返回 legacy 结果，仅记录红脱敏差异；canary 必须依照稳定哈希按租户/用户/请求选择流量，严禁随机或跨请求漂移。
4. 将观测窗口、差异指标、CUTOVER/ROLLBACK 审计持久化；切换进程重启后必须恢复当前层级和审核记录。
5. 切流门禁必须强制：Policy Leakage、跨租户结果、Forget 残留和观测错误均为 0；只允许 `0 → 5 → 25 → 50 → 100` 顺序推进。
6. 回滚开关必须只影响读路径，不能回滚或删除已经正确提交的 Authority 数据。

### 验收标准

- 配置切至 `shadow` 或 `dual-read` 时，线上返回值与 legacy 完全一致，且生成红脱敏比较报告。
- 5%、25%、50%、100% 每级均存在足量的持久化观测窗口和 CUTOVER 审计。
- 任一零容忍指标非零时，推进失败；回滚后所有请求稳定返回 legacy 结果。
- 进程重启后，当前模式、层级、观测和回滚窗口仍可查询。

## P1 — 持久化 Trace、指标与 Dashboard 数据源

### 当前缺口

TraceStore 在应用启动时创建为内存对象，Dashboard 仅读取其进程内数据；服务重启后 Trace、审计关联和看板数据丢失，不能满足可重放、跨期分析与生产审计需求。

相关位置：

- `memoryhub/app.py`
- `memoryhub/observability/trace_store.py`
- `memoryhub/application/dashboard_service.py`
- `memoryhub/observability/metrics.py`

### 需要补充

1. 定义 Trace/Metric/Audit 的持久化模型与迁移；至少索引 `trace_id`、`task_id`、`event_id`、`memory_id`、`query_id`、时间、租户和状态类别。
2. 接入保留期与采样策略：错误、高风险 Policy、Forget 与评测流量全量保留；普通成功路径可采样，但聚合计数必须全量。
3. 递归校验并拒绝原文、query、payload、Evidence 正文等敏感字段；Forget 只记录受影响 ID 的哈希或聚合数。
4. Dashboard 改为查询持久化且已脱敏的投影，保留管理权限和访问审计；支持 Memory、Episode、Retrieval Trace、Projection Version 之间跳转。

### 验收标准

- 重启服务后仍可按 trace/task/query 关联查询历史记录。
- 任何 Trace/Dashboard/API 报告中均不出现原始 query、正文或敏感 Evidence。
- 非管理员无法查看诊断数据；管理员查看行为有审计记录。
- 保留期清理不会删除 Authority 数据，也不会影响聚合指标正确性。

## P1 — 修正固定演示与最终验收材料

### 当前缺口

演示 README 声明 `retrieval`、`resume`、`forget` 场景及“每场景单独 JSON”，但脚本仅支持 `formation`、`docx`、`idempotency`，并只输出 `demo_report.json`。

相关位置：

- `examples/vnext_demo/README.md`
- `examples/vnext_demo/run_demo.py`
- `docs/spec/VNEXT_ACCEPTANCE.md`

### 需要补充

1. 在脚本实现并测试 `retrieval`、`resume`、`forget`；覆盖 Intent/通道/Scope/Budget 解释、任务重启恢复、Forget 后 residual retrieval 为 0。
2. 补充 Candidate 多证据 Promotion、Scope COEXIST/覆盖、冲突演化的固定场景；所有 fixture 必须脱敏且可重复执行。
3. 明确输出契约：若按场景输出，则生成 `<scenario>.json`；若统一报告，则同步更正 README，不能保留失效命令。
4. 修正 `--output-dir`：SQLite demo 数据库与全部报告均写入指定目录，不得在仓库受跟踪目录留下运行产物。
5. 在最终验收中真实登记旧读兼容窗口、负责人和最终下线日期；未登记前不得勾选完成。

### 验收标准

- README 中每条命令均可在干净环境运行，且有自动化测试。
- `all` 覆盖形成、证据固化、Scope、检索解释、任务恢复、Forget 六类场景。
- 演示输出可重复、默认脱敏，不修改受跟踪文件。
- 最终验收报告的勾选状态与可检索的兼容窗口/下线登记一致。

## 实施顺序与提交建议

1. 先完成 Formation worker 与 Candidate/Promotion 链路，并以 Shadow/仅 Candidate 模式验证。
2. 再接通 Shadow/dual-read/canary 与持久化切流审计，完成真实读路径灰度。
3. 随后持久化 Trace/Metric/Dashboard，补齐跨重启审计能力。
4. 最后修复演示、运行手册和最终验收登记，并执行端到端回归。

每个阶段应独立提交，且至少包含：实现、迁移、定向测试、受影响回归、风险测试、红脱敏证据和运行手册更新。P2 可在以上阻塞项完成后，以只读 Shadow 和小流量方式逐步引入。
