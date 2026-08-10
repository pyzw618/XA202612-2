# MemoryHub × opencode 接入文档（MCP Server + Plugin）

> 本文档维护「opencode ↔ MemoryHub」两条接入链路所对接的接口与实现的功能。
> 接口以代码为准：REST 契约见 `memoryhub/adapter/api.py`，数据结构见
> `memoryhub/adapter/schemas.py`（`docs/INTERFACE.md` 已过时，不做依据）。
>
> 目录结构（全部位于本 `opencode-integration/` 文件夹内，不改动仓库其他代码）：
>
> ```
> opencode-integration/
> ├── mcp-server/            # MCP Server（Python，stdio JSON-RPC，无第三方 MCP 依赖）
> │   └── memoryhub_mcp/
> │       ├── config.py          # 环境变量配置（MEMORYHUB_*）
> │       ├── client.py          # MemoryHub REST 客户端（httpx）
> │       ├── schemas_bridge.py  # 复用 memoryhub Pydantic 契约做写入校验
> │       ├── tools.py           # 12 个工具的注册与 handler
> │       └── server.py          # MCP stdio 协议层（initialize/tools/list/tools/call）
> ├── plugin/
> │   └── memoryhub.plugin.mjs   # 插件：会话结束后自动把 tool 轨迹沉淀为 MemoryEvent
> ├── scripts/
> │   ├── start_memoryhub_server.py  # 本地启动 MemoryHub REST（含运行期兼容补丁）
> │   ├── install_plugin.mjs         # 把插件复制到 .opencode/plugins/
> │   └── memoryhub_compat.py        # 运行期兼容补丁（见“已知问题”）
> ├── examples/opencode.json    # 接入示例配置
> ├── tests/                    # 集成测试与插件单测
> └── docs/INTEGRATION.md       # 本文档
> ```

---

## 1. 总体架构

```
┌────────────────────────────── opencode ──────────────────────────────┐
│  LLM ── tools/call ──▶ MCP Server (memoryhub_mcp)  ─┐                │
│  Plugin (memoryhub.plugin.mjs) ── session.idle ─────┼──▶ HTTP ──┐    │
└─────────────────────────────────────────────────────┴───────────┘    │
                                                    ┌──────────────────┴─────────────┐
                                                    │  MemoryHub REST (FastAPI)      │
                                                    │  memoryhub/adapter/api.py      │
                                                    │  · 检索 / 写入 / 遗忘 / 反馈   │
                                                    │  · 安全 Gate + 偏好/知识/事实抽取 │
                                                    └────────────────────────────────┘
```

- **MCP Server**（读路径为主，含显式写）：LLM 按需调用 `memoryhub_search`、
  `memoryhub_write_event`、`memoryhub_forget` 等工具，统一走 HTTP 调 MemoryHub REST。
- **Plugin**（写路径自动沉淀）：监听 opencode `session.idle`，把本会话的助手文本与
  工具调用轨迹构造成 `MemoryEvent`（`agent_response` 契约），POST 到 `/api/memory/events`，
  由 MemoryHub 的安全 Gate 过滤后自动抽取偏好/知识/事实。
- 两条链路共享**同一个正在运行的 MemoryHub REST 服务**（本地用
  `scripts/start_memoryhub_server.py` 启动）。

---

## 2. MCP Server

### 2.1 对接的 REST 接口

来源：`memoryhub/adapter/api.py`。

| MCP 工具 | 对接 REST 接口（api.py 行号） | 说明 |
|---|---|---|
| `memoryhub_health` | `GET /api/memory/preferences`（L701，连通性探测） | 服务可达性检查 |
| `memoryhub_search` | `POST /api/memory/search`（L618） | 混合检索偏好/知识/事实 |
| `memoryhub_get_context` | `POST /api/memory/context`（L657） | 取可直接拼 prompt 的上下文文本 |
| `memoryhub_write_event` | `POST /api/memory/events`（L433） | 写入 MemoryEvent，触发安全过滤+抽取 |
| `memoryhub_write_preference` | `POST /api/memory/memories/preference`（L888） | 显式写偏好并同步向量索引 |
| `memoryhub_write_knowledge` | `POST /api/memory/memories/knowledge`（L906） | 显式写知识并同步向量索引 |
| `memoryhub_forget` | `POST /api/memory/forget`（L949） | 自然语言/精确 ID 精准遗忘 |
| `memoryhub_list_memories` | `GET /api/memory/preferences`（L701）、`GET /api/memory/knowledge`（L745）、`GET /api/memory/facts`（L478） | 按类型/场景列出记忆 |
| `memoryhub_get_memory` | `GET /api/memory/preferences/{id}`（L719）、`GET /api/memory/knowledge/{id}`（L765）、`GET /api/memory/facts/{id}`（L492） | 取单条记忆详情 |
| `memoryhub_feedback` | `POST /api/memory/feedback`（L837） | update/confirm/reject 反馈 |
| `memoryhub_list_conflicts` | `GET /api/memory/conflicts`（L782） | 列待处理冲突 |
| `memoryhub_resolve_conflict` | `POST /api/memory/conflicts/{id}/resolve`（L801） | override/merge/coexist/pending 解决冲突 |

