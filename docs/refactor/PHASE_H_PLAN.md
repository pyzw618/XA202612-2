# Phase H 规划：Agent 接入统一 API 收敛（CLI/MCP/Plugin 对接）

> 状态：**已规划，待交接团队实施**
> 依据：`docs/REFACTOR_PLAN_V2.md` §4.9（Agent 接入与统一 API 面）、`docs/Agent接入设计.md` §12~§14（统一 API 契约）
> 本次交接需实现：把 `docs/Agent接入设计.md` 的"CLI 母语 / Plugin 薄壳 / MCP 跨 Agent 标准"三面契约落到真实代码，与重构后的核心接口（FACT 并入知识、记忆分层、语义遗忘、反馈闭环）对齐。

---

## 1. 背景与目标

后端核心重构（Phase A/B/C/D/E/G）已完成并推送，核心暴露的 REST 契约已收敛。但**接入层**（`opencode-integration/`、`claudecode-integration/`）仍是旧契约，与重构后的核心存在漂移：

| 旧接入层现状 | 重构后核心 | 差距 |
|---|---|---|
| 14 个 MCP 工具含 `propose_facts/decide_facts` | FACT 已并入知识（`knowledge_type=fact`） | 事实工具需并入知识面 |
| `propose_facts` 独立 | `POST /memories/knowledge`（含 FACT） | 接口合并 |
| 无 level 维度 | `SearchRequest.level` / 记忆分层（short/mid/long） | CLI/MCP 需暴露分层 |
| 无溯源/投影入口 | `GET /api/memory/v2/...lineage/evidence/audit/projections` | CLI 缺 `provenance`/`projection` |
| 无统一更新 | `PUT /api/memory/{type}/{id}` | 缺 `update` |
| 自反馈未闭环 | `POST /api/memory/feedback`（confirm→健康度） | skill 引导 feedback confirm |
| 无 CLI | `pyproject.toml` 无 `console_scripts` | 需建 `memoryhub` CLI |

**目标**：按 `docs/Agent接入设计.md` §14 统一 API 契约，把 `memoryhub_client`、`memoryhub_cli`、MCP 工具面收敛为**同一套 REST 契约**；CLI 是"母语"，Plugin 的 custom tools/commands 是 CLI 薄壳，MCP 是跨 Agent 标准接口。消灭三处 MCP 拷贝。

---

## 2. 统一 API 契约（权威表，来自 `docs/Agent接入设计.md` §14.1）

| 核心能力 | REST 统一面 | CLI（母语） | MCP/工具（低频走 CLI） |
|---|---|---|---|
| 多源事件写入（工具/行为/配置） | `POST /api/memory/events` | `event` | `write_event` |
| 混合检索（+level/project/provenance） | `POST /api/memory/search` | `search` | `search` |
| 上下文注入（分层级联） | `POST /api/memory/context` | `context` | `get_context` |
| 显式写偏好/知识（含 FACT） | `POST /memories/preference\|knowledge` | `remember --type` | `remember` |
| 统一记忆更新 | `PUT /api/memory/{type}/{id}` | `update <id>` | 低频 → CLI |
| 反馈强化（艾宾浩斯复习） | `POST /api/memory/feedback` | `feedback` | `feedback` |
| NL 精准遗忘（先预览） | `POST /forget` + `/forget/preview` | `forget --preview` | `forget` |
| 溯源 lineage/evidence/audit | `GET /api/memory/v2/memories/{id}/...` | `provenance <id>` | 低频 → CLI |
| 投影恢复 | `GET/POST /api/memory/v2/projections` | `projection list/replay` | 管理 → CLI |
| 健康/状态 | `GET /api/memory/system/status` | `status` | 运维 → CLI |

> **权威字段**：均在 `docs/Agent接入设计.md` §14.1~14.4，本阶段以 §14 为准，其余旧表作废。

---

## 3. 实施项（按序）

### 3.1 目录收敛（`docs/Agent接入设计.md` §5.1）
新建 `agent-integration/`（替代 `opencode-integration/` + `claudecode-integration/` 重复 MCP 部分）：

```
agent-integration/
├── pyproject.toml                # console_scripts: memoryhub = memoryhub_cli.cli:main
├── memoryhub_client/client.py    # 全 REST 方法（在 integrations/memoryhub_client.py 上扩充）
├── memoryhub_mcp/                # 【唯一一份】MCP stdio server
│   ├── server.py / tools.py / config.py / schemas_bridge.py
├── memoryhub_cli/
│   ├── cli.py / format.py / config.py
├── plugin/opencode/              # custom tools + commands + skills + hooks
├── tests/                        # test_cli.py / test_mcp_server.py / test_plugin_events.mjs
└── examples/opencode.json, memoryhub.config.json
```

### 3.2 统一客户端 `memoryhub_client/client.py`（`docs/Agent接入设计.md` §5.2）
覆盖全 REST 面，方法含：`health/search/get_context/write_events/write_preference/write_knowledge(含FACT)/update_memory/forget/forget_preview/feedback/provenance/list_projections/replay_projection/list/generate/export/import/system_status`。统一 `HTTPError → MemoryHubError`（含 status_code/code/safety_action/audit_id）。

