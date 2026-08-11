# MemoryHub × Claude Code 接入文档（MCP Server + Plugin/Hooks）

> 本文档维护「Claude Code ↔ MemoryHub」接入链路所对接的接口、实现的功能与已知问题。
> 接口以代码为准：REST 契约见 `memoryhub/adapter/api.py`，数据结构见
> `memoryhub/adapter/schemas.py`。
>
> 目录结构（全部位于本 `claudecode-integration/` 文件夹内，不改动仓库其他代码）：
>
> ```
> claudecode-integration/
> ├── mcp-server/                 # MCP Server 自包含副本（Python stdio JSON-RPC，无第三方 MCP 依赖）
> │   └── memoryhub_mcp/          #   · 与 opencode-integration/mcp-server 同源，另加 Claude Code 能力
> ├── plugin/memoryhub/           # Claude Code 插件（可整体复制到 ~/.claude/plugins/）
> │   ├── .claude-plugin/plugin.json   # 插件清单
> │   ├── .mcp.json                    # memoryhub MCP server（stdio）
> │   ├── hooks/hooks.json             # PostToolBatch / Stop / SessionEnd（+ UserPromptSubmit）
> │   ├── scripts/record.py            # 自动沉淀：accumulate / flush-turn / flush-all
> │   ├── scripts/context.py           # 可选：UserPromptSubmit 记忆上下文注入
> │   ├── scripts/memoryhub_compat.py  # 运行期兼容补丁（启动服务时用）
> │   └── mcp-server/                  # 插件内嵌的 MCP 包（安装后自包含）
> ├── examples/
> │   ├── .mcp.json                    # 非插件方式：项目级 MCP 配置
> │   └── settings.local.json          # 非插件方式：项目级 hooks
> ├── scripts/
> │   ├── start_memoryhub_server.py    # 本地启动 MemoryHub REST（含稳定密钥/审计目录隔离）
> │   ├── memoryhub_compat.py          # 运行期兼容补丁
> │   └── install_plugin.ps1           # 把插件复制到 ~/.claude/plugins/（可固定解释器）
> ├── tests/                           # record 单测 / MCP E2E / 配置结构校验
> └── docs/CLAUDE_INTEGRATION.md       # 本文档
> ```

---

## 1. 总体架构

```
┌────────────────────────────── Claude Code ──────────────────────────────┐
│  LLM ── tools/call ──▶ MCP Server (memoryhub_mcp)        ─┐             │
│  Hooks ── PostToolBatch/Stop/SessionEnd ──▶ record.py ────┼─▶ HTTP ──┐  │
│          (可选 UserPromptSubmit ──▶ context.py 注入上下文)            │  │
└──────────────────────────────────────────────────────────┴───────────┘  │
                                                  ┌───────────────────────┴──────────────┐
                                                  │  MemoryHub REST (FastAPI)            │
                                                  │  memoryhub/adapter/api.py            │
                                                  │  · 检索 / 写入 / 遗忘 / 反馈          │
                                                  │  · 安全 Gate + 偏好/知识/事实抽取      │
                                                  └──────────────────────────────────────┘
```

- **MCP Server**（读路径为主，含显式写）：LLM 按需调用 12 个 `memoryhub_*` 工具，
  统一走 HTTP 调 MemoryHub REST。
- **Hooks**（写路径自动沉淀）：
  - `PostToolBatch`（异步）把每批工具调用写入 per-turn pending 文件；
  - `Stop`（异步）把该回合的 `last_assistant_message` + 工具轨迹组装成
    `MemoryEvent` POST 到 `/api/memory/events`；
  - `SessionEnd` 兜底清理遗留 pending；
  - `UserPromptSubmit`（可选，默认关）把用户提示发到 `/api/memory/context`
    并把命中的记忆上下文注入 Claude。
- 两条链路共享**同一个正在运行的 MemoryHub REST 服务**。

### 与 opencode 插件的对照

| 能力 | opencode | Claude Code |
|---|---|---|
| 工具调用 | MCP Server `memoryhub_mcp` | 同一实现（本目录自包含副本） |
| 自动沉淀触发 | Plugin `session.idle`（整会话一次） | Hook `Stop`（每回合一次，粒度更细） |
| 工具轨迹来源 | `client.session.messages()` 拉全量 | `PostToolBatch` 逐批累积（按 turn 分文件） |
| 会话结束兜底 | 无 | `SessionEnd` flush-all |

---

## 2. MCP Server

与 opencode 的 `memoryhub_mcp` 同源（`opencode-integration/mcp-server/`），
本目录 `mcp-server/memoryhub_mcp/` 是**自包含副本**，并针对 Claude Code 做了三处增强：

1. `initialize` 响应增加 `instructions`（`SERVER_INSTRUCTIONS`），Claude Code 的
   MCP tool search 据此决定何时加载 MemoryHub 工具；
2. 支持 `roots/list`，返回项目根（`CLAUDE_PROJECT_DIR`）；
3. `config.py` 的 `_find_repo_root()` 新增 `CLAUDE_PROJECT_DIR` 解析线索，并暴露
   `project_root`。

