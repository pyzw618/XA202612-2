# 事实语义增强逐轮工作日志

> 本文件必须随每轮代码提交更新。新对话先阅读 `../../AGENTS.md` 工作区说明、本文件和修复方案，再继续下一轮。

## 总览

| 轮次 | 状态 | 起始提交 | 结束提交 | Review |
|---|---|---|---|---|
| 0：首轮整合检查点 | 已冻结 | `7c75a50` | 本文件所在 WIP 提交 | 不通过 |
| 1：基本可运行性与隔离 | 已完成 | 工作区修改 | 工作区修改 | 通过定向测试 |
| 2：无副作用归一化 | 已完成 | 工作区修改 | 工作区修改 | 通过定向测试 |
| 3：原子裁决与并发 | 已完成（压力测试待补） | 工作区修改 | 工作区修改 | 原子替换、重复补证据和版本校验已覆盖 |
| 4：统一入口与接口 | 已完成 | 工作区修改 | 工作区修改 | 通过定向测试 |
| 5：迁移、检索、遗忘与桌面端 | 已完成（桌面构建待环境） | 工作区修改 | 工作区修改 | 补全脚本、持久化裁决和 FactPage 已接入 |
| 6：全量验证与部署 | 部分完成（不部署） | 工作区修改 | 待提交 | 定向回归通过；全量剩余为基线/环境失败 |

## 第 0 轮：首轮整合检查点

### 目标

冻结 A 根据旧计划产生的第一轮事实语义整合，重新 Review，建立可跨对话恢复的 Git 和文档基线。

### 基线与范围

- 上游分支：`origin/dev-remem`
- 起始提交：`7c75a50 fix(ui): 补完 P0 修复回退项并加固回归测试`
- 修复分支：`feat/fact-semantics-repair`
- 首轮变化：9 个已跟踪文件修改、10 个新增文件，共 19 个文件。
- 主要新增：事实模型、归一化、冲突检测、语义服务、辅助表、REST/MCP 接口、迁移脚本及两个算法测试。

### Review 结论

不通过，禁止部署当前检查点。已确认的问题：

1. `FactSemanticRepository.list_bindings()` 返回已脱离 Session 的 ORM 对象，第二次事实写入触发 `DetachedInstanceError`。
2. `/facts/propose` 与 Agent `fact_commit` 使用 `skip_write_gate=True`，外部原始输入绕过安全门禁。
3. 实体 ID 不包含租户，`FactEntityRow` 又以实体 ID 为全局主键，存在跨租户覆盖风险。
4. 互斥谓词比较错误；“健在/已故”最小复现返回 `NEW`。
5. 裁决替换跨多个事务，可能留下旧事实已归档而新事实未提交的部分状态。
6. `prepare()` 在确认前持久化实体、别名和谓词，待裁决候选会污染语义库。
7. 单条事实可修改全局谓词 `single_value`，自由谓词也没有租户/用户隔离。
8. MCP Schema 缺少实体、谓词和客体 ID，无法完成同名消歧。
9. 统一事务、所有入口、桌面端和迁移报告尚未按原计划完成。

### 实际验证

- Python `compileall`：通过。
- `tests/test_fact_semantics.py` 两个纯算法测试：通过。
- 事实专项组合：`8 passed, 4 failed`；失败均由 `DetachedInstanceError` 触发。
- `tests/test_competition_api.py -k fact`：设置 mock embedding 后 `1 passed, 1 failed`；重复 propose 失败。
- `tests/test_api_acceptance.py -k fact`：`3 passed`。
- `tests/test_vnext_authority_write.py`：`7 passed`。
- `agent-integration/tests/test_mcp_server.py`：`1 failed`，工具集合断言未随新增 MCP 工具更新。
- `tests/test_no_production_write_bypass.py`：`6 passed`，但现有断言没有覆盖外部事实接口的安全旁路。
- 全量测试：未运行；已有阻断错误足以判定本轮不通过。

### 环境状态

- 仓库内 `.venv` 已建立并安装开发依赖，Git 忽略该目录。
- Windows API 测试需临时设置 `MEMORYHUB_EMBEDDING_PROVIDER=mock`。
- SSH：`ssh -p 2222 joe@127.0.0.1`；最近一次连接在 banner 阶段超时，部署前重新验证。

### 下一轮入口

执行修复方案第 1 轮。首先把绑定查询改为 Session 外可安全使用的 DTO，并增加一个“连续写入两个事实”的数据库集成测试；随后修复租户实体 ID、谓词隔离和互斥关系。第 1 轮不得开始原子裁决或桌面端工作。

## 第 1-3 轮：存储隔离、无副作用准备与原子写入