### 3.3 CLI `memoryhub_cli/cli.py`（`docs/Agent接入设计.md` §7）
- 全局选项：`-u/--user`、`--api-url`、`--project`、`--scene/--task-type`、`--timeout`、`-j/--json`、`-c/--compact`、`-q/--quiet`。
- 子命令面（重构后对齐）：
  ```
  search/context/event
  remember [--type preference|knowledge:workflow|case|template|fact] [--project]
  update <memory_id> [--text|--knowledge-type|--scope]
  forget <指令|ID> [--preview] [--cascade]
  list [--type] [--level short|mid|long] [--status]
  get <memory_id>
  provenance <memory_id> [lineage|evidence|audit]
  projection list [--status] ; projection replay <outbox_id...>
  feedback <id> confirm|reject|update <text>
  knowledge fact propose <triples.json>        # 原独立 fact 子命令并入知识
  export/import/status/service start|stop/completion
  ```
- 输出契约：`--compact`（默认）/`--json`/`--quiet` 三档（见 `docs/Agent接入设计.md` §7.3 示例）。
- **复用** `memoryhub_client`，不重复写 HTTP。

### 3.4 单一 MCP 包（`docs/Agent接入设计.md` §5.3 + §6）
- `memoryhub_mcp/` 只留一份，工具注册：`health/write_event/write_preference/write_knowledge(含FACT)/search/get_context/remember/forget/feedback/knowledge_fact_propose`（去重 `propose_facts/decide_facts/list_memories/get_memory` 等低频 → 走 CLI，工具面收敛到最小）。
- `claudecode-integration/`、`opencode-integration/` 内的 MCP 副本标记 deprecated 并软链到新包，验证后删除。

### 3.5 opencode 插件（`memoryhub.plugin.mjs`，`docs/Agent接入设计.md` §6）
- custom tools：`memoryhub_search/get_context/remember`（3 个薄壳，调 CLI）。
- commands：`/memoryhub-context|remember|forget|status|review`。
- skill：`memory-awareness`（引导"用前 search、用后 feedback confirm"）。
- hooks：`tool.execute.after`（累积轨迹）→ `session.status`（冲刷）→ `session.deleted`（兜底）→ `experimental.session.compacting`（注入记忆）。
- 事件构造 `memoryhub_events.mjs`（纯函数可单测），payload 写 `project_root/project_name`（项目隔离）。

### 3.6 自反馈闭环 + project 隔离（`docs/Agent接入设计.md` §14.2,6.4）
- **feedback confirm** 已在核心侧实现（Phase A §4.9.2：→access_count/stability/health）；skill 提示模型使用记忆后调用 `memoryhub feedback <id> confirm`。
- `search`/`context` 已支持 `level`/`project`（Phase E）；CLI/MCP 透传 `--project` 与自动沉淀的 `payload.project_root`。

### 3.7 测试与校验
- `agent-integration/tests/`：CLI 子命令/输出契约、MCP 协议/工具存在、事件构造单测。
- 契约表文档化为 `agent-integration/docs/CONTRACT.md`（来源 `docs/Agent接入设计.md` §14），取代散落各处的手工表。

---

## 4. 落地顺序（建议）

| 步骤 | 内容 | 验收 |
|---|---|---|
| H1 | 建 `agent-integration/` 骨架 + pyproject + 统一 client | client 覆盖全 REST |
| H2 | `memoryhub_cli`：search/context/remember/forget/list/get/status + `--json/--compact/--quiet` | CLI 全链路可用 |
| H3 | 唯一 MCP 包（知识面含 FACT）+ claudecode/opencode 副本软链 | 3 份拷贝收成 1 份 |
| H4 | opencode 插件（3 custom tools + commands + skill + hooks） | `/memoryhub-*` 与自动沉淀可用 |
| H5 | 补全 CLI feedback/provenance/projection/update/knowledge fact/export/import/service | 全命令面 |
| H6 | CONTRACT.md 文档化 + 全量回归 + 契约测试 | 文档零漂移 |

## 5. 涉及文件

| 路径 | 说明 |
|---|---|
| `agent-integration/**`（新建） | 统一 client/CLI/MCP/plugin |
| `pyproject.toml` | 加 `[project.scripts] memoryhub` |
| `opencode-integration/`、`claudecode-integration/` | MCP 副本软链→新包，验证后删除 |
| `docs/Agent接入设计.md` | 已是权威（§14），如有出入以此为准 |
| `docs/REFACTOR_PLAN_V2.md` §4.9 | 核心侧 Agent 面向设计 |

## 6. 验证

```
/d/Anaconda/envs/mhub311/python.exe -m pytest -q agent-integration/tests tests/test_api_acceptance.py tests/test_memory_v2_api.py
# 手工：memoryhub search "<query>"、memoryhub provenance <id> line、memoryhub remember "X" --type knowledge:fact
```

## 7. 不做（超出 H 范围）

- 前端 Qt 桌面端接入（那是另一个工作线）。
