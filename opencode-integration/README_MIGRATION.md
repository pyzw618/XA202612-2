# Migration

新的 Agent 接入统一放在 `agent-integration/`。本目录只保留历史示例。

- Plugin 入口：`agent-integration/plugin/opencode/memoryhub.plugin.mjs`
- MCP 入口：`python -m memoryhub_mcp`
- CLI：`memoryhub`

旧的 `plugin/memoryhub.plugin.mjs` 已经转发到新 Plugin，不要继续在旧目录复制实现。

