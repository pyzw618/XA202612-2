# Kylin MemoryHub

> 面向银河麒麟操作系统的 AI Agent 本地记忆引擎 —— 端侧可插拔的混合检索与生命周期管理后端。
>
> 单一仓库包含 FastAPI 后端、Qt 5 桌面控制台、CLI / MCP / OpenCode 接入层、评测模块与 DEB 打包脚本。

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)](https://fastapi.tiangolo.com/)
[![Qt](https://img.shields.io/badge/Qt-5.9%2B-41CD52)](https://www.qt.io/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#license)

---

## 目录

- [项目概览](#项目概览)
- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [vNext 统一链路](#vnext-统一链路)
- [仓库结构](#仓库结构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
  - [安装后端依赖](#安装后端依赖)
  - [启动后端服务](#启动后端服务)
  - [构建桌面客户端](#构建桌面客户端)
  - [Agent 接入（CLI / MCP / OpenCode）](#agent-接入cli--mcp--opencode)
  - [DEB 打包与离线安装](#deb-打包与离线安装)
- [配置](#配置)
- [REST API](#rest-api)
- [模块详解](#模块详解)
- [评测](#评测)
- [测试](#测试)
- [脚本与运维工具](#脚本与运维工具)
- [开发约定](#开发约定)
- [已知限制](#已知限制)
- [License](#license)

---

## 项目概览

MemoryHub 是为 **银河麒麟 OS / openKylin** 上运行的 AI Agent 提供的一套本地化"记忆系统"，
让 Agent 能够：

- 记住用户的偏好与工作流，并在后续会话中自动复用；
- 从工具轨迹、用户行为、手动配置等多源事件中抽取偏好、知识、事实；
- 在写入前通过安全门禁进行敏感信息脱敏、REVIEW 隔离与审计；
- 在检索时融合向量与关键词通道，并对短期工作记忆 / 中期情景 / 长期记忆分层级联；
- 在冲突 / 过期 / 召回失败时支持精准遗忘、状态流转与健康度衰减。

后端监听 `127.0.0.1:8099`，通过 HTTP JSON 与 OS Agent / Qt 客户端 / CLI 通信；
数据库与向量索引全部位于本地文件系统，不依赖外部云服务。

---

## 核心能力

| 模块              | 能力                                                                                  |
|-------------------|---------------------------------------------------------------------------------------|
| 多源接入          | 工具结果（`/sources/tool_result`）、用户行为（`/sources/behavior`）、手动配置（`/sources/config`） |
| 事件处理          | 清洗 / 标准化 / 质量评分 / 安全门禁 / 偏好&知识抽取 / 抽取重试与死信                        |
| 记忆类型          | `preference`（偏好）、`knowledge`（含 `fact` 子类型）、`episode`（中期情景）                  |
| 安全门禁          | 声明式规则集 catalog、内置规则 + 用户规则 Overlay、AES-256-GCM 隔离区、HMAC 审计链         |
| 混合检索          | Milvus 真实引擎（生产）+ FAISS / BM25（dev/test 降级）                                  |
| 检索缓存          | LRU + TTL，按 `index_version` 自动失效                                                  |
| 检索级联          | 短期工作记忆 → 中期情景 → 长期混合，三层按权重融合并标记 `memory_level`                       |
| 状态机            | `active / pending / archived / deleted` 单条 / 批量流转、版本谱系、证据链                   |
| 精准遗忘          | NL 指令意图解析 → 定位候选 → 预览 → 真实删除 + 审计；支持用户级"删除涉及 X 的记忆"规则         |
| 生命周期          | 会话→中期→长期合并、Tool / Workflow 挖掘、自动遗忘 / 降级调度                              |
| 投影一致性        | SQLite 事实源 → durable outbox → 向量 / 关键词 / 缓存后台补偿，漂移对账                    |
| 运维接口          | 健康度看板、状态 / 配置查看、REVIEW 隔离区放行、抽取任务管理、Milvus 漂移对账               |
| 评测              | 检索评测、延迟基准、全链路基准、内置数据集 + SHA256SUMS                                    |

---

## 系统架构

```
┌────────────────────────────────────────────────────────────┐
│  OS Agent · Qt 桌面控制台 · OpenCode Plugin · CLI / MCP      │
└────────────────────────────────────────────────────────────┘
                          │ HTTP JSON (127.0.0.1:8099)
                          ▼
┌────────────────────────────────────────────────────────────┐
│  FastAPI 应用（memoryhub/app.py）                            │
│  ├ /api/memory/*        标准 REST 路由                      │
│  ├ /api/memory/v2/*     谱系 / 证据 / 投影管理              │
│  ├ /api/memory/vnext/*  vNext 统一写入 / 检索 / 恢复 / 灰度 │
│  ├ /api/memory/admin/*  管理后台（UI 驱动）                  │
│  └ /api/agent/*         Agent 演示适配层（step / replay）   │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  适配层 adapter/ + 服务层 core/                              │
│  EventIngestionService → MemoryWriteService                 │
│  HybridRetriever / MilvusHybridRetriever / 分层级联         │
│  SafetyWriteGate · AutoForget · LifecycleScheduler          │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────┐
│  存储层 storage/                                              │
│  SQLite（事实源） · Vector Engine · Search Cache · Outbox   │
└────────────────────────────────────────────────────────────┘
```

**关键约束（生产模式 `runtime.mode=production`）**：

- 强制 `embedding.provider="kylin"`、`vector_engine.provider="milvus"`，向量维度 768；
- 禁止 mock / faiss / milvus_mock 降级，禁用静默 fallback；
- 所有写入必须经过 `SafetyWriteGate`，记录 HMAC 审计日志；
- 仅装配 `MilvusHybridRetriever`，不构建 `KeywordSearcher` / `HybridRetriever` 降级路径。

---

## 仓库结构

```
.
├── memoryhub/                       # 后端核心 Python 包（参见 memoryhub/app.py）
│   ├── app.py                       # FastAPI 入口；create_app + lifespan
│   ├── config.py                    # dataclass 配置；生产模式门禁
│   ├── adapter/                     # REST 路由层
│   │   ├── api.py                   # /api/memory/* 标准接口
│   │   ├── agent_api.py             # /api/agent/* 演示适配层
│   │   ├── management_api.py        # 后台管理接口（UI 驱动）
│   │   ├── memory_v2_api.py         # 谱系 / 证据 / 投影只读 + replay
│   │   ├── service.py               # MemoryService 最小垂直切片
│   │   ├── schemas.py               # Pydantic DTO
│   │   ├── user_rule_schemas.py     # 用户敏感规则 REST DTO
│   │   └── simulator.py             # OS Agent 模拟器
│   ├── core/                        # 领域核心
│   │   ├── processing.py            # 事件处理协调器
│   │   ├── memory_write.py          # 统一持久化 / 索引同步
│   │   ├── memory/                  # 通用领域模型
│   │   ├── ingestion/               # 多源接入、清洗、抽取、重试
│   │   ├── preference/              # 偏好抽取 / 置信度 / 更新
│   │   ├── knowledge/               # 知识抽取 / 合并 / 工作流挖掘
│   │   ├── conflict/                # 冲突检测 / 解决
│   │   ├── forget/                  # 精准遗忘 / 自动遗忘 / 健康度
│   │   ├── safety/                  # 检测器 / 写入门禁 / 审计 / 隔离 / 用户规则
│   │   ├── lifecycle/               # 调度器 / 整合器 / 降级器
│   │   └── domain_writer.py         # 域对象写入入口
│   ├── retrieval/                   # 检索引擎
│   │   ├── milvus_hybrid.py         # 生产唯一装配
│   │   ├── hybrid.py                # dev/test 降级（FAISS + BM25）
│   │   ├── keyword_search.py        # BM25 + jieba
│   │   ├── vector_search.py         # FAISS IndexFlatIP
│   │   ├── reranker.py              # 重排序
│   │   └── cache.py                 # LRU + TTL 检索缓存
│   ├── storage/                     # 持久化层
│   │   ├── database.py              # SQLite + SQLAlchemy + Repository
│   │   ├── models.py                # ORM 模型
│   │   ├── vector_store.py          # FAISS 索引管理
│   │   ├── vector_engine/           # faiss / milvus / milvus_mock / sparse
│   │   ├── sync_service.py          # SQLite ↔ Milvus 漂移对账
│   │   ├── compensation_task.py     # pending_index 补偿任务
│   │   ├── projection_outbox.py     # durable outbox + worker
│   │   ├── memory_metadata.py       # 谱系 / 证据 / outbox 仓储
│   │   └── evidence_store.py        # JSONL 证据链
│   ├── embedding/                   # Embedding 抽象
│   │   ├── base.py                  # 抽象接口
│   │   ├── kylin_client.py          # ctypes 加载麒麟 SDK
│   │   └── mock_client.py           # SHA256 + 种子确定性随机向量
│   ├── llm/                         # LLM 抽象
│   │   ├── base.py                  # 抽象接口
│   │   └── openai_client.py         # Cloud OpenAI 兼容 API
│   ├── safety_rules/                # 版本化声明式安全规则库
│   │   ├── catalog.json             # 已发布规则集清单
│   │   └── data/builtin-1.0.json    # 内置 v1.0 规则
│   └── __init__.py
├── desktop-client/                  # Qt 5 Widgets 桌面控制台
│   ├── src/
│   │   ├── main.cpp · AppContext · MainWindow
│   │   ├── api/                     # ApiClient（同步 + 等待光标）
│   │   ├── widgets/                 # PageHeader/StatCard/ScoreRing/DetailDrawer…
│   │   └── pages/                   # 13 个页面（含 ForgetPages/SafetyPages/SettingsPages）
│   ├── CMakeLists.txt
│   └── build-linux.sh · build-win.ps1
├── agent-integration/               # Agent 接入层（CLI 为母语）
│   ├── memoryhub_cli/cli.py         # argparse CLI（subcommand: search/context/event/remember/update/...）
│   ├── memoryhub_client/            # Python 同步客户端 + ClientConfig
│   ├── memoryhub_mcp/               # MCP server（stdio）
│   └── plugin/opencode/             # OpenCode 插件 / 命令 / 工具 / 技能
├── evaluation/                      # 评测模块
│   ├── metrics/                     # retrieval / latency / preference / conflict / full_chain
│   ├── datasets/                    # dev / test / golden / latency + SHA256SUMS
│   └── run_*.py                     # 评测驱动脚本
├── packaging/linux/                 # 银河麒麟 DEB 打包
│   ├── build-deb.sh                 # 离线 wheelhouse + Qt 编译 + DEB 装配
│   └── assets/                      # 桌面项 / systemd 用户服务 / opencode 资源
├── scripts/                         # 运维脚本
│   ├── start-memoryhub-service.{ps1,sh}
│   ├── stop-memoryhub-service.ps1
│   ├── verify_kylin_environment.py
│   ├── check_kylin_embedding_runtime.py
│   ├── run_milvus_real_smoke_test.py
│   ├── verify_management_api.py
│   ├── migrate_memory_provenance.py
│   └── gen_ai_report_docx.py
├── tests/                           # 后端测试（≈70 用例，按功能域命名 *_acceptance）
├── examples/                        # 演示 / 集成示例（demo_workspace / run_qwen_agent.py）
├── docs/                            # 设计 / 验收 / 接口文档
│   ├── vnext/                       # vNext 方案、规范、ADR、阶段文档
├── config.example.yaml              # 生产配置示例（含全部安全密钥占位）
├── .env.example                     # 环境变量示例
├── pyproject.toml                   # 项目元数据 + 工具链配置
├── requirements.txt                 # 生产依赖
└── requirements-dev.txt             # 开发 / 测试 / 评测依赖
```

---

## vNext 统一链路

MemoryHub vNext 是面向生产 OS Agent 的新一代统一记忆链路，覆盖规范事件写入、工作记忆 / 情景 / 长期记忆的 Formation、检索、精准遗忘与灰度切流。核心入口为 `POST /api/memory/vnext/events`（统一写入）和 `POST /api/memory/vnext/search` / `POST /api/memory/vnext/context`（统一检索），CLI / MCP / SDK / OpenCode 最终都委托到这组契约。

| 能力 | vNext 入口 | 说明 |
|------|-----------|------|
| 统一写入 | `POST /api/memory/vnext/events` | 规范 Memory / Working / Episode / Authority 事件；`CanonicalWriteService` 处理 Formation |
| 统一检索 | `POST /api/memory/vnext/search` | 融合短期 / 中期 / 长期结果 |
| 上下文 | `POST /api/memory/vnext/context` | 生成可直接注入 prompt 的记忆上下文 |
| 任务恢复 | `GET /api/memory/vnext/tasks/{task_id}/resume` | 跨会话恢复任务状态 |
| 精准遗忘 | `POST /api/memory/vnext/forget` | NL 意图解析 → 候选预览 → 执行删除 + 审计 |
| 灰度切流 | `/api/memory/vnext/rollout/*` | 0→100% 渐进切流、观测与一键回滚 |

配置节 `vnext.*` 控制链路模式（`legacy` / `shadow` / `dual-read` / `vnext` / `canary`）、Formation 策略和只读兜底。详细设计、规范、ADR 与阶段文档见 [`docs/vnext/`](docs/vnext/)。

## 环境要求

| 组件        | 要求                                                          |
|-------------|---------------------------------------------------------------|
| 操作系统    | 银河麒麟 V11 / openKylin 2.x（生产）；Windows 10/11（开发验证）  |
| Python      | ≥ 3.11                                                       |
| 数据库      | SQLite（自带，无需额外安装）                                   |
| 向量引擎    | Milvus 麒麟 C SDK（生产）；FAISS / milvus_mock（开发）          |
| Embedding   | 麒麟 `libkylin-coreai-embedding.so`（生产）；Mock 动态库（开发）  |
| Qt          | ≥ 5.9（推荐 5.15，需 Widgets / Network / Charts 模块）          |
| CMake       | ≥ 3.16                                                       |
| 编译器      | Linux: g++ 7+；Windows: MSVC 2019+ 或 MinGW                     |

---

## 快速开始

### 安装后端依赖

```bash
sudo apt install ./kylin-memoryhub_0.1.0-9_amd64.deb
memoryhub-configure-opencode --current-user
```

安装包同时提供后端、Qt 桌面控制台、CLI/MCP 和 OpenCode 全局插件。OpenCode 配置会根据当前用户主目录自动写入 `~/.config/opencode/`，详见 [`packaging/linux/README.md`](packaging/linux/README.md)。

面向普通用户的下载、图形化安装和首次使用步骤见 [`docs/银河麒麟安装与使用手册.md`](docs/银河麒麟安装与使用手册.md)。

```bash
# 创建虚拟环境并安装生产依赖
python -m venv .venv
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Linux
./.venv/bin/python -m pip install -r requirements.txt

# 或以可编辑模式安装（含 CLI / MCP 入口注册）
pip install -e .

# 复制并按需修改配置
cp config.example.yaml config.yaml
cp .env.example .env
```

### 启动后端服务

**Windows（PowerShell）**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1
```

**Linux（bash）**

```bash
bash scripts/start-memoryhub-service.sh
```

**手动启动**

```bash
python -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8099
```

**验证**

- 健康检查：`GET http://127.0.0.1:8099/api/memory/health`
- Swagger UI：`http://127.0.0.1:8099/docs`
- 停止服务：`powershell -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1`

### 构建桌面客户端

**Linux（银河麒麟 / openKylin）**

```bash
sudo apt install qtbase5-dev qtbase5-dev-tools libqt5charts5-dev \
                 qt5-ukui-platformtheme build-essential cmake
bash desktop-client/build-linux.sh
./desktop-client/build/memoryhub-client
```

**Windows（开发验证）**

> 中文路径会破坏 MSVC 的 PDB/moc；建议先在源码父目录创建 ASCII junction。

```powershell
New-Item -ItemType Junction -Path 'C:\mhub-src' -Target '<绝对路径>\desktop-client' -Force
powershell -ExecutionPolicy Bypass -File desktop-client\build-win.ps1
```

详细说明见 [`desktop-client/README.md`](desktop-client/README.md)。

### Agent 接入（CLI / MCP / OpenCode）

```bash
# CLI（命令示例）
memoryhub --user default search "周报格式"
memoryhub context "今天的工作计划"
memoryhub remember --type preference "我习惯用 Markdown 写周报"

# MCP（stdio 传输）
python -m memoryhub_mcp

# OpenCode 插件（自动发现）
node agent-integration/plugin/opencode/install_plugin.mjs
```

详见 [`agent-integration/README.md`](agent-integration/README.md) 与 `opencode.json`。

### DEB 打包与离线安装

```bash
# 在仓库根目录构建 DEB
bash packaging/linux/build-deb.sh

# 离线安装
sudo apt install ./packaging/linux/dist/kylin-memoryhub_<ver>-1_amd64.deb
memoryhub-configure-opencode --current-user
memoryhub status
```

构建脚本会预先生成 wheelhouse、编译并冒烟测试 Qt 客户端、再装配 DEB；
目标机配置阶段不需要访问 PyPI。详见 [`packaging/linux/README.md`](packaging/linux/README.md)。

---

## 配置

后端同时支持 YAML（`config.yaml`）与环境变量（`.env`），运行时门禁由 `memoryhub/config.py` 校验。

### 核心节

| 节                 | 关键字段                                                              |
|--------------------|----------------------------------------------------------------------|
| `runtime`          | `mode`（production / development / test）、`allow_fallback`           |
| `vnext`            | `mode`、`formation_mode`、`events_default`、`canary_percent`、`policy_required`、`authority_single_writer`、`allow_legacy_read_fallback` |
| `storage`          | `db_path`、`vector_index_path`、`evidence_path`、`cache_max_size`    |
| `retrieval`        | `default_top_k`、`candidate_multiplier`、`max_query_chars`、`target_p95_ms`、`vector_weight` / `keyword_weight` / `metadata_weight` |
| `llm`              | `api_base`、`api_key`、`model`、`temperature`、`max_tokens`、`fact_extraction_timeout_seconds` |
| `embedding`        | `provider`（kylin / mock / kylin_mock / auto）、`dimension`、`model_name`、`so_path`、`query_timeout_ms` |
| `vector_engine`    | `provider`（milvus / faiss / milvus_mock）、`app_id`、`host`、`port`、`collection`、`dimension`、`search_timeout_ms`、`so_path` |
| `safety`           | `rule_set_id` / `rule_set_version`、`policy`、`auto_mask`、`reject_on_detect`、`key_store`、`audit`、`quarantine`、`user_rules` |
| `app`              | `debug`、`log_level`、`host`、`port`                                  |

### vNext 第二阶段默认配置

MemoryHub vNext 默认启用主链路：

- `vnext.mode=vnext`：`/api/memory/search`、`/api/memory/context` 和 Agent 适配层直接返回 vNext `RetrievalService` 结果，不再执行 dual-read。
- `vnext.formation_mode=authority`：Formation 默认将通过门禁的结果沉淀到长期 Authority，并产生 `AUTHORITY_PROMOTED` 事件。
- `vnext.events_default=true`：`/api/memory/events`、`/api/memory/sources/tool_result|behavior|config` 等标准写入口统一使用 vNext `CanonicalWriteService`。

仍可显式配置 `legacy`、`shadow`、`dual-read` 或 `canary` 做回滚/观测；`allow_legacy_read_fallback` 只用于 vNext 读失败时的只读兜底。标准写入口不再回退到 legacy `EventIngestionService`。详细设计、配置项语义与灰度策略见 [`docs/vnext/spec/VNEXT_ROLLOUT.md`](docs/vnext/spec/VNEXT_ROLLOUT.md) 与 [`docs/vnext/VNEXT_PLAN.md`](docs/vnext/VNEXT_PLAN.md)。

```bash
MEMORYHUB_VNEXT_EVENTS_DEFAULT=false
# 或整体切回 legacy 模式
MEMORYHUB_VNEXT_MODE=legacy
```

### 环境变量

```env
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=<your-key>
LLM_MODEL=gpt-4o-mini
EMBEDDING_PROVIDER=mock            # 生产必须 kylin
EMBEDDING_DIMENSION=768
DB_PATH=data/memoryhub.db
MEMORYHUB_VECTOR_ENGINE_APP_ID=<provided-by-deployment-platform>
MEMORYHUB_USER_RULE_KEY=<base64 32-byte>     # 与 audit/quarantine 密钥独立
MEMORYHUB_AUDIT_HMAC_KEY=<base64 32-byte>
MEMORYHUB_QUARANTINE_KEY=<base64 32-byte>
```

> 任何 32 字节随机密钥的 Base64 编码均可；推荐 `openssl rand -base64 32` 生成。
> 三个密钥（user_rule / audit / quarantine）必须相互独立，不得复用。

### 运行时模式门禁

| 模式           | Embedding            | Vector Engine       | 检索装配                      | 写入门禁 |
|----------------|----------------------|---------------------|-------------------------------|----------|
| `production`   | `kylin`（强制）      | `milvus`（强制）    | `MilvusHybridRetriever`       | 强制     |
| `development`  | mock / kylin / auto  | faiss / milvus_mock | 视 provider 决定              | 可选     |
| `test`         | mock                 | milvus_mock / faiss | 同上                          | 可选     |

`allow_fallback` 在 `production` 下被强制设为 `false`；启动时
`validate_production_runtime()` 会校验 SDK 可用性与实际向量维度。

---

## REST API

所有接口均通过 `memoryhub/app.py` 注册，基础前缀 `/api`。
完整定义请参考 Swagger UI（`http://127.0.0.1:8099/docs`）以及源码：

| 路由文件                                  | 前缀                  | 说明                       |
|-------------------------------------------|-----------------------|----------------------------|
| `memoryhub/adapter/api.py`                | `/api/memory`         | 标准记忆 REST 路由         |
| `memoryhub/adapter/agent_api.py`          | `/api/agent`          | Agent 演示适配层           |
| `memoryhub/adapter/management_api.py`     | `/api/memory`         | 后台管理接口（UI 驱动）    |
| `memoryhub/adapter/memory_v2_api.py`      | `/api/memory/v2`      | 谱系 / 证据 / 投影         |
| `memoryhub/adapter/vnext_api.py`          | `/api/memory/vnext`   | vNext 统一写入 / 检索 / 任务恢复 / 灰度 |

### 主要端点

| 方法 | 路径                                                 | 用途                                                   |
|------|------------------------------------------------------|--------------------------------------------------------|
| GET  | `/api/memory/health`                                 | 健康检查（SQLite + 服务状态）                            |
| GET  | `/api/agent/health`                                  | Agent 适配层健康检查                                     |
| POST | `/api/memory/events`                                 | 写入 MemoryEvent（自动门禁 + 抽取）                     |
| POST | `/api/memory/sources/tool_result`                    | 工具结果源接入                                          |
| POST | `/api/memory/sources/behavior`                       | 用户行为源接入                                          |
| POST | `/api/memory/sources/config`                         | 手动配置源接入（版本链）                                |
| POST | `/api/memory/search`                                 | 混合检索偏好 / 知识（含 level 级联）                    |
| POST | `/api/memory/context`                                | 生成可直接注入 prompt 的记忆上下文                      |
| POST | `/api/memory/v2/search`                              | v2 谱系感知检索                                          |
| GET  | `/api/memory/preferences`                            | 偏好列表（scene / status 过滤）                         |
| GET  | `/api/memory/knowledge`                              | 知识列表（scene / knowledge_type / status 过滤）         |
| GET  | `/api/memory/facts`                                  | 事实列表（`knowledge_type=fact`）                       |
| GET  | `/api/memory/conflicts`                              | 冲突列表（支持分页）                                    |
| POST | `/api/memory/conflicts/{id}/resolve`                 | 冲突裁决                                                |
| POST | `/api/memory/feedback`                               | 用户反馈（confirm / reject / update）                   |
| POST | `/api/memory/memories/preference`                    | 显式写入偏好                                            |
| POST | `/api/memory/memories/knowledge`                     | 显式写入知识                                            |
| PUT  | `/api/memory/{type}/{id}`                            | 统一更新（type ∈ preference / knowledge / fact）        |
| PATCH| `/api/memory/memories/{id}/status`                   | 单条状态流转（兼容入口）                                |
| POST | `/api/memory/memories/status`                        | 批量状态流转                                            |
| POST | `/api/memory/memories/delete`                        | 批量软删除                                              |
| DELETE| `/api/memory/memories/{id}?hard=true`               | 物理删除（hard=true）                                   |
| GET  | `/api/memory/memories/health`                        | 健康度看板                                              |
| GET  | `/api/memory/preferences/{id}/versions`              | 偏好版本历史链                                          |
| GET  | `/api/memory/knowledge/{id}/versions`                | 知识版本历史链                                          |
| GET  | `/api/memory/v2/memories/{id}/lineage`               | 谱系（parent / root）                                   |
| GET  | `/api/memory/v2/memories/{id}/evidence`              | 证据列表（脱敏摘要）                                    |
| GET  | `/api/memory/v2/memories/{id}/audit`                 | 该记忆相关的审计条目                                    |
| GET  | `/api/memory/v2/projections`                         | 投影 outbox 列表                                        |
| POST | `/api/memory/v2/projections/replay`                  | 重放失败投影（仅 caller-owned）                          |
| POST | `/api/memory/forget/preview`                         | 遗忘候选预览                                            |
| POST | `/api/memory/forget`                                 | 执行精准遗忘                                            |
| GET  | `/api/memory/forget/history`                         | 遗忘历史                                                |
| GET  | `/api/memory/forget/history/{record_id}`             | 单条遗忘详情（被删记忆内容）                            |
| GET  | `/api/memory/forget/rules`                           | 用户级遗忘规则列表                                      |
| POST | `/api/memory/forget/rules`                           | 创建遗忘规则（如"删除涉及 X 的记忆"）                   |
| DELETE | `/api/memory/forget/rules/{rule_id}`               | 删除遗忘规则                                            |
| POST | `/api/memory/lifecycle/auto-forget`                  | 立即执行自动遗忘扫描                                    |
| POST | `/api/memory/lifecycle/check`                        | 手动触发生命周期检查                                    |
| POST | `/api/memory/lifecycle/consolidate`                  | 手动触发记忆合并（session → mid → long）                |
| GET  | `/api/memory/lifecycle/settings`                     | 生命周期 / 遗忘阈值（只读）                             |
| GET  | `/api/memory/short-term`                             | 短期工作记忆列表                                        |
| GET  | `/api/memory/mid-term`                               | 中期情景列表                                            |
| GET  | `/api/memory/events`                                 | 全量事件列表（分页）                                    |
| GET  | `/api/memory/events/session/{session_id}`            | 单会话事件                                              |
| POST | `/api/memory/facts/propose`                          | 手工三元组 → knowledge(FACT)                            |
| POST | `/api/memory/admin/reconcile`                        | SQLite ↔ Milvus 漂移对账                                |
| GET  | `/api/memory/extraction/tasks`                       | 抽取任务列表                                            |
| POST | `/api/memory/extraction/tasks/run`                   | 执行到期任务                                            |
| POST | `/api/memory/extraction/tasks/{id}/retry`            | 死信重试                                                |
| GET  | `/api/memory/extraction/tasks/metrics`               | 抽取任务指标                                            |
| GET  | `/api/memory/safety/audit-logs`                      | 安全审计日志                                            |
| GET  | `/api/memory/safety/audit-logs/verify`               | 审计链 HMAC 校验                                        |
| GET  | `/api/memory/safety/quarantine`                      | REVIEW 隔离区列表                                       |
| GET  | `/api/memory/safety/quarantine/{review_id}`          | 单条隔离详情                                            |
| DELETE | `/api/memory/safety/quarantine/{review_id}`        | 丢弃隔离记录                                            |
| POST | `/api/memory/safety/quarantine/{review_id}/release` | 放行 / 驳回隔离记录                                     |
| CRUD | `/api/memory/safety/user-rules`                      | 用户自定义敏感规则（需 `X-MemoryHub-User` 头）          |
| GET  | `/api/memory/system/status`                          | 各子系统状态                                            |
| GET  | `/api/memory/system/config`                          | 后端配置（非敏感）                                      |
| PUT  | `/api/memory/system/llm`                             | 运行时更新 LLM 连接（API key 写不读）                  |
| POST | `/api/agent/step`                                    | 执行一轮 Agent 对话                                     |
| POST | `/api/agent/replay`                                  | 执行 JSON 回放                                          |
| POST | `/api/agent/actions/{id}/decision`                   | 用户裁决                                                |
| DELETE | `/api/agent/preferences`                           | 清理偏好（演示）                                        |
| DELETE | `/api/agent/demo-data`                              | 重置演示数据                                            |
| POST | `/api/memory/evaluate/{task_name}`                   | 触发评测（retrieval / latency / preference / conflict）|
| GET  | `/api/memory/evaluate/reports`                       | 历史评测报告                                            |

### vNext 统一接口

vNext 是生产推荐的统一入口，契约定义在 `memoryhub/adapter/vnext_schemas.py`，详细说明见 [`docs/vnext/spec/VNEXT_INTERFACE.md`](docs/vnext/spec/VNEXT_INTERFACE.md)。

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/memory/vnext/events` | 统一写入事件 / Working / Episode / Authority |
| POST | `/api/memory/vnext/search` | 统一检索 |
| POST | `/api/memory/vnext/context` | 统一生成上下文 |
| GET  | `/api/memory/vnext/tasks/{task_id}` | 查询任务状态 |
| GET  | `/api/memory/vnext/tasks/{task_id}/resume` | 任务恢复 |
| POST | `/api/memory/vnext/forget` | 执行精准遗忘 |
| GET  | `/api/memory/vnext/forget/{record_id}` | 单条遗忘详情 |
| GET  | `/api/memory/vnext/forget` | 遗忘列表 |
| POST | `/api/memory/vnext/diagnostics` | 诊断（管理权限） |
| POST | `/api/memory/vnext/dashboard/{view}` | Dashboard 查询 |
| GET  | `/api/memory/vnext/rollout` | 查询当前灰度级别 |
| POST | `/api/memory/vnext/rollout/advance` | 推进灰度 |
| POST | `/api/memory/vnext/rollout/observe` | 上报观测指标 |
| POST | `/api/memory/vnext/rollout/rollback` | 回滚 |
| POST | `/api/memory/vnext/feedback` | 反馈 |

当 `vnext.mode=vnext` 时，`/api/memory/search`、`/api/memory/context` 等 legacy 入口内部路由到 vNext 检索服务；`vnext.events_default=true` 时，标准写入口统一走 `CanonicalWriteService`。

### 错误模型

- 业务安全门禁：`403`（REJECT）+ `{code, status, safety_action, audit_id}`
- REVIEW 隔离：`409`（REVIEW）+ 同上结构
- Embedding / Milvus 后端超时：`504` + `{code: embedding.timeout | milvus.timeout}`
- Embedding / Milvus 后端不可用：`503`
- 参数校验：`422` + `[{type, loc}]`（仅投影安全字段，不回显原始输入）

### 统一记忆更新接口

已有记忆的人工编辑统一使用 `PUT /api/memory/{type}/{id}`；`type` 为 `preference`、`knowledge` 或 `fact`。请求只需携带要修改的字段，写入将同步状态、置信度、版本/谱系、证据链及检索投影。

- 偏好：`text`、`preference_type`、`payload`、`scope`、`is_global`、`tags`、`extra_payload`、`parent_id`、`root_id`、`evidences` 等。
- 知识：`name`、`content`、`knowledge_type`、`steps`、`tools`、`template_body`、`parent_id`、`evidences` 等。
- 事实：`object_value`、`object_type`、`confidence`、`evidence_text` 或 `evidences` 等。

---

## 模块详解

### Embedding 抽象层（`memoryhub/embedding/`）

```python
from memoryhub.embedding import create_embedding_client

client = create_embedding_client(provider="auto", dim=768)
vec = client.embed("你好世界")           # → list[float]
vecs = client.embed_batch([...])        # → list[list[float]]
```

| 实现                   | 适用场景       | 向量来源                                   |
|------------------------|----------------|--------------------------------------------|
| `MockEmbeddingClient`  | dev / test     | SHA256 + 种子随机，同文本同向量             |
| `KylinEmbeddingClient` | 生产           | ctypes 加载 `libkylin-coreai-embedding.so` |

### 混合检索（`memoryhub/retrieval/`）

| 检索通道         | 底层                          | 适用         |
|------------------|-------------------------------|--------------|
| BM25             | `rank-bm25` + `jieba`         | dev/test     |
| FAISS            | `faiss-cpu` IndexFlatIP       | dev/test     |
| Hybrid（加权融合）| FAISS + BM25 + 元数据          | dev/test     |
| MilvusHybrid     | 麒麟 Milvus SDK 稠密 / 稀疏 RRF | **生产唯一** |

生产模式下 `MilvusHybridRetriever` 由引擎执行稠密 / 稀疏 RRF 融合；缓存按 `index_version` 失效。

### 安全模块（`memoryhub/core/safety/` + `memoryhub/safety_rules/`）

- **规则加载**：`safety_rules/loader.py` 从 `data/catalog.json` 加载版本化快照；
- **检测器**：`detector.py` 递归扫描（深度 / 字节 / 字段 / 候选数 / Finding 数均受 `safety.*` 资源预算约束）；
- **写入门禁**：`gate.py` 决策 ALLOW / MASK / REVIEW / REJECT，MASK 后必须再扫描一次；
- **审计**：`audit_log.py` 仅写最小化投影，跨轮转文件保持 HMAC 哈希链；
- **隔离区**：`quarantine.py` 以 AES-256-GCM 密文保存，普通存储 / 检索 / Embedding / 日志均不可读；
- **用户规则**：`user_rules.py` matcher 以密文存 SQLite，主密钥只从环境变量或设备凭据服务读取；
- **密钥**：`key_store.py` 首次启动自动生成（`auto_generate=true`），重启从 `<db_dir>/security/safety-keys.json` 复用。

### 写入同步（`memoryhub/storage/`）

```
SQLite（事实源）
    │
    ▼
ProjectionOutboxWorker（durable outbox）
    │
    ▼
MemoryWriteService.upsert_memory
    │
    ├─→ MilvusHybridRetriever.index_version++
    ├─→ SearchCache.clear()
    └─→ MemorySyncService.reconcile()（手动 / 定时对账）
```

- 生产模式：写入仅到 durable outbox，由后台 worker 投影到向量 / 关键词 / 缓存；
- dev/test：同步投影（`project_immediately=True`），便于交互式诊断；
- 启动时 `repair_at_startup()` 仅同步历史 `pending_index`，禁止全量重建。

### 记忆分层（`memoryhub/core/lifecycle/`）

| 层级       | 来源                                | 检索级联权重 |
|------------|-------------------------------------|--------------|
| short-term | 当前会话工作记忆（带 `session_id`） | 0.9          |
| mid-term   | 中期情景 / `episode`                | 0.7          |
| long       | 长期偏好 / 知识（混合检索）         | 混合分数     |

`/api/memory/search` 通过 `req.session_id` 触发短期注入；`req.level`（short / mid / long）可显式限定返回层。

---

## 评测

评测模块位于 `evaluation/`：

```bash
# 检索评测（HTTP / Milvus）
python evaluation/run_kylin_http_retrieval_evaluation.py
python evaluation/run_retrieval_eval.py

# 延迟基准
python evaluation/run_latency_eval.py

# Milvus / Milvus Mock 基准
python evaluation/run_milvus_kylin_benchmark.py
python evaluation/run_milvus_mock_benchmark.py

# 数据集校验
python evaluation/validate_retrieval_dataset.py
```

数据集、结果与 SHA256SUMS 位于 `evaluation/datasets/`、`evaluation/results/`。

---

## 测试

```bash
# 后端测试（约 70 用例）
pytest -q

# 分类示例
pytest -q tests/test_preference_functionality.py
pytest -q tests/test_safety_gate.py tests/test_safety_audit_log.py
pytest -q tests/test_retrieval.py tests/test_search_milvus_mock.py

# 桌面客户端测试（Qt Test）
cd desktop-client && ctest --test-dir build -V
```

测试涵盖：偏好 / 知识功能、安全门禁 / 审计 / 用户规则、检索（FAISS / Milvus mock / 超时）、
记忆分层、合并回归、谱系 v2、生产装配门禁、事实→知识迁移、用户隔离等。

---

## vNext 固定验收演示

演示命令不需要启动服务；六类场景和输出契约见
[`examples/vnext_demo/README.md`](examples/vnext_demo/README.md)。在已安装开发依赖的
环境运行：

```powershell
$demoOut = Join-Path $env:TEMP "memoryhub-vnext-demo"
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario all --output-dir $demoOut
```

命令会在 `$demoOut` 生成 `formation.json`、`evidence.json`、`scope.json`、
`retrieval.json`、`resume.json`、`forget.json`、`all.json` 和 `demo.db`；JSON 报告
默认只含脱敏 ID/hash、计数、分类和解释元数据。

---

## 脚本与运维工具

| 脚本                                              | 用途                                                     |
|---------------------------------------------------|----------------------------------------------------------|
| `scripts/start-memoryhub-service.ps1` / `.sh`     | 后端启停（自动探测 .venv，写 PID，等待 `/health` 就绪）   |
| `scripts/stop-memoryhub-service.ps1`              | 按 PID 文件优雅停止                                       |
| `scripts/verify_kylin_environment.py`             | 麒麟 / Mock SDK 环境自检（输出 `retrieval_environment_manifest.json`） |
| `scripts/check_kylin_embedding_runtime.py`        | Embedding 运行时检查                                     |
| `scripts/run_milvus_real_smoke_test.py`           | Milvus 真实引擎冒烟测试                                  |
| `scripts/verify_management_api.py`                | 管理后台接口端到端验证                                    |
| `scripts/migrate_memory_provenance.py`            | 历史记忆谱系迁移                                          |
| `scripts/gen_ai_report_docx.py`                   | 生成 AI 报告 DOCX                                        |

---

## 开发约定

- **依赖管理**：生产依赖在 `requirements.txt`；开发 / 测试 / 评测依赖在 `requirements-dev.txt`；
  `pyproject.toml` 定义入口点 `memoryhub = memoryhub_cli.cli:main`。
- **代码风格**：`ruff`（line-length=100、target=py311、select=E/F/I/W）；
  可选 `black`、`mypy`（`pyproject.toml` 未强制）。
- **安全写入**：所有内容变更必须经过 `SafetyWriteGate`；失败关闭（`fail_closed=true`）。
- **回显最小化**：FastAPI 422 响应只投影安全字段；隔离区 / 用户规则 matcher 永不返回原文。
- **配置密钥**：禁止把真实密钥、`.env`、SQLite、向量索引提交到 Git；`.gitignore` 已覆盖。
- **API 兼容性**：修改现有响应字段时保持兼容；新增字段一律 optional。
- **生产门禁**：提交前至少运行 `pytest -q`；涉及 `runtime.mode=production` 的改动必须经 `validate_production_runtime()`。
- **新接入不要复制** `agent-integration/opencode-integration/` 或 `claudecode-integration/`；使用统一的 `agent-integration/` 入口。

---

## 已知限制

- **Agent 默认编排为确定性规则**；真实大模型接入仍走 OpenAI 兼容 transport。
- **无内置调度器**：自动遗忘与生命周期检查需要手动触发（`/lifecycle/auto-forget` 等）或由外部 cron / systemd timer 调度。
- **偏好 / 冲突评测**已落地，但与检索评测相比覆盖用例较少；全链路基准仅供回归使用。
- **生产模式**强制麒麟 Embedding SDK + Milvus，禁止 mock / FAISS / milvus_mock 降级。
- **跨平台分发**：Windows 仅作开发验证；生产目标为银河麒麟 V11 x86_64。
- **打包态依赖**：在目标机器上仍需 `pip install -r requirements.txt` 或使用 DEB 内置 wheelhouse。
- **记忆层级** (`memory_tier`) 需显式开启（`config.yaml` 中 `memory_tier.enabled=true`），否则 `/search` 不注入短期 / 中期结果。

---

## License

MIT — 见仓库根目录 LICENSE 文件。
