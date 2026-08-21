# Kylin MemoryHub（OS Agent Memory Engine）

基于麒麟操作系统的 AI Agent 记忆引擎 —— 端侧轻量化混合检索与存储层。

本仓库包含：

- `memoryhub`：Python/FastAPI 本地记忆服务，负责事件处理、偏好、知识、事实、检索、冲突和遗忘。
- `desktop-client`：Qt 5 原生桌面控制台（银河麒麟/Windows），21 个页面，可视化审计、演示与调参（详见 `desktop-client/README.md`）。
- `agent-integration`：统一 CLI、MCP 与 OpenCode Plugin 接入层；旧的重复集成目录已收敛。

## 项目定位

MemoryHub 是银河麒麟 OS 上 AI Agent 的"记忆系统"，让 AI 助手能记住用户偏好、学到工作流，下次自动复用。本项目实现其中的**混合检索**、**持久化存储**和**记忆生命周期管理**等核心能力。

## 架构总览

```
┌──────────────────────────────────┐
│  用户 / OS Agent / Qt 桌面客户端   │
├──────────────────────────────────┤
│  REST API (FastAPI)             │
├──────────────────────────────────┤
│  Embedding 抽象层        ✅ 完成  │  ← 麒麟 SDK（生产）+ Mock/降级
├──────────────────────────────────┤
│  混合检索引擎            ✅ 完成  │  ← Milvus（生产）BM25+FAISS（dev/test）
├──────────────────────────────────┤
│  SQLite + Milvus/FAISS 持久化 ✅  │  ← 重启数据不丢
└──────────────────────────────────┘
```

职责划分：

```text
OS Agent / Qt 桌面客户端
              │ HTTP JSON
              ▼
       FastAPI 本地后端（127.0.0.1:8099）
              │
              ▼
     记忆处理、SQLite、检索、安全门禁、向量索引
```

MemoryHub 负责真正的记忆读写、冲突处理和遗忘；客户端通过 REST API 访问，不应直接修改核心记忆数据库。

## 环境要求

- Windows 10/11 或银河麒麟 Linux
- Git
- Python 3.11+

## 安装

### 银河麒麟 DEB（x86_64）

```bash
sudo apt install ./kylin-memoryhub_0.1.0-8_amd64.deb
memoryhub-configure-opencode --current-user
```

安装包同时提供后端、Qt 桌面控制台、CLI/MCP 和 OpenCode 全局插件。OpenCode 配置会根据当前用户主目录自动写入 `~/.config/opencode/`，详见 [`packaging/linux/README.md`](packaging/linux/README.md)。

面向普通用户的下载、图形化安装和首次使用步骤见 [`docs/银河麒麟安装与使用手册.md`](docs/银河麒麟安装与使用手册.md)。

### 安装后端环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果项目中没有 `requirements.txt`，按照 `pyproject.toml` 安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

## 启动

### 启动后端

在仓库根目录打开 PowerShell 窗口：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1
```

后端默认监听 `http://127.0.0.1:8099`，FastAPI 接口文档：

```text
http://127.0.0.1:8099/docs
```

后端停止命令：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1
```

也可手动启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8099
```

## 项目结构