工具清单、参数、REST 接口映射与 opencode 完全一致，见
`opencode-integration/docs/INTEGRATION.md` 第 2 节（本目录不重复维护）。

### Claude Code 配置（插件内嵌）

`plugin/memoryhub/.mcp.json`：

```json
{
  "mcpServers": {
    "memoryhub": {
      "type": "stdio",
      "command": "${MEMORYHUB_PYTHON:-python}",
      "args": ["-m", "memoryhub_mcp"],
      "env": {
        "PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}/mcp-server",
        "MEMORYHUB_REPO_ROOT": "${CLAUDE_PROJECT_DIR}",
        "MEMORYHUB_API_URL": "${MEMORYHUB_API_URL:-http://127.0.0.1:8000}",
        "MEMORYHUB_USER_ID": "${MEMORYHUB_USER_ID:-claudecode}",
        "MEMORYHUB_TOP_K": "${MEMORYHUB_TOP_K:-5}"
      }
    }
  }
}
```

- `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PROJECT_DIR}` 由 Claude Code 对插件配置直接替换
  （无需 `:-default`）；`${MEMORYHUB_PYTHON:-python}` 是 `.mcp.json` 的通用
  `${VAR:-default}` 环境变量展开。
- 本机 PATH 上的 `python` 是 3.7，而 `memoryhub_mcp` 需要 Python ≥ 3.10 + `httpx`，
  **务必设置 `MEMORYHUB_PYTHON`**（如 `D:\Anaconda\envs\py12\python.exe`），或用
  `install_plugin.ps1 -PythonPath` 固定。
- 插件工具的完整调用名是 `mcp__plugin_memoryhub_memoryhub__<tool>`（在权限规则、
  hook matcher 中引用时注意）。

---

## 3. Hooks（自动沉淀）

### 3.1 事件选择

| Hook 事件 | 模式 | 作用 |
|---|---|---|
| `PostToolBatch` | async | 每批工具调用完成后，把该批工具轨迹写入 per-turn pending 文件（`<session>_<turn>.jsonl`，位于 `CLAUDE_PLUGIN_DATA/pending/`） |
| `Stop` | async | 回合结束，把 pending 轨迹 + `last_assistant_message` 组装为 `MemoryEvent` 并 POST；成功后删除 pending |
| `SessionEnd` | sync | 兜底：把遗留 pending 作为 summary 事件尽力冲刷（共享 1.5s 预算，见已知问题 4） |
| `UserPromptSubmit` | sync | 可选：把用户提示发到 `/api/memory/context`，stdout 注入上下文（默认关） |

### 3.2 事件构造

`record.py`（纯标准库，3.7+ 可运行）：

- 有工具调用 → `source_type=tool_result`，`event_type=agent_response`，
  `turn_id=prompt_id`，`text=last_assistant_message`（空则用占位文本）；
- 无工具调用但 `MEMORYHUB_RECORD_SUMMARIES=true` 且有文本 → `user_behavior` /
  `agent_summary`；
- 跳过 MemoryHub 自身工具（`tool_name` 含 `memoryhub`），避免自我记录；
- 默认跳过子代理工具（`agent_id` 存在），可用 `MEMORYHUB_RECORD_SUBAGENTS=true` 开启；
- `source_hash` = 种子字段 canonical JSON 的 SHA-256（64 位 hex）；
- 若 `memoryhub` 包可导入，则用真实 `MemoryEvent` Pydantic 校验，否则手动构造、
  由 REST 服务端兜底校验。

### 3.3 hooks.json

```json
{
  "hooks": {
    "PostToolBatch": [{ "hooks": [{ "type": "command", "command": "python",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/record.py", "--accumulate"],
        "async": true, "timeout": 10 }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "python",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/record.py", "--flush-turn"],
        "async": true, "timeout": 60 }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "python",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/record.py", "--flush-all"],
        "timeout": 60 }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/context.py"], "timeout": 30 }] }]
  }
}
```

- 插件 hooks 里 `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PROJECT_DIR}` 由 Claude Code 替换。
- **hooks 的 `command` 不支持 `${VAR}` 环境变量展开**，只能用 PATH 上的 `python`
  （`record.py` 纯标准库所以 3.7 也能跑；若要与 MCP 同解释器，用
  `install_plugin.ps1 -PythonPath` 或手动改 `command`）。
- `Stop` 用 `async`：开发环境无 LLM 时事件落库约需 16s（抽取连接超时），异步避免阻塞会话。

### 3.4 失败软着陆

`record.py` / `context.py` 永远以退出码 0 结束；任何失败只写 stderr（进 debug 日志），
不会阻塞、拒绝或打断 Claude Code。

---

## 4. 安装与运行

### 4.1 启动 MemoryHub REST（本地开发）

```bash
D:/Anaconda/envs/py12/python.exe claudecode-integration/scripts/start_memoryhub_server.py --port 8000
```