### 2.2 复用 memoryhub 数据契约

`schemas_bridge.py` 会把仓库根目录加入 `sys.path` 并导入
`memoryhub.adapter.schemas`，因此：

- `memoryhub_write_event` 用 `MemoryEvent.model_validate()` 校验后再提交，自动满足
  `tool_calls` 唯一性/升序、`occurred_at`（`YYYY-MM-DDTHH:MM:SSZ`）、`agent_response`
  必须含 `turn_id`+`text`+至少一个 `tool_calls`、`source_hash` 为 64 位 hex 等硬性约束；
- `source_hash` 由事件内容 canonical JSON 的 SHA-256 确定性生成；
- 若仓库不可导入（例如把 MCP 跑在无 memoryhub 的机器上），降级为手动构造，由 REST
  服务端兜底校验。

### 2.3 实现的功能

- **检索**：混合检索 + 场景过滤（`context.scene/task_type/app`）+ `memory_types`/
  `min_confidence` 过滤；返回偏好/知识/事实三段的可读摘要（含置信度）。
- **显式写**：偏好、知识、工具事件三种写入，均先经 Pydantic 契约校验。
- **遗忘**：自然语言指令或精确 memory_id，支持按场景范围与级联删除。
- **管理**：列出/查看记忆、反馈（更新/确认/拒绝）、冲突查看与解决。
- **容错**：REST 不可达/超时/业务错误统一转成稳定错误码返回给 LLM（`isError=true`），
  不泄漏异常内部细节；单条 JSON-RPC 消息异常不会杀死 stdio 进程。

---

## 3. Plugin

### 3.1 对接的接口

- **opencode 事件**：`session.idle`（插件文档注册的会话事件）；
  SDK 调用：`client.session.messages({ path: { id } })` 拉取会话消息。
- **MemoryHub REST**：`POST /api/memory/events`（api.py L433）。

### 3.2 实现的功能

1. 会话空闲（`session.idle`）时，按 `sessionID` 去重，拉取该会话全部消息；
2. 从消息 parts 中抽取：
   - 助手文本（`type="text"`）→ 取最后一条非空文本作为 `event.text`；
   - 工具调用（`type="tool"`）→ 映射为 `tool_calls[]`：`tool_name`、`input`→`arguments`、
     `output/result`→`result`、`state.status`→`status`（completed→success、error→error、
     cancelled→cancelled、running/pending→partial），并按出现顺序生成 `sequence`；
3. 组装 `MemoryEvent`：
   - 含工具调用 → `source_type=tool_result`，`event_type=agent_response`，
     `turn_id=session_id`，`scene/task_type` 由环境变量配置（默认 code/coding_task）；
   - 仅文本无工具调用 → `source_type=user_behavior`，`event_type=agent_summary`
     （可通过 `MEMORYHUB_RECORD_SUMMARIES=false` 关闭）；
   - 两者皆无 → 跳过；
4. 计算 `occurred_at`（UTC 秒）与 `source_hash`（64 位 hex），构造 accepted 质量分；
5. POST `/api/memory/events`，由 MemoryHub 完成安全过滤与偏好/知识/事实抽取；
6. **失败软着陆**：所有异常经 `client.app.log` 记录后吞掉，不影响 opencode 会话；
   每次上报也写一条 info 日志（accepted/rejected/event_ids/抽取失败数）。

### 3.3 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MEMORYHUB_API_URL` | `http://127.0.0.1:8000` | REST 服务地址 |
| `MEMORYHUB_USER_ID` | `opencode` | 写入事件的 user_id |
| `MEMORYHUB_AUTO_RECORD` | `true` | 设为 `false` 关闭自动沉淀 |
| `MEMORYHUB_SCENE` | `code` | 事件 scene |
| `MEMORYHUB_TASK_TYPE` | `coding_task` | 事件 task_type |
| `MEMORYHUB_MAX_RESULT_CHARS` | `4000` | 工具输出截断长度 |
| `MEMORYHUB_RECORD_SUMMARIES` | `true` | 是否记录无工具调用的摘要事件 |

> opencode 配置 schema 没有顶层 `env`，插件变量需在启动 opencode 前导出到进程环境
> （或在 shell profile 中设置）。MCP Server 的变量则可写在 `opencode.json` 的
> `mcp.memoryhub.environment` 里。

---

## 4. 安装与运行

