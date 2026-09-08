# 事实语义增强逐轮工作日志

> 本文件必须随每轮代码提交更新。新对话先阅读 `../../AGENTS.md` 工作区说明、本文件和修复方案，再继续下一轮。

## 总览

| 轮次 | 状态 | 起始提交 | 结束提交 | Review |
|---|---|---|---|---|
| 0：首轮整合检查点 | 已冻结 | `7c75a50` | 本文件所在 WIP 提交 | 不通过 |
| 1：基本可运行性与隔离 | 未开始 | 待定 | 待定 | 待定 |
| 2：无副作用归一化 | 未开始 | 待定 | 待定 | 待定 |
| 3：原子裁决与并发 | 未开始 | 待定 | 待定 | 待定 |
| 4：统一入口与接口 | 未开始 | 待定 | 待定 | 待定 |
| 5：迁移、检索、遗忘与桌面端 | 未开始 | 待定 | 待定 | 待定 |
| 6：全量验证与部署 | 未开始 | 待定 | 待定 | 待定 |

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
