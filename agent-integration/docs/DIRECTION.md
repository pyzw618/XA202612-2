# Agent 接入改造方向

## 结论

CLI 做底层入口，Plugin 做 opencode 的日常使用面，MCP 保留给需要跨 Agent 标准协议的场景。三者共用一套 REST client，不再各写一份 HTTP 和业务逻辑。

## 这次做什么

- `memoryhub` CLI 覆盖检索、上下文、事件、记住、更新、反馈、遗忘、溯源、投影和状态；
- MCP 收敛到 8 个高频工具，低频管理操作走 CLI；
- opencode Plugin 增加 3 个薄壳工具、5 个命令、`memory-awareness` skill；
- 用 `tool.execute.after` 累积轨迹，`session.status` 冲刷，`session.deleted` 兜底；
- `search/context` 支持记忆分层、项目和会话参数，Fact 统一走知识面；
- 补契约文档和最小回归测试。

## 不做什么

- 不在接入层直接写数据库；
- 不继续扩展旧的三份 MCP 副本；
- 不把所有低频管理能力都注册成常驻工具；
- 不默认执行不可逆的遗忘操作。

## 交付判断

能用 CLI 独立完成全 REST 操作；opencode 默认不依赖常驻 MCP；需要 Claude Code 或其他 Agent 时可以直接启用同一份 MCP。详细契约见 `CONTRACT.md`，技术细节见 `TECHNICAL.md`。

