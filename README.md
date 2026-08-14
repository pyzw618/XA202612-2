# Kylin MemoryHub（OS Agent Memory Engine）

基于麒麟操作系统的 AI Agent 记忆引擎 —— 端侧轻量化混合检索与存储层。

本仓库包含：

- `memoryhub`：Python/FastAPI 本地记忆服务，负责事件处理、偏好、知识、事实、检索、冲突和遗忘。
- `desktop-client`：Qt 5 原生桌面控制台（银河麒麟/Windows），可视化审计、演示与调参（详见 `desktop-client/README.md`）。

## 项目定位

MemoryHub 是银河麒麟 OS 上 AI Agent 的"记忆系统"，让 AI 助手能记住用户偏好、学到工作流，下次自动复用。本项目实现其中的**混合检索**、**持久化存储**和**记忆生命周期管理**等核心能力。

## 架构总览

```
┌──────────────────────────────────┐
│  OS Agent / 用户                  │
├──────────────────────────────────┤
│  REST API (FastAPI)              │
├──────────────────────────────────┤
│  Embedding 抽象层        ✅ 完成  │  ← 麒麟 SDK 骨架 + Mock 降级
├──────────────────────────────────┤
│  混合检索引擎            ✅ 完成  │  ← BM25 + FAISS + Hybrid / Milvus
├──────────────────────────────────┤
│  SQLite + FAISS 持久化   ✅ 完成  │  ← 重启数据不丢
└──────────────────────────────────┘
```

职责划分：

```text
OS Agent / 客户端
              │ HTTP JSON
              ▼
       FastAPI 本地后端（127.0.0.1:8000）
              │
              ▼
     记忆处理、SQLite、BM25、向量索引
```

MemoryHub 负责真正的记忆读写、冲突处理和遗忘；客户端通过 REST API 访问，不应直接修改核心记忆数据库。

## 环境要求

- Windows 10/11 或银河麒麟 Linux
- Git
- Python 3.11+

## 安装

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

后端默认监听 `http://127.0.0.1:8000`，FastAPI 接口文档：

```text
http://127.0.0.1:8000/docs
```

后端停止命令：

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1
```

也可手动启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8000
```

## 项目结构

```
memoryhub/                  # 核心 Python 包
├── app.py                  # FastAPI 应用入口
├── config.py               # 配置管理
├── adapter/                # OS Agent 接入适配层
│   ├── api.py              # 记忆查询和管理 REST 路由
│   ├── agent_api.py        # Agent 回放/裁决适配路由
│   ├── schemas.py          # 核心数据结构 (Pydantic)
│   ├── user_rule_schemas.py # 用户敏感规则 REST DTO
│   └── simulator.py        # OS Agent 模拟器
├── core/                   # 记忆核心逻辑
│   ├── processing.py       # 事件处理协调器（Agent 演示适配层）
│   ├── ingestion/          # 多源数据接入 (清洗/标准化/质量评分/重试)
│   ├── preference/         # 偏好记忆 (抽取/置信度/版本管理)
│   ├── knowledge/          # 知识记忆 (抽取/模板/工作流挖掘)
│   ├── fact/               # 事实记忆 (提取/冲突/标准化)
│   ├── forget/             # 精准遗忘模块
│   ├── conflict/           # 冲突处理 (检测/解决)
│   ├── safety/             # 安全过滤与精准遗忘
│   └── lifecycle/          # 记忆生命周期管理
├── retrieval/              # 混合检索引擎
│   ├── hybrid.py           # 混合检索入口
│   ├── milvus_hybrid.py    # Milvus 混合检索（生产）
│   ├── vector_search.py    # FAISS 向量检索
│   ├── keyword_search.py   # BM25 关键词检索
│   ├── reranker.py         # 重排序
│   └── cache.py            # LRU 缓存
├── storage/                # 持久化存储层
│   ├── database.py         # SQLite + SQLAlchemy
│   ├── models.py           # ORM 模型
│   ├── vector_store.py     # FAISS 索引管理
│   ├── vector_engine/      # 向量引擎（faiss / milvus / milvus_mock）
│   ├── sync_service.py     # 记忆写入同步
│   └── evidence_store.py   # 证据链存储
├── llm/                    # LLM 抽象层
│   ├── base.py             # 抽象接口
│   ├── openai_client.py    # OpenAI 兼容 API
│   └── ollama_client.py    # Ollama 本地推理
└── embedding/              # Embedding 抽象层
    ├── base.py             # 抽象接口
    ├── kylin_client.py     # 麒麟 SDK 封装
    └── mock_client.py      # 开发用 Mock

evaluation/                 # 评测模块
├── metrics/
│   ├── preference_eval.py  # 偏好提取评测
│   ├── retrieval_eval.py   # 检索评测
│   ├── conflict_eval.py    # 冲突处理评测
│   └── latency_benchmark.py # 性能基准测试

docs/                       # 设计/验收/技术文档
scripts/                    # 服务启动脚本
integrations/               # Qwen Agent 等 Agent 集成
claudecode-integration/     # Claude Code MCP 接入
opencode-integration/       # opencode MCP 接入
tests/                      # 后端测试
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
| POST | /api/agent/step | 执行一轮 Agent 对话 |
| POST | /api/agent/replay | 执行 JSON 回放 |
| POST | /api/agent/actions/{id}/decision | 用户裁决（事实/冲突/遗忘） |
| POST | /api/memory/events | 写入标准事件 |
| POST | /api/memory/search | 检索记忆候选 |
| GET | /api/memory/preferences | 偏好记忆列表 |
| GET | /api/memory/knowledge | 知识记忆列表 |
| GET | /api/memory/facts | 事实记忆列表 |
| GET | /api/memory/conflicts | 冲突记录列表 |
| POST | /api/memory/forget | 执行精准遗忘 |
| GET | /api/memory/forget/history | 遗忘历史 |

详细参数以 Swagger 文档为准：`http://127.0.0.1:8000/docs`。

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
- 自动遗忘调度、完整评测执行和部分安全看板仍在完善。
- 银河麒麟版本需要在目标机器上重新安装 Python 依赖。

## License

MIT
