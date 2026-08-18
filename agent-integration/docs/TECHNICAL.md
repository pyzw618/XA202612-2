# Agent 接入技术说明

## 目标

当前接入以 MCP 为主会把工具 schema 和协议进程长期放进 Agent 上下文。这里采用 CLI 为底层母语：一次安装得到完整 REST 能力，opencode 默认使用三个原生 custom tool 和命令；需要跨 Agent 标准时再启用同一份 MCP stdio server。

## Python 包

`memoryhub_client` 使用 `httpx.Client`，统一处理超时、不可达、HTTP 错误和安全业务结果。`_request` 只负责 `/api/memory`，`_root_request` 负责 `/api` 下的 agent 兼容路由，避免路径拼接产生越权或错误路由。客户端不导入核心存储模块，故可独立安装。

`memoryhub_cli` 使用 argparse。命令执行流程是：读取三层配置 -> 构造 payload -> 调用 client -> compact/json/quiet 格式化。`forget` 默认必须先 `--preview`，执行删除需要 `--yes`。`event -` 支持 stdin，便于 hooks 和脚本串接。

`memoryhub_mcp` 是无第三方 MCP SDK 的 stdio JSON-RPC 实现，只注册八个高频工具。`initialize`、`tools/list`、`tools/call` 及空的 resources/prompts 响应保持标准形状；错误以结构化文本返回，单条请求失败不关闭进程。

## JavaScript Plugin

`memoryhub_events.mjs` 是纯函数层：截断工具输出、白名单过滤、状态归一化、项目 provenance、事件 hash 和回合累积均在这里完成。插件本身只负责把 opencode hook 事件转给累积器，把事件 POST 到 `/api/memory/events`，以及通过 Bun/Node 调用 CLI。

自动沉淀的生命周期如下：

1. `tool.execute.after` 记录工具名、参数、结果、状态和序号；
2. `session.status` 进入 `idle` 时清空当前回合并提交 `agent_response`；
3. `session.deleted` 清空残留并以兜底事件提交；
4. `experimental.session.compacting` 在压缩前调用 `memoryhub context`，将持久上下文附加到压缩输入。

## 验证

```powershell
python -m compileall -q agent-integration/memoryhub_client agent-integration/memoryhub_cli agent-integration/memoryhub_mcp
python -m pytest -q agent-integration/tests
node agent-integration/tests/test_plugin_events.mjs
python -m pip install -e .
memoryhub --help
```

