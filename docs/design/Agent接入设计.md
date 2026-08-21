# MemoryHub Agent 接入重构设计（opencode 双模式：Plugin + CLI）

> 本文档是 **MemoryHub ↔ opencode 接入方案的重构设计**，目标是把当前"能用但不够好"的接入升级为
> 更全面、更多样、更符合工程实际的接入体系。
>
> - **两个交付形态**：① 一体化 **Plugin**（custom tools + commands + skills + hooks，MCP 作为可选标准接口）；
>   ② **CLI**（零加载成本、按需调用、省 token）。
> - **设计原则**：不被现状束缚，对不合理处大胆改进；**以 opencode 官方能力为准**（本文档依据
>   `md/` 下 opencode 开发者文档的 `plugins / skills / commands / mcp-servers / custom-tools /
>   tools / config / agents` 八篇校准）；所有能力映射到真实代码/接口；两条链路共享同一份记忆与同一套配置。
> - **代码基线**：`main` @ `8c04b4d`（opencode MCP 实际已 14 工具，文档仍写 12，见 §1 诊断）。
> - **与核心重构同步（2026-08-18 更新）**：核心记忆模块重构（`docs/refactor/REFACTOR_PLAN_V2.md`）
>   对本接入设计产生以下影响——**统一 API 契约**取代旧工具/方法表（§14）；**事实记忆并入知识**
>   （`KnowledgeType.FACT`，`propose_facts/decide_facts` 并入知识面）；**记忆分层**（short/mid/long）
>   暴露为检索/上下文可过滤维度；**自反馈闭环**与**艾宾浩斯遗忘曲线**成为"记忆越用越懂"的引擎
>   （§6.4、§14.4）。凡与 §14 冲突的旧表述以 §14 为准。
> - 本文档是**设计稿**（标注【建议】【规划】），落地后按 §12 迁移清单执行。

---

## 目录

