# 更新记录

## 2026-08-18

### 事实记忆与冲突裁决

- 新增 `fact.conflict_decision_mode` 配置，支持 `user_review` 和 `agent_autonomous`。
- 事实候选和 MemoryEvent 路径均保存冲突裁决模式；用户审核模式下冲突进入待裁决状态，Agent 自主模式下调用现有冲突裁决器自动处理，无法判断时仍升级人工确认。
- `memoryhub_propose_facts`、`memoryhub_decide_facts` 以及旧 Agent decision 接口支持冲突裁决模式覆盖。
- 管理接口和 MCP Schema 暴露冲突裁决模式，便于界面和主 Agent 选择策略。

### 存储一致性

- 应用启动时校验事实 `FactStore` 与偏好/知识 `Database` 使用同一个 SQLite `db_path`。
- 管理状态接口增加 `fact_storage_shared` 和 `fact_db_path`，用于确认三类记忆是否共用数据库文件。
- 候选表新增 `conflict_decision_mode` 字段，并兼容旧数据库自动迁移。

### 验证

- 事实专项测试：55 passed，1 skipped。
- MCP 专项测试中的部分写入用例仍受本地 FAISS 临时目录环境影响；相关问题与本轮事实冲突模式改动无关。
