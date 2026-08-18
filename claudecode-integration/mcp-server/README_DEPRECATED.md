# Deprecated

Claude Code 的 MCP 副本已统一到仓库根目录的 `agent-integration/memoryhub_mcp`。新配置使用：

```json
{"command": ["python", "-m", "memoryhub_mcp"], "cwd": "agent-integration"}
```

这里的代码只为旧配置兼容保留，不再新增工具或 REST 实现。

