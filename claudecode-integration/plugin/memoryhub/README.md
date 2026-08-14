# memoryhub — Claude Code 插件

把 Kylin-MemoryHub 记忆引擎接入 Claude Code 的完整插件（MCP 工具 + 自动沉淀 hooks）。

启用后提供：

- **MCP 工具**（`memoryhub` 服务器，12 个）：`memoryhub_search`、`memoryhub_get_context`、
  `memoryhub_write_event`、`memoryhub_write_preference`、`memoryhub_write_knowledge`、
  `memoryhub_forget`、`memoryhub_list_memories`、`memoryhub_get_memory`、
  `memoryhub_feedback`、`memoryhub_list_conflicts`、`memoryhub_resolve_conflict`、
  `memoryhub_health`。
- **自动沉淀 hooks**：`PostToolBatch` 异步累积工具轨迹 → `Stop` 异步冲刷为 MemoryEvent
  → `SessionEnd` 兜底清理。可选 `UserPromptSubmit` 记忆上下文注入（默认关）。

## 目录

```
memoryhub/
├── .claude-plugin/plugin.json   # 插件清单
├── .mcp.json                    # memoryhub MCP server（stdio，自包含）
├── hooks/hooks.json             # PostToolBatch + Stop + SessionEnd（+ UserPromptSubmit）
├── scripts/
│   ├── record.py                # 自动沉淀：accumulate / flush-turn / flush-all
│   ├── context.py               # 可选：UserPromptSubmit 记忆上下文注入
│   └── memoryhub_compat.py      # 运行期兼容补丁（启动服务时用）
└── mcp-server/                  # memoryhub_mcp 包（自包含副本，见 docs/CLAUDE_INTEGRATION.md）
```

## 启用

```powershell
# 1. 安装到用户插件目录（复制即可，或用 `claude --plugin-dir`）
powershell -ExecutionPolicy Bypass -File claudecode-integration/scripts/install_plugin.ps1
#    如需固定解释器（本机 PATH 上的 python 是 3.7，MCP 需要 3.10+）：
powershell -ExecutionPolicy Bypass -File claudecode-integration/scripts/install_plugin.ps1 `
    -PythonPath D:\Anaconda\envs\py12\python.exe

# 2. 启动 MemoryHub REST（dev 模式）
D:/Anaconda/envs/py12/python.exe claudecode-integration/scripts/start_memoryhub_server.py

# 3. 导出环境变量
$env:MEMORYHUB_API_URL = 'http://127.0.0.1:8099'
$env:MEMORYHUB_USER_ID = 'claudecode'

# 4. 重启 Claude Code，在 /plugin 中启用 memoryhub（或用 --plugin-dir 指向本目录）
```

`MEMORYHUB_PYTHON` 供 MCP server 使用（`${MEMORYHUB_PYTHON:-python}`）；hooks 使用
PATH 上的 `python`（record.py 纯标准库，3.7+ 可跑；如需与 MCP 同解释器，用
`install_plugin.ps1 -PythonPath` 或手动改 `hooks/hooks.json` 的 `command`）。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MEMORYHUB_API_URL` | `http://127.0.0.1:8099` | REST 服务地址 |
| `MEMORYHUB_USER_ID` | `claudecode` | 写入事件的 user_id |
| `MEMORYHUB_AUTO_RECORD` | `true` | 设为 `false` 关闭自动沉淀 |
| `MEMORYHUB_SCENE` | `code` | 事件 scene |
| `MEMORYHUB_TASK_TYPE` | `coding_task` | 事件 task_type |
| `MEMORYHUB_MAX_RESULT_CHARS` | `4000` | 工具输出截断长度 |
| `MEMORYHUB_RECORD_SUMMARIES` | `true` | 无工具调用的回合是否记摘要事件 |
| `MEMORYHUB_RECORD_SUBAGENTS` | `false` | 是否记录子代理的工具调用 |
| `MEMORYHUB_FLUSH_SETTLE_MS` | `300` | flush 前等待异步累积落盘的毫秒数 |
| `MEMORYHUB_CONTEXT_ON_PROMPT` | `false` | 开启 UserPromptSubmit 记忆上下文注入 |

> hooks 不读取 `$env` 展开，环境变量由脚本进程继承；在启动 Claude Code 前导出即可。