```
memoryhub/                  # 核心 Python 包
├── app.py                  # FastAPI 应用入口（create_app，4 个 router）
├── config.py               # 配置管理（dataclass + YAML + 环境变量）
├── adapter/                # OS Agent 接入适配层
│   ├── api.py              # 标准记忆 REST 路由（/api/memory）
│   ├── management_api.py   # 管理后台 API（状态流转/批量/健康/审计/隔离区/系统状态）
│   ├── agent_api.py        # Agent 演示适配层（step/replay/裁决，/api/agent）
│   ├── service.py          # MemoryService 最小垂直切片（无 LLM 降级路径）
│   ├── schemas.py          # 核心数据结构 (Pydantic)
│   ├── user_rule_schemas.py # 用户敏感规则 REST DTO
│   └── simulator.py        # OS Agent 模拟器
├── core/                   # 记忆核心逻辑
│   ├── processing.py       # 事件处理协调器（演示适配层）
│   ├── memory_write.py     # 统一持久化与索引同步（MemoryWriteService）
│   ├── ingestion/          # 多源数据接入 (清洗/标准化/质量评分/抽取重试)
│   ├── preference/         # 偏好记忆 (抽取/置信度/版本管理)
│   ├── knowledge/          # 知识记忆 (抽取/模板/工作流挖掘/合并)
│   ├── fact/               # 事实记忆 (三元组提取/归一化/准入/冲突)
│   ├── forget/             # 精准遗忘 (显式/自动遗忘/健康度)
│   ├── conflict/           # 冲突处理 (检测/解决)
│   ├── safety/             # 安全门禁 (检测/决策/脱敏/审计/隔离/用户规则)
│   └── lifecycle/          # 记忆生命周期管理
├── retrieval/              # 混合检索引擎
│   ├── milvus_hybrid.py    # Milvus 混合检索（生产唯一装配）
│   ├── hybrid.py           # 混合检索入口（dev/test 降级）
│   ├── vector_search.py    # FAISS 向量检索
│   ├── keyword_search.py   # BM25 关键词检索
│   ├── reranker.py         # 重排序
│   └── cache.py            # LRU 缓存
├── storage/                # 持久化存储层
│   ├── database.py         # SQLite + SQLAlchemy + Repository
│   ├── models.py           # ORM 模型
│   ├── vector_store.py     # FAISS 索引管理
│   ├── vector_engine/      # 向量引擎（faiss / milvus / milvus_mock / sparse）
│   ├── sync_service.py     # SQLite ↔ Milvus 写入同步与补偿
│   ├── compensation_task.py # pending 索引补偿任务
│   └── evidence_store.py   # 证据链存储
├── llm/                    # LLM 抽象层
│   ├── base.py             # 抽象接口
│   ├── openai_client.py    # 云端 OpenAI 兼容 API
├── embedding/              # Embedding 抽象层
│   ├── base.py             # 抽象接口
│   ├── kylin_client.py     # 麒麟 SDK 封装（生产）
│   ├── mock_client.py      # 开发用 Mock
└── safety_rules/           # 版本化声明式安全规则库（内置规则集 catalog）

desktop-client/             # Qt 5 原生桌面控制台（21 页，详见 desktop-client/README.md）

evaluation/                 # 评测模块
├── metrics/                # retrieval_eval / latency_benchmark / full_chain_benchmark（preference/conflict 为框架占位）
├── datasets/               # 检索评测数据集（dev/test/golden/latency + SHA256SUMS + 标注规范）
├── results/                # 评测结果与验收报告
└── run_*.py                # 评测驱动脚本（HTTP/延迟/Milvus 基准等）

docs/                       # 设计/验收/技术文档
scripts/                    # 服务启停脚本 + 环境自检（start/stop/verify）
agent-integration/          # 统一 CLI / MCP / OpenCode Plugin 接入
packaging/                  # systemd 用户服务与 DEB 独立安装包
third_party/                # 麒麟 SDK mock 动态库
tests/                      # 后端测试（约 700 用例）
```

## 模块说明

### 1. Embedding 抽象层 (`memoryhub/embedding/`)

统一接口，自动选择最佳实现：

```python
from memoryhub.embedding import create_embedding_client

client = create_embedding_client(dim=768)
# Kylin OS + .so 存在 → KylinEmbeddingClient（真实语义向量）
# 其他环境 → MockEmbeddingClient（确定性随机向量）

vec = client.embed("你好世界")        # → List[float]
vecs = client.embed_batch(["文本1", "文本2"])
```

| 实现 | 适用场景 | 向量来源 |
|------|---------|---------|
| `MockEmbeddingClient` | Windows/Mac 开发 | SHA256 + 随机种子，同文本同向量 |
| `KylinEmbeddingClient` | Kylin OS 部署 | ctypes 加载麒麟 embedding SDK |

### 2. 混合检索引擎 (`memoryhub/retrieval/`)

三路检索，可独立调用也可混合加权：

| 检索通道 | 底层 | 擅长 |
|---------|------|------|
| BM25 | `rank-bm25` + `jieba` 分词 | 精确关键词匹配 |
| FAISS | `faiss-cpu` IndexFlatIP | 语义相似度搜索 |
| Hybrid | 加权融合 | 兼顾精确与语义 |

生产模式下仅允许装配 `MilvusHybridRetriever`；FAISS / HybridRetriever 仅在 development/test 或显式故障诊断场景下作为降级路径保留。

### 3. 安全模块

