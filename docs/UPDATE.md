# 更新记录

## 2026-08-28

### 事实语义裁决委托主 Agent

- 实体和谓词归一化继续使用精确匹配、别名、关键词和向量分数完成确定性判断；出现多个可能项时返回结构化 `decision_task`，不再由 MemoryHub 内部调用 LLM 猜测。
- 事实冲突仅由代码检测。未提供明确裁决时，候选保持 `awaiting_decision`，不写入 `disputed` 事实；主 Agent 可结合完整对话上下文直接选择，或询问用户。
- `/facts/decide` 与 `memoryhub_decide_facts` 新增主体实体、客体实体和谓词选择字段，并保留 `replace / keep_old / merge / coexist` 冲突操作。
- 所有主 Agent 返回的实体选择继续校验用户归属和实体类型，避免跨用户关联。
- 自动 `MemoryEvent` 的事实抽取路径保持不变；本次只移除归一化和冲突裁决阶段的内部 LLM 调用。

### 验证

- Python 3.13 `compileall` 通过。
- 事实模块回归：58 passed，1 skipped；API 与 MCP 定向回归：27 passed。

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
