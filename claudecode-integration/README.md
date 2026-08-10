# MemoryHub × Claude Code 集成

把 Kylin-MemoryHub 记忆模块接入 **Claude Code** 的两条链路，与
`opencode-integration/`（opencode 接入）等价：

- **MCP Server**（`mcp-server/`）：LLM 按需调用 `memoryhub_search`、
  `memoryhub_write_event`、`memoryhub_forget` 等 12 个工具读写记忆。
- **Plugin + Hooks**（`plugin/memoryhub/`）：监听 `PostToolBatch` / `Stop` /
  `SessionEnd`，把 Claude Code 会话的工具轨迹自动沉淀为 MemoryHub `MemoryEvent`
  （偏好 / 知识 / 事实抽取）。

两者共享同一个 MemoryHub REST 服务（`scripts/start_memoryhub_server.py` 启动）。

## 快速开始

```bash
# 1. 启动 MemoryHub REST（dev 模式）
D:/Anaconda/envs/py12/python.exe claudecode-integration/scripts/start_memoryhub_server.py --port 8000

# 2. 安装插件到 ~/.claude/plugins/（固定解释器）
powershell -ExecutionPolicy Bypass -File claudecode-integration/scripts/install_plugin.ps1 \
    -PythonPath D:\Anaconda\envs\py12\python.exe

# 3. 导出环境变量并重启 Claude Code
$env:MEMORYHUB_API_URL = 'http://127.0.0.1:8000'
$env:MEMORYHUB_USER_ID = 'claudecode'
```

不装插件也可用项目级配置（`examples/` 的 `.mcp.json` + `settings.local.json`）。

## 文档

- **接入方案、映射表、安装与配置、已知问题**：`docs/CLAUDE_INTEGRATION.md`
- **插件说明**：`plugin/memoryhub/README.md`

## 测试

```bash
# 自动沉淀脚本单测 + 配置文件结构校验
D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_record.py \
    claudecode-integration/tests/test_configs.py -v

# MCP server E2E（起真实 uvicorn + memoryhub 应用）
D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_mcp_server.py -v
```

## 与 opencode 接入的关系

- MCP 协议是标准，`memoryhub_mcp` 在 opencode 与 Claude Code 间**同一实现**；
  本目录 `mcp-server/` 是自包含副本，另加了 Claude Code 需要的能力：
  `initialize` 返回 `instructions`（配合 Claude Code 的 tool search）、支持 `roots/list`、
  `config.py` 识别 `CLAUDE_PROJECT_DIR`。
- 自动沉淀链路：opencode 用 Plugin（`session.idle` 整会话一次）；Claude Code 用
  Hooks（`PostToolBatch` 按批次累积 + `Stop` 按回合冲刷，粒度更细）。
- 改动 opencode-integration 下的 `memoryhub_mcp` 时，需同步本目录副本（见文档维护约定）。