1. [现状诊断：当前接入有哪些不合理](#1-现状诊断当前接入有哪些不合理)
2. [opencode 官方能力校准：能用的原生机制](#2-opencode-官方能力校准能用的原生机制)
3. [设计目标与原则](#3-设计目标与原则)
4. [总体架构](#4-总体架构)
5. [共享基础：统一客户端 + 单一 MCP 包](#5-共享基础统一客户端--单一-mcp-包)
6. [模式 A：一体化 Plugin（custom tools + commands + skills + hooks）](#6-模式-a一体化-plugincustom-tools--commands--skills--hooks)
7. [模式 B：memoryhub CLI（省 token 的按需接入）](#7-模式-bmemoryhub-cli省-token-的按需接入)
8. [配置体系](#8-配置体系)
9. [安全、噪声与隐私控制](#9-安全噪声与隐私控制)
10. [两个模式的协作关系与取舍](#10-两个模式的协作关系与取舍)
11. [交互模式（Profile）与切换机制：默认 Plugin，可切换](#11-交互模式profile与切换机制默认-plugin可切换)
12. [落地路线与迁移清单](#12-落地路线与迁移清单)
13. [与现状的对照表](#13-与现状的对照表)
14. [与核心重构 V2 的同步：统一 API 契约](#14-与核心重构-v2-的同步统一-api-契约)

---

## 1. 现状诊断：当前接入有哪些不合理

### 1.1 工具面：14 个 MCP 工具全量进上下文，token 浪费严重

`opencode-integration/mcp-server/memoryhub_mcp/tools.py` 实际注册了 **14 个工具**
（`health / search / get_context / write_event / write_preference / write_knowledge /
propose_facts / decide_facts / forget / list_memories / get_memory / feedback /
list_conflicts / resolve_conflict`）。每个工具名 + 中英双语 description + inputSchema
（含枚举、默认值、说明）会**常驻每次会话的上下文**。

问题：
- `memoryhub_health`（连通性探测）占一个工具位，却是纯运维行为，LLM 几乎不该碰；
- `list_memories / get_memory / feedback / list_conflicts / resolve_conflict /
  write_event / decide_facts` 都是低频管理操作，schema 却和其它工具一样昂贵；
- 文档（`docs/design/产品形态与使用方案.md`、`opencode-integration/docs/INTEGRATION.md`）仍写 **12 工具**，
  与代码事实漂移（8c04b4d 新增 propose/decide 两个事实工具后为 14）。
- **官方文档自己都警告**："MCP servers add to your context, so you want to be careful
  with which ones you enable"（`md/mcp-servers.md`）——验证了"常驻 MCP 工具"是 token 大头。

> **结论**：工具"大一统常驻"是最大的 token 浪费点，也是接入可维护性最差处。

### 1.2 代码：同一套 MCP server 存在 3 份拷贝

`memoryhub_mcp`（`server.py / client.py / config.py / schemas_bridge.py / tools.py`）
在仓库里有 **3 份逐字节相近的拷贝**：

```
opencode-integration/mcp-server/memoryhub_mcp/
claudecode-integration/mcp-server/memoryhub_mcp/
claudecode-integration/plugin/memoryhub/mcp-server/memoryhub_mcp/
```

任何接口/契约改动都要同步三处，漏一处就是静默失配。

### 1.3 自动沉淀：opencode 侧比 claudecode 侧弱一档

- claudecode 插件是**按回合**沉淀：`PostToolBatch` 累积（`record.py --accumulate`）→
  `Stop` 每回合冲刷（`--flush-turn`）→ `SessionEnd` 兜底（`--flush-all`），
  带文件锁、去重、agent 过滤、MemoryEvent 契约校验；
- opencode 插件（`memoryhub.plugin.mjs`）只在 `session.idle` 时**整会话一次性** POST，
  粒度粗、失败即整会话丢失、没有回退清理，且 `session.idle` 语义本身已标记为 deprecated
  （官方建议改用 `session.status`）。

### 1.4 读路径：opencode 侧没有上下文注入

claudecode 有 `context.py`（`UserPromptSubmit` hook，把检索结果注入 prompt，默认关）；
opencode 插件**没有任何**上下文注入机制——记忆的"被动想起"只能依赖 LLM 主动去调 MCP 工具。
而 opencode 的 **command 支持 `!`shell 输出注入**（`md/commands.md`），天然可以做到
"用户一发 prompt 就内联记忆上下文"，这个能力完全没被利用。

### 1.5 无 commands / skills：用户没有直接入口

opencode 有 **commands**（`.opencode/commands/*.md`，用户 `/` 可触发）和 **skills**
（`.opencode/skills/*/SKILL.md`，agent 按需发现）两套成熟机制，当前接入一个都没用。
用户想"记住/忘掉/查看记忆"，只能间接让 Agent 调工具。

### 1.6 无自反馈闭环

`agent_api.py` 的 `step` 接口已有 `used_memory_ids` 概念（检索命中→使用→上报），但接入层
没有把"LLM 使用了哪条记忆"回灌成 `feedback confirm`。记忆用过的次数无法反哺置信度/健康度。

### 1.7 无 CLI；无导出/导入；无服务管理入口

`docs/design/产品形态与使用方案.md` P1 清单里有 `memoryhub-cli`（start/stop/status/reset/inspect），
但仓库 `pyproject.toml` 无 `console_scripts`，`integrations/memoryhub_client.py` 只覆盖 3 个方法。
Agent 之外（运维脚本、跨机迁移、无插件环境）没有统一入口。

### 1.8 噪声与隐私：自动沉淀无工具白名单/采样策略

自动沉淀把**所有**工具调用结果（默认截断 4000 字符）写入事件。`read`、`grep`、`shell` 这类
高频且可能含敏感内容的工具与 `memoryhub` 工具一视同仁（只有 memoryhub 自身被过滤）。
噪声大、敏感内容暴露面大。

---

## 2. opencode 官方能力校准：能用的原生机制

> 本节依据 `md/` 下的官方文档，列出设计里会**直接借用**的原生机制，避免"自己发明轮子"。

| 机制 | 出处 | 对本设计的意义 |
|---|---|---|
| **Commands**：`.opencode/commands/*.md`，用户 `/` 触发；支持 `$ARGUMENTS`、`!`命令注入、`@file`、`agent`/`model`/`subtask` | `md/commands.md` | `/memoryhub remember` 等**用户命令**应做成 command，而非 skill |
| **Skills**：`.opencode/skills/*/SKILL.md`，agent 经 `skill` 工具按需加载；frontmatter 只认 `name`/`description`/`license`/`compatibility`/`metadata`；`permission.skill` 可 allow/ask/deny | `md/skills.md` | **被动"记忆意识"指令**做成 skill；不把用户命令塞进 skill |
| **Custom tools**：`.opencode/tools/*.ts` 或插件 `tool` 导出；`tool()` + Zod schema；execute 可 shell 出去调任何语言；工具名 = 文件名 | `md/custom-tools.md` | **在 opencode 内用原生 custom tool 取代常驻 MCP 进程**（更轻、无协议开销），thin wrapper 调 CLI |
| **typed hooks**：`tool.execute.before` / `tool.execute.after`（`input.tool`/`output.args`/`output.output`）、`shell.env`、`experimental.session.compacting` | `md/plugins.md` | `tool.execute.after` 是**最佳工具轨迹累积点**（直接拿到工具名+入参+输出）；compacting hook 可在压缩时注入记忆 |
| **events**：`session.status`（推荐）、`session.deleted`、`message.part.updated`、`permission.replied`、`file.edited` | `md/plugins.md` | 冲刷/兜底用 `session.status`+`session.deleted`，替代 deprecated 的 `session.idle` |
| **MCP 工具全局/按 agent 启停**：`tools: {"memoryhub_*": false}`、`agent.<name>.permission`、`permission.mymcp_*` | `md/mcp-servers.md`、`md/tools.md`、`md/agents.md` | 用**官方 `tools`/`permission` glob**控制工具可见性，替代自研 `mcpTier` |
| **config 变量替换**：`{env:VAR}`、`{file:path}`；config 多源合并（global → project → `.opencode/` → inline） | `md/config.md` | MCP `environment` 可直接 `{env:MEMORYHUB_API_URL}`；插件/CLI 读 env + 配置文件 |
| **bash 权限可按命令 glob**：`permission.bash: {"memoryhub *": "allow"}` | `md/agents.md` | 放行 `memoryhub` CLI 调用，无需整包开 `bash: allow` |

**两条修正（对初稿的纠偏）**：

1. **用户可见的 `/memoryhub xxx` 是 command，不是 skill。** 初稿把它们写成 skill，违背 opencode 的机制（skill 是 agent 按 description 自动发现的，不是用户 slash 命令）。skill frontmatter 也只认 5 个字段，初稿里 Claude Code 风格的 `disable-model-invocation`/`argument-hint` 会被 opencode 直接忽略。
2. **MCP 不是 opencode 内的最优工具载体。** opencode 原生 custom tool（`tool` 导出）无独立进程、无 MCP 协议层、可 shell 出去调 CLI，且同样能被 `tools`/`permission` 原生控制。MCP server 保留为**跨 Agent 的标准接口**（Claude Code / 远程 MCP 客户端），opencode 内默认走 custom tool + CLI。

---

## 3. 设计目标与原则

| 目标 | 说明 |
|---|---|
| **省 token** | 默认零常驻工具 schema；custom tool 面最小；读路径靠 command 的 `!` 注入与 CLI 按需触发 |
| **一次接入全能力** | 一个 Plugin 内含 custom tools + commands + skills + hooks；一个 CLI 覆盖全 REST 面 |
| **单一事实源** | 一套共享 client + 一个 MCP 包 + 一份契约映射表，消灭 3 份拷贝 |
| **原生优先** | 能用 opencode 原生机制（command/skill/custom tool/typed hook/glob 启停）就不自研 |
| **工程化** | 类型化配置、单测、`--json` 输出、shell 补全、日志分级、失败软着陆 |
| **安全内建** | 工具白名单/去敏、采样、按项目隔离、敏感内容不落地 |
| **可迁移** | 导出/导入、服务管理，满足产品文档 P1 的 `memoryhub-cli` 规划 |

**总原则**：

1. **CLI 是记忆能力的"母语"，Plugin 是它的便捷层。** 所有能力先落 CLI（`memoryhub` 子命令）；
   plugin 的 custom tools / commands 都是 CLI 的**薄壳**（shell 出去调 CLI），不重复实现业务逻辑。
2. **按需加载，不做常驻堆料。** 低频/管理型能力移出 LLM 工具空间，留给 CLI 与 slash 命令；
   工具可见性用 opencode 原生 `tools`/`permission` glob 控制。
3. **自动沉淀对齐 claudecode 的成熟模型**（累积→冲刷→兜底），用 opencode 原生
   `tool.execute.after` + `session.status` + `session.deleted` 实现。
4. **插件不重复实现业务。** 插件里的脚本一律调共享 client 或 CLI，杜绝第三份实现。

---

## 4. 总体架构

```
┌────────────────────────── opencode 会话（Bun 运行时） ─────────────────────────┐
│                                                                                │
│   用户 ── /memoryhub remember ··commands(/ 触发) ··/memoryhub search            │
│                    │                                   │                       │
│                    ▼                                   ▼                       │
│   Plugin(memoryhub)  plugin.js ── 事件hooks(自动沉淀) ─┐     CLI 动态注入        │
│      ├─ tools/   custom tools (memoryhub_search …) ────┼──┐   ┌──────────┐     │
│      │           → 薄壳 shell 调 CLI                     │  └──▶│ memoryhub │──┐ │
│      ├─ commands/*.md  (/memoryhub remember|forget|…) ──┼─────▶│   CLI    │  │ │
│      ├─ skills/memory-awareness/  (agent 被动想起) ─────┼─────▶│  (可选)   │  │ │
│      └─ hooks:                                          │      └──────────┘  │ │
│          tool.execute.after → accumulate                │            ▲       │ │
│          session.status(idle) → flush-turn              └──── HTTP ─┘       │ │
│          session.deleted → drain                        │                    │ │
│          experimental.session.compacting → 注入记忆      │                    │ │
│                                                                              │ │
│   LLM ── Bash(memoryhub …) / custom tools ── 只按需召唤 CLI ──────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
                                    │  (MCP server 仅作跨 Agent 标准接口，opencode 内默认不用)
                                    ▼
                   ┌──────────────────────────────────────────────────┐
                   │  MemoryHub REST（FastAPI 127.0.0.1:8099）         │
                   │  /api/memory/search|context|events|memories/     │
                   │  |forget|facts|conflicts|feedback|lifecycle      │
                   │  |safety|system                                   │
                   └──────────────────────────────────────────────────┘
                   ┌──────────────────────────────────────────────────┐
                   │  共享 Python 包 agent-integration/                 │
                   │  memoryhub_client/（全 REST 方法）                  │
                   │  memoryhub_mcp/（唯一一份，跨 Agent 标准）           │
                   │  memoryhub_cli/（CLI，被 Plugin 薄壳调用）           │
                   └──────────────────────────────────────────────────┘

   Plugin、CLI、MCP 共享：同一份记忆、同一套 MEMORYHUB_* 配置、同一个 REST 服务。
```

- **模式 A（Plugin）**：custom tools（读/写薄壳）+ commands（用户命令）+ skill（被动想起）
  + hooks（自动沉淀、压缩注入）。适合"零思考，开箱即用"的交互式场景。
- **模式 B（CLI）**：任何 Agent / 脚本 / 运维都可用 `memoryhub <子命令>`，工具 schema 不进上下文，
  只按需进上下文。适合"能省则省"的 token 敏感场景，也是模式 A 中 custom tools / commands 的底层执行器。

---

## 5. 共享基础：统一客户端 + 单一 MCP 包

### 5.1 目录收敛：废弃 3 份拷贝，收敛到 `agent-integration/`

【建议】新建 `agent-integration/`（替代现 `opencode-integration/` + `claudecode-integration/`
中重复的 MCP 部分），目录如下：

```
agent-integration/
├── pyproject.toml               # 本包构建元数据 + console_scripts 入口
├── memoryhub_client/
│   └── client.py                # 全 REST 方法客户端（基于 integrations/memoryhub_client.py 扩充）
├── memoryhub_mcp/               # 【唯一一份】MCP stdio server（跨 Agent 标准接口）
│   ├── __init__.py / __main__.py
│   ├── config.py                # 类型化配置（env 优先，config 文件兜底）
│   ├── server.py                # MCP 协议层（stdio JSON-RPC）
│   ├── tools.py                 # 工具注册（14 工具，契约表见 CONTRACT.md）
│   └── schemas_bridge.py        # 复用 memoryhub Pydantic 契约校验
├── memoryhub_cli/
│   ├── __init__.py
│   ├── cli.py                   # 子命令入口（本 CLI 是 Plugin 薄壳的唯一逻辑来源）
│   ├── format.py                # 人类可读 / --json / --compact / --quiet 四种输出
│   └── config.py                # 配置解析（env → .memoryhub/config.json → 全局 → 默认）
├── plugin/opencode/             # opencode 插件包（见 §6）
│   ├── memoryhub.plugin.mjs     # 插件工厂：注册 custom tools + hooks
│   ├── memoryhub_events.mjs     # 事件→MemoryEvent 构造（纯函数，供单测）
│   ├── commands/                # /memoryhub-* 命令（安装时复制到 .opencode/commands/）
│   ├── skills/                  # memory-awareness（安装时复制到 .opencode/skills/）
│   └── tools/                   # custom tools 薄壳（安装时复制到 .opencode/tools/）
├── tests/
│   ├── test_cli.py              # CLI 子命令/输出/契约
│   ├── test_mcp_server.py       # MCP 协议层 + 工具存在性
│   └── test_plugin_events.mjs   # 事件构造单测
└── examples/
    ├── opencode.json            # 接入配置示例（mcp 可选段 + permission/tools glob）
    └── memoryhub.config.json    # 项目级配置示例
```

> 兼容策略：`opencode-integration/`、`claudecode-integration/` 中重复的 `mcp-server/`
> 标记为 deprecated 并做软链接/薄 wrapper 指向 `agent-integration/memoryhub_mcp/`，
> 验证通过后删除副本（见 §12 迁移清单）。

### 5.2 统一客户端：`memoryhub_client/client.py`

在现有 `integrations/memoryhub_client.py`（仅 `health/get_context/write_events` 3 方法）基础上
扩充为**覆盖全部 REST 面**：

| 方法 | REST 端点 | 用途 |
|---|---|---|
| `health()` | `GET /api/memory/health` | 连通性 |
| `search()` | `POST /api/memory/search` | 混合检索 |
| `get_context()` | `POST /api/memory/context` | 可注入上下文文本 |
| `write_events()` | `POST /api/memory/events` | 批量写入事件 |
| `write_preference()` | `POST /api/memory/memories/preference` | 显式写偏好 |
| `write_knowledge()` | `POST /api/memory/memories/knowledge` | 显式写知识（`knowledge_type` 支持 workflow/case/template/**fact**） |
| `propose_knowledge_fact()` | `POST /api/memory/knowledge` （`knowledge_type=fact`） | 三元组知识候选（替代 `propose_facts`） |
| `decide_knowledge_fact()` | `POST /api/memory/knowledge/{id}/resolve` | 三元组知识裁决（替代 `decide_facts`） |
| `forget()` / `forget_preview()` | `POST /api/memory/forget` `/forget/preview` | 遗忘（艾宾浩斯健康度参与优先级） |
| `list_preferences()` 等 | `GET /api/memory/preferences|knowledge`（facts 兼容转发） | 列表（返回含 `memory_level`） |
| `get_preference()` 等 | `GET /api/memory/{type}/{id}` | 详情 |
| `update_memory()` | `PUT /api/memory/{type}/{id}` | 统一记忆更新（偏好/知识/FACT） |
| `feedback()` | `POST /api/memory/feedback` | 反馈强化（confirm/reject → 置信度/健康度，艾宾浩斯复习） |
| `provenance()` | `GET /api/memory/v2/memories/{id}/lineage|evidence|audit` | 溯源（新增，v2） |
| `list_projections()` / `replay_projection()` | `GET /api/memory/v2/projections` `/replay` | 投影恢复（新增，v2） |
| `list_conflicts()` / `resolve_conflict()` | `GET/POST /api/memory/conflicts...` | 冲突 |
| `export()` / `import_()` | 组合多个 GET + `write_events`/`memories/*` | 导出/导入 |
| `system_status()` | `GET /api/memory/system/status` | 健康/状态 |

> 注：§14 为统一契约权威；`search`/`context` 均支持 `level`（short/mid/long）与 `project` 过滤参数。

所有方法统一：超时、`user_id` 默认、`HTTPError → MemoryHubError`（含 `status_code /
code / safety_action / audit_id`），与 MCP 工具 `handle_tool_error` 的语义对齐。

### 5.3 单一 MCP 包（跨 Agent 标准接口）

`memoryhub_mcp/` 只保留一份，契约映射表（工具 ↔ REST）统一维护在 `agent-integration/docs/CONTRACT.md`
（或 `README`），取代散落在三处 docs 里的手工表。

**在 opencode 内**，MCP server 默认**不启用**（由 opencode 原生 custom tool + CLI 承担，见 §6）；
若用户仍想用 MCP（例如与 Claude Code 行为保持一致、或给远程 MCP 客户端复用），在 `opencode.json`
的 `mcp.memoryhub` 引用同一份包即可，工具可见性用官方 `tools`/`permission` glob 控制（§6.5）。

---

## 6. 模式 A：一体化 Plugin（custom tools + commands + skills + hooks）

> 安装器 `scripts/install_opencode_plugin.mjs`（替代现有 `install_plugin.mjs`）一次性把下列
> 文件复制到对应目录：`memoryhub.plugin.mjs → .opencode/plugins/`、
> `commands/*.md → .opencode/commands/`、`skills/* → .opencode/skills/`、
> `tools/*.ts → .opencode/tools/`。opencode 按官方目录自动加载。

### 6.1 Custom tools：opencode 内的原生记忆工具面（默认 3 个薄壳）

用插件 `tool` 导出（或 `.opencode/tools/memoryhub.ts`）注册**最少的原生工具**，每个都是
CLI 的薄壳（`Bun.$` 调 `memoryhub <子命令>`），不重复实现业务：

```ts
// .opencode/tools/memoryhub.ts —— 文件名即工具名前缀（memoryhub_search 等）
import { tool } from "@opencode-ai/plugin"

export const search = tool({
  description: "混合检索 MemoryHub 记忆（偏好/知识/事实）。问题依赖用户持久偏好或过去工作流时先调用。",
  args: {
    query: tool.schema.string().describe("检索查询文本"),
    top_k: tool.schema.number().optional().describe("返回条数，默认 5"),
    memory_types: tool.schema.array(tool.schema.string()).optional(),
  },
  async execute(args, ctx) {
    // 薄壳：调 CLI，输出直接给 LLM；超时 15s；失败返回稳定错误文本
    const out = await Bun.$`memoryhub search --json ${args.query}`.nothrow().quiet().text()
    return formatToolOutput(out)
  },
})
```

| 工具 | 用途 | 薄壳命令 | 备注 |
|---|---|---|---|
| `memoryhub_search` | 混合检索 | `memoryhub search --json "<query>"` | 读主路径，最常用 |
| `memoryhub_get_context` | 取可注入文本 | `memoryhub context --json "<query>"` | 与 command 注入互补 |
| `memoryhub_write_preference` | 显式写偏好 | `memoryhub remember "<text>" --type preference` | 用户显式要求才用 |

> 写知识 / 事实 / 遗忘 / 管理等**低频操作一律走 CLI**（§7），不进工具面；工具面默认只 3 个，
> 比现在的 14 个 MCP 工具每回合省下大量 schema token。工具**可见性由 opencode 原生控制**
> （§6.5），想完全不要工具也可以：`tools: {"memoryhub_*": false}`。

### 6.2 Commands：用户可直接触发的 `/memoryhub-*` 命令

命令放 `.opencode/commands/memoryhub-<name>.md`，文件名即 `/memoryhub-<name>`。用 command
的 `!`bash 注入把 CLI 输出内联进 prompt —— 读路径的"被动想起"就是这里实现的：

```markdown
<!-- .opencode/commands/memoryhub-context.md -->
---
description: 检索并注入与当前问题相关的 MemoryHub 记忆上下文
agent: build
---

以下是 MemoryHub 检索到的与用户偏好/过去工作流相关的记忆，先读再作答，引用时注明来源：

!`memoryhub context "$ARGUMENTS" --max-chars 4000`
```

| 命令 | 文件 | 用途 | 关键特性 |
|---|---|---|---|
| `/memoryhub-context` | `memoryhub-context.md` | 注入与问题相关的记忆上下文 | `!` 内联 CLI 输出 |
| `/memoryhub-remember` | `memoryhub-remember.md` | 显式记住一句话 | `$ARGUMENTS` 透传 CLI |
| `/memoryhub-forget` | `memoryhub-forget.md` | 精准遗忘（先 `--preview`） | `$ARGUMENTS` + CLI 预览 |
| `/memoryhub-status` | `memoryhub-status.md` | 服务健康 + 记忆统计 | `!` 内联 |
| `/memoryhub-review` | `memoryhub-review.md` | 待裁决的事实候选/冲突清单 | `!` 内联 + 引导后续裁决 |

> opencode 的 command 也支持 `agent`/`model`/`subtask`，可用 `subtask: true` 把记忆检索
> 放到子代理里执行，不污染主上下文（`md/commands.md`）。

### 6.3 Skill：agent 自动发现的"记忆意识"指令

`skills/memory-awareness/SKILL.md`（注意 frontmatter **只认 5 个字段**，名称必须匹配目录名）：

```markdown
---
name: memory-awareness
description: 记忆使用准则。当问题可能依赖用户持久偏好、过去可复用的工作流或事实知识时使用。
license: MIT
metadata:
  audience: agent
---

## 记忆使用准则
1. 问题依赖持久偏好/工作流/事实时，先取记忆再作答：
   - 运行 `memoryhub context "<问题>"` 或用 custom tool `memoryhub_search`；
   - 命中后把相关记忆融入回答，并注明来源（如"根据你之前的偏好……"）。
2. 用户明确说"记住…/以后…"时：先跑 `memoryhub remember "<内容>"`（或 `/memoryhub-remember`），
   把返回的安全处置结果（ALLOW/MASK/REVIEW/REJECT）原样转述，不改写。
3. 用户说"忘掉…"时：先跑 `memoryhub forget "<指令>" --preview` 预览再确认。
4. 使用过某条记忆后：跑 `memoryhub feedback <id> confirm`，帮助记忆强化。
5. 若 MemoryHub 不可达，正常作答，不要反复重试或编造记忆。
```

- skill 由 agent 按 description 自动加载（`md/skills.md`），可用 `permission.skill` 配置
  allow/ask/deny（如 `"memory-awareness": "allow"`）。
- **它只承载"怎么用记忆"的准则**；具体动作都落在 CLI/custom tools/commands，符合"按需加载"。

### 6.4 Hooks：事件驱动的自动沉淀（对齐 claudecode 成熟模型）

用 opencode **typed hooks + events** 实现三段式沉淀，比 claudecode 的
`PostToolBatch → Stop → SessionEnd` 更贴 opencode 原生事件：

| opencode 机制 | 动作 | 对应 claudecode | 说明 |
|---|---|---|---|
| `tool.execute.after`（typed hook） | **accumulate** | `PostToolBatch --accumulate` | 直接拿到 `input.tool`/`args`/`output.output`，追加到 `内存/每会话.pending.jsonl`（文件锁；工具白名单过滤；输出截断，见 §9） |
| `session.status` → `idle` | **flush-turn** | `Stop --flush-turn` | 读 pending，构造 `MemoryEvent(agent_response)` POST，清理文件 |
| `session.deleted` | **drain** | `SessionEnd --flush-all` | 兜底清空残留 pending，按 `agent_summary` 上报 |
| `experimental.session.compacting` | **注入记忆** | —（新能力） | 压缩会话前，注入与当前会话相关的 MemoryHub 记忆，让持久记忆熬过摘要；或注入"本会话应记住但还没沉淀的要点" |

项目级上下文（opencode 独有优势）：插件 ctx 提供 `{ project, directory, worktree }`，
构造 `MemoryEvent` 时写入 `payload.project_root / payload.project_name`（REST 检索后续可加
`project` 过滤，见 §12 落地增强）。

事件构造逻辑放 `memoryhub_events.mjs`（纯函数，不依赖 SDK），保证可单测——
这是对现有 `memoryhub.plugin.mjs` + `memoryhub_event_builder.mjs` 结构的有意保留。

### 6.5 工具/命令可见性的原生控制（取代自研 mcpTier）

不发明开关，直接用 opencode 官方 `tools` / `permission`：

```jsonc
// opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "tools": {
    "memoryhub_*": false          // 默认不把任何 memoryhub 工具塞进上下文（纯 CLI/命令模式）
  },
  "permission": {
    "bash": { "memoryhub *": "allow", "*": "ask" },   // 放行 memoryhub CLI，其余 bash 仍要问
    "skill": { "memory-awareness": "allow" }
  },
  "mcp": {                        // 可选：需要跨 Agent 一致的 MCP 接口时启用
    "memoryhub": {
      "type": "local",
      "command": ["python", "-m", "memoryhub_mcp"],
      "cwd": "agent-integration",
      "environment": { "MEMORYHUB_API_URL": "{env:MEMORYHUB_API_URL}", "MEMORYHUB_USER_ID": "{env:MEMORYHUB_USER_ID}" },
      "enabled": false             // 默认关；打开后工具名前缀 memoryhub_*
    }
  }
}
```

- 想要 MCP 工具常驻：`tools: {"memoryhub_*": true}`（或删掉 glob），并在 `mcp.enabled: true`。
- 想只给 build agent 开：`agent: { build: { permission: { "memoryhub_search": "allow" } } }`。
- glob 是官方能力（`md/mcp-servers.md`），可比自研 `mcpTier` 更精细且零维护。

---

## 7. 模式 B：`memoryhub` CLI（省 token 的按需接入）

### 7.1 为什么 CLI 更省 token

- **工具 schema 不进上下文**：14 个 MCP 工具名/描述/schema 常驻；CLI 只是 1 个 shell 命令名。
- **按需进上下文**：LLM 用内置 `Bash` 工具 `memoryhub search "…"`（或 command 的 `!` 注入）时，
  才把命令 + 精简输出放进上下文。
- **输出可控**：默认 terse、`--compact` 更小、`--json` 结构化、`--quiet` 只留结果字段。
- **零插件依赖**：任何 Agent（opencode / claude code / 自研）都能直接用；shell 管道、cron、运维脚本通用。

> 估算（同一读操作）：MCP `memoryhub_search` 常驻 schema ≈ 150–300 token/回合；
> CLI `memoryhub search "x"` 只有被调用那一下 ≈ 30–80 token，且 3 个 custom tool × 常驻也远小于 14 个。

### 7.2 命令面（覆盖全 REST）

安装即得 `memoryhub` 命令（`pyproject.toml` 增加 `console_scripts`）：

```
memoryhub [全局选项] <子命令>

全局选项：
  -u, --user <id>        用户 ID（默认 opencode；优先于配置）
      --api-url <url>    REST 地址（默认 http://127.0.0.1:8099）
      --project <dir>    项目上下文（默认取 cwd 的 git root）
      --scene / --task-type   场景/任务过滤
      --timeout <sec>    HTTP 超时
  -j, --json             结构化 JSON 输出
  -c, --compact          精简输出（默认形态，最省 token）
  -q, --quiet            只输出最小结果字段
      --no-color         禁用颜色

子命令：
  检索 / 上下文
    search <query>                    混合检索（--top-k/--memory-types/--min-confidence/--scene）
    context <query>                   取可直接注入 prompt 的上下文文本（--max-chars）
  写入
    remember <text> [--type preference|knowledge:workflow|knowledge:case|knowledge:template|knowledge:fact] [--scene] [--project]
    event <file.jsonl>                批量写入 MemoryEvent（从 stdin 读 "-"）
  更新
    update <memory_id> [--text ...] [--scope ...] [--knowledge-type ...]   统一记忆更新（PUT /{type}/{id}）
  遗忘
    forget <指令|ID> [--preview] [--cascade]    带预览的精准遗忘（艾宾浩斯健康度参与优先级）
  查看
    list [--type all|preference|knowledge] [--level short|mid|long] [--status active|archived|trash|review]
    get <memory_id>                   单条详情（含 memory_level、health）
  溯源 / 投影
    provenance <memory_id> [lineage|evidence|audit]   溯源链/证据/安全审计（v2）
    projection list [--status pending|failed] [--user] ; projection replay <outbox_id...>
  反馈 / 裁决
    feedback <id> confirm|reject|update <text>         confirm → 艾宾浩斯复习强化 + 置信度/健康度刷新
    review [knowledge|conflicts]        待裁决队列（含 FACT 知识冲突）
    decide <proposal_id> commit|reject [--scope global|project]
    resolve <conflict_id> override|merge|coexist|pending [--reason ...]
  知识事实（原事实子命令并入知识）
    knowledge fact propose <triples.json> [--mode user_review|agent_autonomous]
  导出 / 导入
    export [--type all] > memoryhub-backup.jsonl
    import <file.jsonl> [--dry-run]
  服务 / 状态
    status                          健康度 + 记忆统计（偏好/知识/FACT 计数、延迟、安全状态）
    service start|stop|status       本地服务管理（对应 packaging/linux/memoryhub.service）
  其它
    completion [bash|zsh]           生成 shell 补全
    help <子命令>
```

### 7.3 输出契约（token 友好）

默认 `--compact`（人类 + LLM 双友好）：

```
$ memoryhub search "周报格式" -c
[1] pref_8f2a (conf .92) 始终用 Markdown 生成周报
[2] know_09d1 workflow: 项目周报生成流程（5 步，2 工具）
（3 命中，lat 28 ms）
```

`--json`（结构化，供 Agent/脚本二次处理）：

```json
{"results":[{"memory_id":"pref_8f2a","memory_type":"preference","text":"…","confidence":0.92,"score":0.87}],"latency_ms":28,"total_count":3}
```

`--quiet`（管道友好，只出核心字段）：

```
pref_8f2a	preference	0.92	始终用 Markdown 生成周报
```

### 7.4 实现要点

- **复用统一 client**：`memoryhub_cli/cli.py` 直接调 `memoryhub_client/client.py`，不重复写 HTTP。
- **可脚本化**：stdin/stdout 约定明确；`event -` 支持从 stdin 读事件（配合 `jq`/管线）。
- **安全优先**：`forget` 默认先 `--preview` 再确认（非交互 `-y` 跳过）；敏感处置（REVIEW/REJECT）
  原样透出，不静默改写。
- **配置三层**：环境变量 → 项目 `.memoryhub/config.json` → 全局 `~/.config/memoryhub/config.json`。

---

## 8. 配置体系

### 8.1 三层优先级

1. **显式传参**（CLI 全局选项）
2. **进程环境变量**（`MEMORYHUB_API_URL / USER_ID / TOP_K / SCENE / TASK_TYPE / AUTO_RECORD / …`）
   —— opencode 官方支持 `{env:VAR}` 替换，且插件/命令在进程内天然继承，因此 env 是一等公民；
3. **配置文件**
   - 项目级：`<project>/.memoryhub/config.json`（插件用 `ctx.directory`/`ctx.worktree` 定位）
   - 全局：`~/.config/memoryhub/config.json`
4. **内置默认值**

### 8.2 示例

```jsonc
// <project>/.memoryhub/config.json 示例
{
  "apiUrl": "http://127.0.0.1:8099",
  "userId": "opencode",
  "scene": "code",
  "taskType": "coding_task",
  "topK": 5,
  "minConfidence": 0.5,
  "context": { "maxChars": 4000, "injectOnCommand": true },
  "autoRecord": {
    "enabled": true,
    "toolAllow": ["read","edit","write","bash","grep","glob","webfetch"],
    "toolResultMaxChars": 1000,
    "recordSummaries": true,
    "recordProjects": true
  }
}
```

> **为什么插件不用"options 对象"传参**：opencode 的 `plugin` 配置是**字符串数组**
> （`"plugin": ["@my-org/custom-plugin"]`，见 `md/plugins.md`），插件工厂只收 `ctx`，
> 没有官方 options 机制。因此插件选项走 **env + 配置文件** 两路（env 最省事、config 可随仓库提交），
> 由插件与 CLI 共用同一套 `config.py` 解析逻辑，行为一致。

---

## 9. 安全、噪声与隐私控制

| 控制 | 实现 | 说明 |
|---|---|---|
| **写入安全门禁** | 沿用 REST `POST /api/memory/events` 的内核安全门禁（ALLOW/MASK/REVIEW/REJECT） | 接入层不改写，原样透出处置结果 |
| **工具白名单/黑名单** | 插件 hooks `autoRecord.toolAllow/deny`（按 opencode 内置工具名 `read/edit/write/bash/grep/glob/webfetch`，见 `md/tools.md`） | 只沉淀有价值的工具轨迹，屏蔽 `memoryhub*`（防自我循环）、敏感/高频工具 |
| **输出截断与采样** | `toolResultMaxChars`（默认 1000，比现在 4000 更收敛）+ 可选"仅记录工具名+文本、不记录输出"（summary-only） | 降噪 + 缩小敏感内容暴露面 |
| **项目隔离** | `payload.project_root/project_name` 写入事件；REST 检索支持 `project` 过滤 | opencode 多项目互不串味 |
| **预览确认** | CLI `forget --preview`、`import --dry-run`；command 的 forget 先预览再确认 | 破坏性操作先看后做 |
| **失败软着陆** | 所有 hooks/CLI 失败只记日志（`client.app.log`），绝不影响 Agent 会话 | 与现状一致并强化 |
| **导出脱敏** | `export` 默认跳过 REVIEW 隔离区与 REJECT 内容；`--full` 才导出全部 | 迁移不夹带敏感原文 |
| **bash 权限收敛** | `permission.bash: {"memoryhub *": "allow", "*": "ask"}` | 只放行记忆 CLI，其余 shell 保持人工确认（`md/agents.md` 原生支持） |

---

## 10. 两个模式的协作关系与取舍

| 场景 | 推荐模式 |
|---|---|
| 交互式 Agent 会话，想要"零思考自动沉淀 + 记忆越用越懂" | **Plugin**（hooks 自动沉淀 + commands + custom tools + skill） |
| token 预算紧张 / 大量只读检索 | **CLI**（`tools: {"memoryhub_*": false}`，`/memoryhub-context` 或 `memoryhub context` 按需注入） |
| 运维 / 脚本 / cron / 跨机迁移 | **CLI**（`service/export/import/status`） |
| 无插件运行时（自研 Agent、远程 shell） | **CLI** |
| 需要与 Claude Code 行为完全一致的 MCP 工具面 | **Plugin + MCP**（`mcp.enabled: true`，`tools: {"memoryhub_*": true}`） |
| 高安全审计场景 | **CLI + Plugin**，`context.injectOnCommand:false`、`autoRecord.toolAllow` 收紧、`--preview` 全开 |

两者不是二选一，而是**同一能力的两个调用面**：CLI 是底层执行器（custom tools / commands 都调它），
Plugin 是便捷层（hooks 自动沉淀 + 用户命令 + 被动想起）。建议默认 **Plugin 全功能 + 工具面最小**，
token 敏感项目把 `tools.memoryhub_*` 关掉并靠 CLI/command 读取。**默认与切换机制见 §11。**

---

## 11. 交互模式（Profile）与切换机制：默认 Plugin，可切换

### 11.1 一个前提修正：不是"二选一"，而是"一套引擎上的开关组合"

> 设想的合理处：**默认 plugin、前端可切换、配置可指定**——这三条都成立，且与产品形态一致
> （Qt 控制台本就是"运维/调参"入口，见 `docs/design/产品形态与使用方案.md` §5.3）。
> 需要修正的只有前提本身："两套模式，实现必须选一套"。

- **CLI 是引擎，Plugin 的 custom tools / commands / hooks 底层全在调 CLI**（§6）。二者不是两条
  平行实现，**实现上不存在"选一套"**——真去二选一，会造出两套并行调用链，重蹈"3 份 MCP 拷贝"覆辙。
- 真正可切换的是**交互档案（Profile）**：在同一套安装里，决定哪些**表层能力**被激活——
  custom tools 是否注册、自动沉淀 hooks 是否开启、MCP 是否启用、commands/skills 是否常驻。

### 11.2 两个 Profile 的定义

| Profile | 默认 | 激活的表层 | 语义 |
|---|---|---|---|
| `plugin`（协助模式） | ✅ 默认 | custom tools(3) + 自动沉淀 hooks + commands/skills + 可选 MCP | 开箱即用、记忆越用越懂；内置"精益默认"（工具最少、hooks 过滤严格），token 可控 |
| `cli`（极简模式） | — | 不注册记忆工具、关闭自动沉淀（或仅 summary）、只留 commands（按需）+ CLI | 一切显式、token 最低 |

关键点：

- **CLI 在两种 profile 下都始终安装**——plugin 的工具/命令只是它的薄壳；`cli` 只是不再主动把
  记忆能力端到 LLM 面前。
- commands/skills 是文件、常驻但**零 idle 成本**（用户不触发、agent 不按需加载就不占上下文），
  所以两个 profile 都保留；`cli` 下它们变成"完全由用户/按需触发"。

### 11.3 切换层级（优先级高 → 低）

1. **Agent 级**：opencode 配置的 `tools` / `permission` glob（`memoryhub_*`）——原生机制、最细粒度；
2. **项目级**：`.memoryhub/config.json` 的 `mode`（随仓库走、可 review、可提交）；
3. **设备/全局默认**：`~/.config/memoryhub/config.json` 的 `mode` —— **这是 Qt 桌面控制台
   "接入方式"设置写入的位置**；
4. **内置默认**：`plugin`。

```jsonc
// <project>/.memoryhub/config.json —— 项目级覆盖（优先级高于设备默认）
{
  "mode": "cli"          // "plugin"（默认）| "cli"
}
```

### 11.4 前端（Qt 控制台）只做"设备级默认"，不碰项目目录

- 控制台写 `~/.config/memoryhub/config.json`（或等价的全局注册表），**不**去改写任意项目的
  `.opencode/` 或 `opencode.json`——GUI 去动项目目录是脆弱且越界的（控制台不知道 opencode
  会开在哪个项目）。
- 项目级覆盖由仓库内 `.memoryhub/config.json` 决定，保证"这个项目就是要极简/就是要协助"
  能跟着仓库走、跟着提交走。

### 11.5 生效语义：对"新会话"生效，非热切换

- 插件在 **opencode 会话启动时**读取 mode，决定注册哪些 tools / hooks（插件只在启动时加载）；
- MCP 的 `enabled` 与 `tools.memoryhub_*` glob 同理，在新会话生效；
- 因此 **切换后：当前已打开的会话不变，下一次会话（或重启 opencode）生效**。
  文档与控制台 UI 必须把这句话写清楚，避免"我切了怎么没变"。

### 11.6 为什么"默认 plugin"成立

- **UX 优先**：绝大多数用户要"零思考、自动沉淀、越用越懂"；
- **成本可控**：plugin profile 的默认面是 3 个 custom tool + 严格过滤的 hooks，远低于现状
  14 个 MCP 工具常驻；
- **CLI 不消失**：plugin 的 tools/commands 底层就是 CLI，"按需省 token"的语义天然保留，
  想省就切 `cli`。

### 11.7 实现时的坑（提醒）

1. 不要把 profile 实现成"两套插件文件、二选一安装"——会回到双实现、双维护；
2. 前端切换要明确"新会话生效"，必要时在控制台 UI 上提示"重开会话后生效"；
3. `mode` 只决定"激活哪些表层"，**不要**让它决定"装不装 CLI"（CLI 永远在）；
4. 若未来要热切换，方向是让插件监听 mode 文件变化并在会话内动态增删工具（opencode 插件模型
   暂不支持，标记为远期规划）。

---

## 12. 落地路线与迁移清单

### 12.1 阶段划分

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0（1–2 周）** | `agent-integration/` 骨架 + 统一 client + 唯一 MCP 包；CLI 基础子命令（search/context/remember/forget/list/status）；安装器复制 tools/commands/skills 到 `.opencode/` | 3 份拷贝收成 1 份；`memoryhub` CLI 全链路可用 |
| **P1（2–3 周）** | 插件 custom tools（3 薄壳）+ commands（/memoryhub-*）+ skill（memory-awareness）+ hooks（tool.execute.after / session.status / session.deleted / compacting 注入）；CLI 补全（feedback/review/decide/resolve/fact/export/import/service/completion） | `/memoryhub-*` 可用；自动沉淀按回合生效；压缩注入可用 |
| **P2（2 周）** | 配置三层解析；导出/导入/服务管理联调；契约表文档化；claudecode 侧软链收敛；opencode MCP 段可选启用验证 | 双模式同一份配置、同一份记忆；文档与代码零漂移 |

### 12.2 迁移步骤（改动面）

1. **新建** `agent-integration/`（§5.1 目录）；把现有 `opencode-integration/mcp-server/` 内容迁入
   `agent-integration/memoryhub_mcp/`；
2. **扩写** `integrations/memoryhub_client.py` → `agent-integration/memoryhub_client/`（§5.2），
   补全 REST 方法；`integrations/agents/qwen_agent.py` 改为引用统一 client（或保留薄封装）；
3. **新增** `agent-integration/memoryhub_cli/`（§7）；`pyproject.toml` 增加
   `[project.scripts] memoryhub = "memoryhub_cli.cli:main"`；
4. **重写** opencode 插件 `plugin/memoryhub.plugin.mjs`（§6）：custom tools + commands + skills +
   三事件 hooks + compacting 注入；安装器改为一次复制全套；
5. **标记 deprecated** `opencode-integration/`、`claudecode-integration/` 内重复的
   `mcp-server/` 为 wrapper 指向新包；验证后删除副本；
6. **同步文档**：`docs/design/产品形态与使用方案.md`、`opencode-integration/docs/INTEGRATION.md`
   的工具数量/映射表更新到新契约（`agent-integration/docs/CONTRACT.md` 为准）。

### 12.3 需要落地的 REST 增强（最小集）

- `POST /api/memory/context`、`POST /api/memory/search` 增加可选 `project` 过滤参数
  （配合 §6.4 项目级事件）；【规划】
- 事件写入的 `payload` 已可携带 `project_root/project_name`，REST 侧无需改 schema。【已满足】

---

## 13. 与现状的对照表

| 维度 | 现状 | 重构后 | 改进点 |
|---|---|---|---|
| 工具面 | 14 个 MCP 工具常驻 | opencode 内 3 个原生 custom tool 薄壳；其余走 CLI/commands；MCP 仅按需启用 | 每回合省数百 token |
| 工具启停 | 自研开关（无） | opencode 原生 `tools`/`permission` glob（`memoryhub_*`） | 官方机制，零维护 |
| 用户命令 | 无 | `/memoryhub-remember|forget|context|status|review`（command） | 记忆对用户可见可控 |
| 被动想起 | 无 | `memory-awareness` skill + command `!` 注入 + `memoryhub context` | 开箱可用 |
| MCP 代码 | 3 份拷贝 | 1 份共享包（跨 Agent 标准） | 消灭重复维护 |
| 自动沉淀 | `session.idle` 整会话一次 | `tool.execute.after` 累积 → `session.status` 冲刷 → `session.deleted` 兜底 | 细粒度、可恢复、官方推荐事件 |
| 压缩期记忆 | 无 | `experimental.session.compacting` 注入记忆 | 持久记忆熬过压缩 |
| CLI | 无 | `memoryhub` 全 REST 命令面 + `--json/--compact/--quiet` | 零插件、可脚本、省 token |
| 自反馈 | `used_memory_ids` 未接 | skill 提示模型 `memoryhub feedback confirm` → 核心刷新 `stability`/置信度/健康度 | 命中反哺置信度 + **艾宾浩斯复习强化**（越用越懂） |
| 记忆分层 | 无 level 维度 | `search/context` 支持 `level`(short/mid/long)；context 按"会话短期→中期→长期"级联 | Agent 区分"本会话刚发生/历史沉淀" |
| 溯源/投影 | 无 | CLI `provenance <id>`、`projection list/replay`（v2 接口） | 可回答"这条记忆为什么/从哪来、索引同步没有" |
| 项目隔离 | 仅 scene/task/app | + `project_root/project_name` + 检索 `project` 过滤 | opencode 多项目不串味 |
| 事实接入 | 独立 `propose_facts/decide_facts` | 并入 `knowledge_type=fact`（统一知识面） | 消灭独立事实工具/存储（V2 §4.8） |
| 配置 | 散落环境变量 | env（`{env:}` 原生支持） + `.memoryhub/config.json` + 全局 | 单一解析、三层优先级 |
| 交互模式 | 无（14 工具常驻） | Profile：`plugin`（默认）/ `cli`，agent→项目→设备级三层覆盖，前端可切 | 默认协助、按需极简 |
| 文档 | 12 工具漂移 | 契约表统一在 `CONTRACT.md` | 文档零漂移 |

---

## 14. 与核心重构 V2 的同步：统一 API 契约（取代旧工具/方法表）

> 依据：`docs/refactor/REFACTOR_PLAN_V2.md` §4.9（Agent 接入与统一 API 面）、§4.5.3（艾宾浩斯遗忘曲线）。
> 本节是接入层与核心层**双向优化**后的统一契约；**凡 §5.2、§7.2、§13 与本节冲突处，以本节为准**。

### 14.1 统一 API 契约（CLI / MCP / Agent 共用一套 REST 面）

原则不变：**CLI 是记忆能力的"母语"，Plugin 的 custom tools/commands 与 MCP 工具都是 CLI 薄壳**。
核心重构后暴露的统一契约如下（与 `REFACTOR_PLAN_V2.md` §4.9.4 逐行对应）：

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

### 14.2 相对旧设计的关键变更

1. **事实并入知识**：核心决策"事实不再独立成类，降格为 `KnowledgeType.FACT`"（V2 §4.8）。接入侧——
   `propose_facts/decide_facts` 不再独立；三元组以 `knowledge_type=fact` 承载；CLI `fact propose` →
   `remember --type knowledge:fact`（或 `knowledge fact propose`）；MCP 工具面无 `*_facts`。
2. **记忆分层暴露**：`search`/`context` 支持 `level`（short/mid/long）过滤与返回标注；`context` 注入按
   "会话短期（工作记忆）→ 近期中期（情景）→ 长期（全局）"级联（V2 §4.4.3），响应标注 `memory_level`。
3. **project 隔离**：`search`/`context` 增加 `project` 参数（原 §12.3 的【规划】升级为必做），配合自动沉淀
   写入的 `payload.project_root/project_name`（§6.4），多项目互不串味。
4. **统一记忆更新**：`PUT /api/memory/{type}/{id}` 覆盖偏好/知识（含 FACT），替代散落的"改偏好/改知识"细节。
5. **自反馈闭环（记忆越用越懂）**：`feedback confirm/reject` 驱动 `access_count/stability`（艾宾浩斯复习强化，
   `health.py:98-105`）与置信度/健康度更新；skill 引导模型"使用某条记忆后 `feedback confirm`"（§6.3 规则 4）。
6. **溯源与投影**：CLI 新增 `provenance <id>`（lineage/evidence/audit）与 `projection list/replay`，对应 v2 只读接口。

### 14.3 旧表述 → 新表述映射

| 旧表述（§1/§5/§7/§13） | 新表述 |
|---|---|
| 14 个 MCP 工具（含 `propose_facts`/`decide_facts`） | 收敛后的统一工具面（§14.1），事实并入 `knowledge` |
| `write_preference` / `write_knowledge` 分别写 | `remember --type` + 统一 `PUT /{type}/{id}` |
| `list_memories / get_memory` 按类型分开 | `list [--type]` / `get`（返回含 `memory_level`） |
| 无溯源/投影入口 | `provenance <id>`、`projection list/replay` |
| 检索无 level/project 维度 | `search/context` 支持 `level`/`project`（返回 `memory_level`） |

### 14.4 与艾宾浩斯遗忘机制的关系

接入层是"记忆越用越懂"闭环的**触发端**：模型使用记忆 → `feedback confirm` → 核心按艾宾浩斯曲线增强
`stability`（`health.py:98-105` 的 `S × (1 + hits/10)`）并刷新健康度 → 记忆更不易被遗忘/降级（V2 §4.5.3）。
接入侧无需感知公式，只负责**如实上报"用了哪条记忆、用户认不认可"**——`agent_api.step` 已有 `used_memory_ids`
概念（§1.6），接入层需把它接通到 `feedback confirm`。

---

*本文档为接入重构设计稿；落地状态、接口映射与已知问题将随开发更新。*
*依据：`md/`（opencode 官方文档 plugins/skills/commands/mcp-servers/custom-tools/tools/config/agents）。*
*关联：`docs/design/产品形态与使用方案.md`、`opencode-integration/docs/INTEGRATION.md`（旧）、
`docs/refactor/REFACTOR_PLAN_V2.md`（核心重构 V2）、`docs/spec/ARCHITECTURE.md`、`docs/spec/INTERFACE.md`。*
