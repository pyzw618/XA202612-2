# 更新记录

## 2026-09-08：B + C 合并为 D

- D 合并提交为 `c49e2d4`，基线为 `a7728ba`（`dev-remem-debug`），纳入 C 的事实语义提交 `74620b5`、`a59a6af` 及收尾快照 `cf86619`。
- 事实语义入口、实体/谓词归一化、关系冲突裁决、租户与项目作用域、事务写入和检索元数据已合入统一工作树。
- FactPage 同时保留 B 的异步筛选/UI 回归修复与 C 的持久化候选、消歧、冲突裁决交互。
- 合并过程中补齐 FactPage 候选区头文件成员和 UI 容器；修正事实提案 deterministic ID、租户读回和项目 scope-resolution pending 行为。
- 已完成：冲突消解、`git diff --check`、Python `compileall`、B/C 双祖先谱系校验。
- 待目标环境补验：定向事实/API/检索测试、Python 全量回归及麒麟/Qt 编译；当前 Windows 工作区缺少 FastAPI/SQLAlchemy，pytest 仅能报告依赖收集失败。

## 2026-09-09：D 合并后审查修复

- 向量索引元数据补齐 `tenant_id`，无租户元数据的历史结果仅归属 `default`，不再继承查询方租户。
- 事实语义与索引统一从 `KnowledgeMemory.project_id` 或兼容载荷读取项目作用域，标准知识写入入口同步镜像该字段。
- 明确事实提案契约：普通事实必须携带 evidence；缺少项目 ID 的项目事实进入可恢复的 scope-resolution pending。
- FactPage 正确展示 pending 数量并刷新候选；裁决始终提交 scope，项目作用域校验 project_id，驳回后同步刷新，候选删除兼容 `memory_id`。
- MCP 事实提案工具公开结构化三元组及 evidence 字段约束。
- `compileall` 与 `git diff --check` 通过；定向 pytest 仍因当前 Python 缺少 FastAPI、且 Pydantic/解释器类型注解兼容问题而在收集阶段中止。
