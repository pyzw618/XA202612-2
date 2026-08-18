# Agent 接入契约

这份文档是 CLI、MCP 和 opencode Plugin 的共同边界。三者不直接操作数据库，也不各自实现一套 HTTP 逻辑。

## 1. 分层

```
Agent -> CLI (母语) -> MemoryHub REST -> core
      -> Plugin tools/commands/hooks (薄壳)
      -> MCP (跨 Agent 标准薄壳)
```

CLI 默认输出 compact 文本；脚本和 MCP 使用 `--json` 或客户端返回的结构化对象。所有写入都经过 REST 的安全门、审计和抽取流程。

## 2. REST 映射

| 能力 | REST | CLI | MCP |
|---|---|---|---|
| 健康检查 | `GET /api/memory/health` | `status` / `service status` | `memoryhub_health` |
| 检索 | `POST /api/memory/search` | `search` | `memoryhub_search` |
| 上下文 | `POST /api/memory/context` | `context` | `memoryhub_get_context` |
| 事件写入 | `POST /api/memory/events` | `event` | `memoryhub_write_event` |
| 显式记住 | `POST /api/memory/memories/preference` 或 `knowledge` | `remember` | `memoryhub_remember` |
| 更新 | `PUT /api/memory/{type}/{id}` | `update` | CLI（低频） |
| 反馈 | `POST /api/memory/feedback` | `feedback` | `memoryhub_feedback` |
| 遗忘 | `POST /api/memory/forget`、`forget/preview` | `forget` | `memoryhub_forget` |
| 溯源 | `GET /api/memory/v2/memories/{id}/{lineage,evidence,audit}` | `provenance` | CLI（低频） |
| 投影 | `GET/POST /api/memory/v2/projections*` | `projection` | CLI（低频） |
| Fact 候选 | `POST /api/memory/facts/propose` | `knowledge fact propose` | `memoryhub_knowledge_fact_propose` |
| Fact 裁决 | `POST /api/agent/actions/{id}/decision` | `knowledge fact propose --commit` | CLI（低频） |

`search` 和 `context` 始终透传 `level`（`short/mid/long`）、`project_id`、`session_id`；事件 payload 使用 `project_root/project_name` 保存项目隔离信息。事实不再暴露独立记忆类型，写入知识面时使用 `knowledge_type=fact`。

## 3. Plugin 面

`agent-integration/plugin/opencode/` 提供：

- `memoryhub_search`、`memoryhub_context`、`memoryhub_remember`：只调用 CLI；
- `/memoryhub-context`、`remember`、`forget`、`status`、`review`：命令使用 `!` 按需注入 CLI 输出；
- `memory-awareness`：只描述何时检索、记住、反馈和遗忘；
- `tool.execute.after` 累积工具轨迹，`session.status=idle` 按回合冲刷，`session.deleted` 兜底，`experimental.session.compacting` 注入持久上下文。

默认过滤 `memoryhub*` 自身调用，并只记录 `read/edit/write/bash/grep/glob/webfetch`。失败只记日志，不阻塞 Agent。通过 `MEMORYHUB_AUTO_RECORD=false` 可关闭自动沉淀。

## 4. 配置和迁移

统一使用 `MEMORYHUB_API_URL`、`MEMORYHUB_USER_ID`、`MEMORYHUB_PROJECT`、`MEMORYHUB_SCENE`、`MEMORYHUB_TASK_TYPE`。CLI 还读取项目 `.memoryhub/config.json` 和用户配置。

旧的 `opencode-integration/plugin/memoryhub.plugin.mjs` 现在只是兼容入口；新项目应引用 `agent-integration/plugin/opencode/memoryhub.plugin.mjs`。旧 MCP 副本只保留兼容文档，新的 MCP 入口为 `python -m memoryhub_mcp`。

