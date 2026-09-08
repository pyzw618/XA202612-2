# 事实语义增强修复方案

## 目标与完成标准

以 `dev-remem@7c75a50` 为基线，保留 `KnowledgeType.FACT`、统一证据、Authority 和现有索引体系，修复首轮整合中的存储、安全、隔离、冲突判断和裁决闭环问题。

完成时必须满足：同租户和用户内能够稳定执行“写入事实 → 实体/谓词归一化 → 完整冲突检测 → 持久化裁决 → 原子提交 → 检索/遗忘”；所有外部入口经过安全门禁；不同租户、用户和项目相互隔离；偏好及普通知识回归通过；部署只在全量测试通过后进行。

## 分轮实施

### 第 0 轮：冻结首轮整合和 Review 基线

- 保存当前 19 个文件的整合结果、评审结论和实际测试结果。
- 使用 `wip(fact): checkpoint initial semantic integration` 建立可回退检查点。
- 本轮不把现有实现认定为可部署版本。

### 第 1 轮：恢复基本可运行性和隔离正确性

- `FactSemanticRepository.list_bindings()` 返回脱离 ORM Session 的不可变绑定 DTO，修复第二次事实写入崩溃。
- 实体 ID 纳入 `tenant_id`；实体查询、保存和唯一性同时按租户与用户约束，防止跨租户主键碰撞。
- 谓词本体保持只读；用户自由谓词、别名和覆盖配置使用租户/用户作用域，单条事实不得修改全局 `single_value`。
- 修正互斥谓词比较，并补齐重复、单值、多值、逆关系、对称、互斥、类型、自反、成环与租户隔离测试。
- 验收：事实专项和现有 `test_knowledge_fact.py` 全部通过。

建议提交：`fix(fact): restore semantic repository and conflict invariants`

### 第 2 轮：建立无副作用的归一化准备阶段

- 将 `prepare()` 改为纯分析：返回拟创建实体、别名、自由谓词和绑定，不直接持久化。
- 精确标准名或已确认别名可自动复用；同名多实体、类型不确定和模糊匹配只返回候选，不自动建立别名。
- 用户选择实体或谓词后校验租户、用户和类型，再重新执行完整冲突检测。
- 待裁决、安全拒绝或校验失败均不得产生实体、别名、谓词、绑定或索引记录。
- 验收：对数据库快照断言 `prepare/reject/review` 前后无写入差异，重启后候选可恢复。

建议提交：`refactor(fact): make semantic preparation side effect free`

### 第 3 轮：原子裁决、并发控制和版本链

- 在 `DomainMemoryWriter` 增加事实批次事务，在同一 Session 内完成实体/谓词变更、旧事实归档、新事实写入、绑定、Evidence、Lineage、Authority、Outbox 和裁决终态。
- 裁决任务携带 `expected_version`；事务内重新检测事实和版本，不匹配时返回 `409 fact.decision_stale`。
- `replace` 明确归档全部被替换记录；`merge` 必须提交完整结构化结果；`coexist` 必须通过本体和作用域约束；硬约束不可绕过。
- 删除吞异常逻辑，返回稳定错误码；索引失败只进入 outbox 重试，不重复创建事实或证据。
- 验收：事务中途失败无部分状态，并发写入不会产生两条非法 ACTIVE 单值事实。

建议提交：`feat(fact): commit decisions atomically with version checks`

### 第 4 轮：封闭所有写入旁路和补齐接口

- `/facts/propose`、Agent、MCP、remember、管理编辑、自动抽取和 canonical/vNext FACT 均调用同一事实服务。
- 外部请求走记忆级安全门禁；只有已经通过事件安全门禁的内部抽取路径可以跳过重复检查。
- API 从当前身份解析租户和用户，不信任正文中的任意身份；所有查询和裁决同时校验租户、用户和任务归属。
- MCP Schema 暴露 `subject_id/predicate_id/object_id/expected_version`；Agent 兼容路由转发到同一裁决服务。
- canonical 重复、待裁决和成功结果返回真实 `memory_id` 与 receipt，不为不存在的候选创建投影任务；Formation 只在正式提交后确认候选。
- 验收：每个入口运行相同的重复与冲突用例，MASK/REVIEW/REJECT 响应不泄露原文。

建议提交：`feat(fact): route every fact entry through guarded decisions`

### 第 5 轮：迁移、检索、遗忘和桌面闭环

- `migrate_fact_semantics.py` 的默认 dry-run 不创建数据库、不建表、不加载并写入本体，只输出计划；`--apply` 才执行幂等补全。
- 补全报告区分已绑定、可绑定、字段缺失、实体歧义和历史冲突，不自动归档历史事实。
- 检索只返回 ACTIVE 正式事实；待裁决和归档事实由数据库状态过滤；遗忘事务同步更新事实绑定和 outbox。
- FactPage 加载持久化候选，支持实体/谓词选择、冲突动作和 stale 提示。
- 验收：重启恢复、迁移重复执行、检索、遗忘、客户端和 Qt 回归通过。

建议提交：`feat(fact): complete migration retrieval and desktop review flow`

### 第 6 轮：全量验证与虚拟机部署

- 先运行事实、知识、Authority、Formation、Agent/MCP、遗忘和全量测试，记录既有失败与新增失败。
- 运行冲突 golden dataset，单独报告正确率；不能用单元测试代替比赛指标。
- SSH 部署前验证远端分支、未提交修改、数据库路径和服务状态；备份数据库，保留远端 Qt 兼容改动和运行数据。
- 部署后执行健康检查、事实 propose/decide/search/forget 烟测和服务重启持久化检查；失败时回退到部署前提交和数据库备份。

建议提交：`test(fact): complete regression and deployment evidence`

## 固定测试门槛

每轮至少运行本轮定向测试。第 6 轮必须运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fact_semantics.py tests/test_knowledge/test_knowledge_fact.py tests/test_fact_knowledge_transition.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_vnext_authority_write.py tests/test_vnext_formation_worker.py tests/test_vnext_forget_diagnostics.py -q
.\.venv\Scripts\python.exe -m pytest agent-integration/tests -q
.\.venv\Scripts\python.exe -m pytest tests -q
```

API 测试在 Windows 使用 `MEMORYHUB_EMBEDDING_PROVIDER=mock`，麒麟部署验证使用实际配置；两者的结果分开记录。

## 明确不在本轮实现

- 有效时间区间与历史任期推理。
- 来源可信度排序。
- MemoryAgentBench 多跳推理。
- 偏好和普通知识业务逻辑重构。
- 自动修改真实部署数据库或直接推送远端分支。