### 4.1 启动 MemoryHub REST（本地开发）

```bash
# 进入本文件夹的父目录（仓库根）
python opencode-integration/scripts/start_memoryhub_server.py --port 8000
```

默认 dev 模式：embedding=mock、向量引擎=faiss、user_rules 关闭、安全密钥自动生成、
数据落在 `opencode-integration/.memoryhub-data/`。启动即应用运行期兼容补丁（见第 6 节）。

生产/麒麟环境：用真实 `config.yaml` 起标准服务，只需把 `MEMORYHUB_API_URL` 指向它；
本仓库提供的补丁仅用于修正两个影响事件落盘的已知问题（见第 6 节）。

### 4.2 接入 MCP Server

把 `examples/opencode.json` 的 `mcp` 段合并进项目的 `opencode.json`：

```jsonc
{
  "mcp": {
    "memoryhub": {
      "type": "local",
      "command": ["python", "-m", "memoryhub_mcp"],
      "cwd": "opencode-integration/mcp-server",
      "environment": {
        "MEMORYHUB_API_URL": "http://127.0.0.1:8000",
        "MEMORYHUB_USER_ID": "opencode"
      },
      "enabled": true
    }
  }
}
```

`python` 需为 Python ≥ 3.10 且装有 `httpx`（`pip install -r opencode-integration/mcp-server/requirements.txt`）。

### 4.3 接入 Plugin

```bash
node opencode-integration/scripts/install_plugin.mjs   # 复制到 .opencode/plugins/
```

然后导出第 3.3 节环境变量并重启 opencode。插件即随 `session.idle` 自动沉淀记忆。

---

## 5. 测试

```bash
# MCP Server 集成测试（起真实 uvicorn + 真实 memoryhub 应用，走 HTTP 全链路）
D:/Anaconda/envs/py12/python.exe -m pytest opencode-integration/tests/test_mcp_server.py -v

# Plugin 事件构造单测
node opencode-integration/tests/test_plugin_event_builder.mjs
```

覆盖：MCP initialize/tools/list/tools/call 协议、12 个工具存在性、健康检查、
写偏好→检索命中、`agent_response` 事件写入、遗忘、契约校验错误回显、stdio 子进程冒烟；
插件侧：`occurred_at`/`source_hash` 格式、工具调用序列与状态映射、摘要事件、空会话跳过。

---

## 6. 已知问题与运行期兼容补丁（重要）

> 2026-08-08 更新：下述两个 bug 已在 memoryhub 源码层面修复，记录见
> `docs/DATA_FLOW_UPDATE.md`。`scripts/memoryhub_compat.py` 中的运行期补丁因此
> **不再必需**，仅作为旧版本 checkout 的兜底保留（无害）；新代码直接依赖源码修复。

在**不修改任何 memoryhub 源码**的前提下，`scripts/memoryhub_compat.py` 可于启动时修正
以下两个问题（只影响「事件写入」链路 `POST /api/memory/events`，不影响检索）：

1. **`TypeError: Object of type _ImmutableMapping is not JSON serializable`**（已修复）
   - 现象：安全 Gate 通过（`ALLOW/MASK`）的事件被包装为深度只读的
     `_SafeMemoryEvent`，其 `payload` 是 `_ImmutableMapping`；而
     `EventRepository._to_row` 直接把 `event.payload` 交给 SQLAlchemy JSON 列
     序列化，导致 clean 事件**必然 500/503**。
   - 源码修复：`EventRepository._to_row` 改为先 `event.model_dump(mode="json")`
     投影再构造行（`memoryhub/storage/database.py`）。
2. **`re._parser` / `re._constants` 缺失**（已修复）
   - 现象：部分 Python 发行版（含本机 Anaconda 环境）不暴露 `re._parser`，
     `memoryhub.safety_rules.regex_safety` 导入后 `sre_parser=None`，规则库加载失败。
   - 源码修复：`regex_safety.py` 增加 `sre_parse`/`sre_constants` 回退，
     麒麟标准 CPython（3.11+）走原生 `re._parser`。
3. **安全密钥要求**（未变更）
   - 安全 Gate 要求 `MEMORYHUB_AUDIT_HMAC_KEY` 与 `MEMORYHUB_QUARANTINE_KEY`
     为 **32 字节 Base64**（各密钥不得复用）；启用 `user_rules` 还需
     `MEMORYHUB_USER_RULE_KEY` 与认证身份 resolver。`ensure_safety_keys()` 在开发模式
     自动生成临时密钥；生产请从密钥服务注入。

> 接入清单修订原则：今后 memoryhub 改 REST 或 schema，只需同步更新本文件
> 「第 2.1 节」的接口映射表与 `memoryhub_mcp/tools.py`；MCP 工具返回文本与
> plugin 事件构造不依赖 `docs/` 旧文档。