### 完成修改

- `FactBinding` 改为 Session-independent DTO，修复连续事实写入的 `DetachedInstanceError`。
- 实体 ID 纳入 `tenant_id + user_id`；自定义谓词、别名按租户/用户隔离，内置本体只读并带版本字段。
- `prepare()` 改为延迟物化：候选实体、别名和自由谓词先放入 pending operations，只有接受写入才提交；歧义和硬约束不会注册语义元数据。
- 关系检测改为收集完整冲突集合，修复互斥谓词双向判断，并保留单值、多值、逆关系、对称、类型、自反和成环检查。
- `DomainMemoryWriter.write_batch()` 与 `MemoryWriteService.upsert_fact_decision()` 将事实语义绑定和替换前驱纳入同一事务；裁决携带并校验 `expected_version`。
- `/facts/propose`、显式 `/memories/knowledge`、Agent、MCP 和 canonical/vNext FACT 入口统一经过事实服务；新增实体/谓词选择字段、持久化 proposals 和决定接口。
- 迁移脚本 dry-run 改为 SQLite 只读扫描，不创建数据库；增加 REST 裁决、租户隔离和算法回归测试。

### 测试结果

- `tests/test_fact_semantics.py tests/test_knowledge/test_knowledge_fact.py tests/test_fact_decision_api.py tests/test_domain_memory_writer.py`：23 passed。
- `tests/test_competition_api.py -k fact`：2 passed；`tests/test_api_acceptance.py -k fact`：3 passed。
- `tests/test_vnext_authority_write.py tests/test_vnext_formation_worker.py`：12 passed。
- `agent-integration/tests/test_mcp_server.py`：1 passed。
- Python compileall、ontology JSON 校验和迁移 dry-run：通过。

### 已知问题

- 全量测试和桌面端构建尚未在本轮完成；需要继续按固定门槛运行。
- 事实替换的数据库部分已原子化，但提交后的向量投影仍由现有 outbox 异步处理；部署数据库未执行迁移或补全。

## 第 4-6 轮：入口闭环、历史补全与收尾验证

### 完成修改

- `/facts/propose`、Agent、canonical、vNext FACT 晋升和 `/facts/decide` 均经过同一事实语义服务；外部入口在实体/谓词解析前先执行安全门禁。
- 事实裁决支持版本和旧记录校验、原子替换；实体消歧后发现重复时原子消费候选并补充证据，响应增加 `outcome=new|duplicate|coexist|replaced|merged`。
- 客户端、CLI、MCP 自动发送租户身份；MCP 暴露 `memoryhub_decide_facts`；FactPage 加载持久化候选并提交实体选择、创建新实体和冲突动作。
- 增加 `scripts/migrate_fact_semantics.py` 幂等补全工具，默认 `--dry-run`，仅 `--apply` 执行写入；重复运行不会重复创建绑定或任务。
- 修复 Knowledge 投影 outbox 在证据版本变化时的自然键复用，避免重复提交触发唯一键错误。
- 修复同一事件产出多个记忆时的 outbox 唯一索引，唯一键包含 `memory_id`，保留事件/记忆级幂等。

### 测试结果

- 事实、裁决、Knowledge 和事务写入：`36 passed`；FACT 抽取迁移回归：`2 passed`。
- vNext Authority/Formation/Forget：`15 passed`；Agent/MCP：`8 passed`；入口安全旁路、competition/API acceptance 等定向组合：`67 passed, 1 skipped`。
- `compileall`、变更文件 Ruff F 检查、`git diff --check` 和本体 JSON 校验通过。
- 全量 `pytest tests -q`（mock embedding）：`1287 passed, 6 skipped, 23 failed, 28 errors`。失败主要是仓库基线或本机环境：Kylin/Milvus mock 动态库缺失、生产 embedding 配置门禁、既有 vNext demo 断言和无关迁移用例；已用基线工作树复核 vNext demo 失败并非本轮引入。
- Windows 环境没有 Qt/MSVC，桌面端未能实际编译；代码已完成静态检查，部署数据库和索引均未操作。

### Review 结论

事实语义增强代码已完成并保留在 `feat/fact-semantics-repair` 工作区，满足本轮“直接改代码”的范围；并发压力、Qt 构建和真实 Kylin/Milvus 环境验证仍需在对应环境补测。

## 后续轮次记录模板

复制以下模板追加，不删除以前的记录：

```markdown
## 第 N 轮：名称

### 目标

### 起始状态
- 起始提交：
- 允许修改的模块：

### 完成修改

### 测试结果

### Review 结论

### 已知问题

### 结束状态
- 结束提交：
- 下一轮入口：
```