规则加载/校验、递归扫描、策略决策、全值脱敏、同快照复检、用户自定义规则 Overlay、实例内结果认证、最小化 JSONL 审计链、REVIEW 加密隔离和强制写入 Gate 均已实现。安全配置与密钥要求见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)，数据契约见 [`docs/INTERFACE.md`](docs/INTERFACE.md)。

## 常用接口

| 方法 | 接口 | 作用 |
| --- | --- | --- |
| GET | /api/health | 健康检查 |
| POST | /api/agent/step | 执行一轮 Agent 对话 |
| POST | /api/agent/replay | 执行 JSON 回放 |
| POST | /api/agent/actions/{id}/decision | 用户裁决（事实/冲突/遗忘） |
| POST | /api/memory/events | 写入标准事件（安全门禁 + 抽取） |
| POST | /api/memory/search | 混合检索记忆候选 |
| POST | /api/memory/context | 生成可直接注入 prompt 的记忆上下文 |
| GET | /api/memory/preferences | 偏好记忆列表（scene/status 过滤） |
| GET | /api/memory/knowledge | 知识记忆列表（scene/knowledge_type/status 过滤） |
| GET | /api/memory/facts | 事实记忆列表（含 conflicts/evidence） |
| GET | /api/memory/conflicts | 冲突记录列表 |
| POST | /api/memory/conflicts/{id}/resolve | 冲突裁决 |
| POST | /api/memory/forget | 执行精准遗忘（NL/范围/ID + 预览） |
| GET | /api/memory/forget/history | 遗忘历史 |
| PUT | /api/memory/{type}/{id} | 统一更新偏好、知识或事实：内容/元数据、模板正文/步骤、客体、置信度、状态、版本谱系与证据链 |
| PATCH | /api/memory/memories/{id}/status | 兼容的单条状态流转入口；新客户端请使用统一 PUT 接口 |
| POST | /api/memory/memories/status | 批量状态流转 |
| DELETE | /api/memory/memories/{id}?hard=true | 物理删除 |
| GET | /api/memory/memories/health | 记忆健康度看板 |
| POST | /api/memory/lifecycle/auto-forget | 立即执行自动遗忘扫描 |
| GET | /api/memory/lifecycle/settings | 生命周期/遗忘阈值（只读） |
| CRUD | /api/memory/safety/user-rules | 用户自定义敏感规则（需 X-MemoryHub-User） |
| GET | /api/memory/safety/audit-logs | 安全审计日志（HMAC 哈希链） |
| GET | /api/memory/safety/quarantine | REVIEW 隔离区 |
| GET | /api/memory/system/status | 各子系统状态 |
| GET | /api/memory/system/config | 后端配置（非敏感项） |

详细参数以 Swagger 文档为准：`http://127.0.0.1:8099/docs`。

### 统一记忆更新接口

已有记忆的人工编辑统一使用 `PUT /api/memory/{type}/{id}`；`type` 为 `preference`、`knowledge` 或 `fact`。请求只需携带要修改的字段，写入将同步状态、置信度、版本/谱系、证据链及检索投影。

- 偏好：`text`、`preference_type`、`payload`、`scope`、`is_global`、`tags`、`extra_payload`、`parent_id`、`root_id`、`evidences` 等。
- 知识：`name`、`content`、`knowledge_type`、`steps`、`tools`、`template_body`、`parent_id`、`evidences` 等。
- 事实：`object_value`、`object_type`、`confidence`、`evidence_text` 或 `evidences` 等。

## 检查和测试

后端测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 提交代码前的约定

- 不要把数据库文件、向量索引、密钥和 .env 提交到 GitHub。
- 不要把未脱敏的工具调用原文直接暴露给外部客户端。
- 修改 API 响应时尽量保持已有字段兼容。
- 涉及记忆状态变化时，优先通过 Agent action 接口完成。
- 提交前至少运行后端测试。

## 当前限制

- 当前 Agent 默认以确定性规则编排，真实大模型接入沿用现有 Agent transport。
- 自动遗忘与生命周期检查已实现，但需要手动触发或由外部定时任务调用；应用本身不含调度器。
- 偏好/冲突评测为框架占位（`NotImplementedError`），检索评测与延迟/全链路基准已实现。
- 生产模式（`runtime.mode=production`）强制麒麟 Embedding SDK + Milvus 向量引擎，禁止 mock/FAISS 降级。
- 银河麒麟版本需要在目标机器上重新安装 Python 依赖。

## License

MIT
