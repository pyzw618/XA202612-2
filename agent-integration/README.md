# Agent Integration

统一的 MemoryHub Agent 接入层。CLI 是底层母语，MCP 和 OpenCode Plugin 都是薄壳；所有入口最终调用同一 REST 契约。

## 安装

```powershell
python -m pip install -e .
```

这会注册 `memoryhub` CLI 入口，并安装 `memoryhub_client`、`memoryhub_mcp`。

## CLI

```powershell
memoryhub --help
memoryhub search "周报格式" --json
memoryhub context "今天的工作计划"
memoryhub remember --type preference "我习惯用 Markdown 写周报"
memoryhub event examples/vnext_demo/event_start_report.json
memoryhub resume task_report_demo
memoryhub forget "删除周报格式偏好" --preview
```

CLI 完整命令列表见 `memoryhub_cli/cli.py` 或运行 `memoryhub --help`。

## SDK

```python
from memoryhub_client import MemoryHubClient

client = MemoryHubClient(base_url="http://127.0.0.1:8099", user_id="default")

# vNext 统一写入
client.write_canonical_events([...])

# vNext 统一检索
client.vnext_search({"query": "周报格式", "top_k": 5})

# 任务恢复
client.resume_task("task_report_demo")

# 精确遗忘预览
client.forget_preview({"instruction": "删除周报格式偏好"})
```

## MCP Server

```powershell
python -m memoryhub_mcp
```

工具列表：

- `memoryhub_health`
- `memoryhub_search`
- `memoryhub_get_context`
- `memoryhub_write_event`
- `memoryhub_resume_task`
- `memoryhub_remember`
- `memoryhub_forget`
- `memoryhub_feedback`
- `memoryhub_knowledge_fact_propose`

## OpenCode Plugin

```powershell
node agent-integration/plugin/opencode/install_plugin.mjs
```

## REST 契约

vNext REST 契约定义在 `memoryhub/adapter/vnext_schemas.py`，文档见 `docs/spec/VNEXT_INTERFACE.md`。

主要端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/memory/vnext/events` | 统一写入 |
| POST | `/api/memory/vnext/search` | 统一检索 |
| POST | `/api/memory/vnext/context` | 统一上下文 |
| GET | `/api/memory/vnext/tasks/{task_id}/resume` | 任务恢复 |
| POST | `/api/memory/vnext/forget` | 精确遗忘 |
| GET | `/api/memory/vnext/forget/{record_id}` | 遗忘状态 |
| POST | `/api/memory/vnext/diagnostics` | 诊断（管理权限） |

## 更多文档

- 部署与运维：`docs/spec/VNEXT_DEPLOYMENT.md`
- 迁移与回滚：`docs/spec/VNEXT_MIGRATION.md`
- 备份与恢复：`docs/spec/VNEXT_BACKUP_RECOVERY.md`
- 故障处理：`docs/spec/VNEXT_FAULT_HANDLING.md`
- 灰度与回滚：`docs/spec/VNEXT_ROLLOUT.md`
- Trace 契约：`docs/spec/VNEXT_TRACE.md`