- dev 模式：embedding=mock、向量引擎=faiss、user_rules 关闭；
- 数据落在 `claudecode-integration/.memoryhub-data/`；
- **稳定密钥**：`security/safety-keys.json` 由 MemoryHub 核心首次创建并跨重启复用；
  旧 `dev-safety-keys.json` 会自动安全导入；
  审计链 / 隔离区目录被收进 data_dir（`safety-audit/`、`review-quarantine/`），
  重启不再因密钥变化导致 `audit.head_invalid`（见已知问题 1）；
- `--reset-dev-data` 一键清空 dev 数据目录后重启；
- 生产/麒麟环境：`--config /path/to/config.yaml` 用真实配置起标准服务，
  只需把 `MEMORYHUB_API_URL` 指向它。

### 4.2 接入插件（推荐）

```bash
powershell -ExecutionPolicy Bypass -File claudecode-integration/scripts/install_plugin.ps1 -PythonPath D:\Anaconda\envs\py12\python.exe
```

复制到 `~/.claude/plugins/memoryhub/` 后，重启 Claude Code，在 `/plugin` 中启用
`memoryhub`；或临时用 `claude --plugin-dir claudecode-integration/plugin/memoryhub`。
然后导出 `MEMORYHUB_API_URL` / `MEMORYHUB_USER_ID`（必要时 `MEMORYHUB_PYTHON`）。

### 4.3 非插件方式（项目级配置）

把 `examples/.mcp.json` 合并进项目根的 `.mcp.json`，把 `examples/settings.local.json`
合并进 `.claude/settings.local.json`（或 `.claude/settings.json`）。注意非插件
`.mcp.json` 里引用 `${CLAUDE_PROJECT_DIR}` 需要 `:-default` 兜底（示例已带）。

---

## 5. 测试

```bash
D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_record.py \
    claudecode-integration/tests/test_configs.py -v     # 自动沉淀 + 配置结构
D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_mcp_server.py -v  # MCP E2E
```

覆盖：事件构造（agent_response / agent_summary / 跳过）、工具截断、MemoryHub 工具
自记录过滤、子代理过滤、按 turn 隔离、flush 幂等、`--reset-dev-data` 与稳定密钥、
MCP initialize(instructions)/roots/list/tools/list/tools/call、配置 JSON 结构、
`record.py` 仅用标准库。

---

## 6. 已知问题与注意事项

1. **dev 模式 503（`event ingestion service not initialized` / `audit.head_invalid`）**
   - 旧根因：dev 模式每 boot 自动生成随机安全密钥，而审计链 head 落在固定
     `data/safety-audit/`；重启后新密钥使旧 head HMAC 校验失败。
   - 当前修复：MemoryHub 核心首次生成并持久保存密钥，审计/隔离目录与数据库统一
     收进 data_dir；重启自动复用。旧 `dev-safety-keys.json` 自动导入到
     `security/safety-keys.json`，无需删除已有数据。`--reset-dev-data` 仅用于用户
     明确要求整体重置开发数据的场景。
2. **开发环境无 LLM 时事件落库慢（约 16s）**
   - 事件在 `ingest` 内同步等待抽取（LLM 连接超时），无 LLM 时
     `extraction_failures=2`、`retry_tasks_enqueued=2` 且耗时约 16s（偏好与事实抽取分别进入重试队列）。`record.py` 默认超时 60s；`Stop` 用
     `async` 使该耗时不再阻塞 Claude Code。生产接真实 LLM 后即快。
3. **hooks 解释器**：hooks `command` 不能用环境变量展开，默认走 PATH 上的
   `python`（record.py 纯标准库可跑）；MCP 走 `${MEMORYHUB_PYTHON:-python}`。
   建议用 `install_plugin.ps1 -PythonPath` 统一固定。
4. **SessionEnd 预算**：SessionEnd hooks 共享 1.5s 预算，插件 hooks 的 `timeout`
   不会抬高预算。遗留 pending 冲刷可能被截断；可设
   `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS=60000` 抬高。逐回合的 `Stop` 冲刷才是主链路。
5. **异步 hook 的竞态**：`PostToolBatch`/`Stop` 均异步，pending 按 `(session, turn)`
   分文件 + 文件锁隔离读写；`flush-turn` 前有 `MEMORYHUB_FLUSH_SETTLE_MS`（默认
   300ms）等待。极端情况下最后一个批次的轨迹可能未被 Stop 捕获（丢失可接受，
   不会出错）。

---

## 7. 维护约定

- `mcp-server/memoryhub_mcp/` 是 `opencode-integration/mcp-server/memoryhub_mcp/`
  的副本。**改 opencode 侧的 MCP 包时需同步本目录副本**（`config.py` 的
  `project_root`/`CLAUDE_PROJECT_DIR` 与 `server.py` 的 `instructions`/`roots/list`
  是本目录独有，注意保留）。
- 插件内 `scripts/memoryhub_compat.py` 与 `scripts/start_memoryhub_server.py` 里的
  兼容补丁随 `opencode-integration` 的对应实现走；两个 bug 已在源码层面修复，
  补丁仅作旧 checkout 兜底。
- 改动 memoryhub REST 或 schema 时：同步 `memoryhub_mcp/tools.py` 的接口映射与
  `record.py` 的事件构造即可，本文档第 2、3 节据此更新。
