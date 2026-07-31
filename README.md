# OS Agent Memory Engine

基于麒麟操作系统的 AI Agent 记忆引擎 —— 端侧轻量化混合检索与存储层。

## 项目定位

MemoryHub 是银河麒麟 OS 上 AI Agent 的"记忆系统"，让 AI 助手能记住用户偏好、学到工作流，下次自动复用。本项目实现其中的**混合检索**和**持久化存储**两层。

## 架构总览

```
┌──────────────────────────────────┐
│  OS Agent / 用户                  │
├──────────────────────────────────┤
│  REST API (FastAPI)     ← 待建   │
├──────────────────────────────────┤
│  Embedding 抽象层        ✅ 完成  │  ← 麒麟 SDK 骨架 + Mock 降级
├──────────────────────────────────┤
│  混合检索引擎            ✅ 完成  │  ← BM25 + FAISS + Hybrid
├──────────────────────────────────┤
│  SQLite + FAISS 持久化   ✅ 完成  │  ← 重启数据不丢
└──────────────────────────────────┘
```

## 安装

```bash
pip install -r requirements.txt
```

依赖：`faiss-cpu`、`rank-bm25`、`numpy`、`jieba`

## 项目结构

```
memoryhub/                  # 核心 Python 包
├── app.py                  # FastAPI 应用入口
├── config.py               # 配置管理
├── adapter/                # OS Agent 接入适配层
│   ├── api.py              # REST 路由定义
│   ├── schemas.py          # 核心数据结构 (Pydantic)
│   ├── user_rule_schemas.py # 用户敏感规则 REST DTO
│   └── simulator.py        # OS Agent 模拟器
├── core/                   # 记忆核心逻辑
│   ├── ingestion/          # 多源数据接入 (清洗/标准化/质量评分)
│   ├── preference/         # 偏好记忆 (抽取/置信度/版本管理)
│   ├── knowledge/          # 知识记忆 (抽取/模板/工作流挖掘)
│   ├── fact/               # 事实记忆 (提取/冲突/标准化)
│   ├── forget/             # 精准遗忘模块
│   ├── conflict/           # 冲突处理 (检测/解决)
│   ├── safety/             # 安全过滤与精准遗忘
│   └── lifecycle/          # 记忆生命周期管理
├── retrieval/              # 混合检索引擎
│   ├── hybrid.py           # 混合检索入口
│   ├── vector_search.py    # FAISS 向量检索
│   ├── keyword_search.py   # BM25 关键词检索
│   ├── reranker.py         # 重排序
│   └── cache.py            # LRU 缓存
├── storage/                # 持久化存储层
│   ├── database.py         # SQLite + SQLAlchemy
│   ├── models.py           # ORM 模型
│   ├── vector_store.py     # FAISS 索引管理
│   └── evidence_store.py   # 证据链存储
├── llm/                    # LLM 抽象层
│   ├── base.py             # 抽象接口
│   ├── openai_client.py    # OpenAI 兼容 API
│   └── ollama_client.py    # Ollama 本地推理
└── embedding/              # Embedding 抽象层
    ├── base.py             # 抽象接口
    ├── kylin_client.py     # 麒麟 SDK 封装
    └── mock_client.py      # 开发用 Mock

console/                    # 管理控制台前端 (PyQt6)
├── main.py                 # 应用入口
├── api_client.py           # MemoryHub API 客户端
├── main_window.py          # 主窗口框架
├── pages/                  # 各功能页面
└── widgets/                # 可复用组件

evaluation/                 # 评测模块
├── metrics/
│   ├── preference_eval.py  # 偏好提取评测
│   ├── retrieval_eval.py   # 检索评测
│   ├── conflict_eval.py    # 冲突处理评测
│   └── latency_benchmark.py # 性能基准测试

docs/
├── ARCHITECTURE.md         # 项目整体架构可视化
├── INTERFACE.md            # 数据结构与接口规范文档
└── SAFETY_MODULE_TECHNICAL.md  # 安全模块技术文档
```

## 模块说明

### 1. Embedding 抽象层 (`src/embedding/`)

统一接口，自动选择最佳实现：

```python
from src.embedding import create_embedding_client

client = create_embedding_client(dim=768)
# Kylin OS + .so 存在 → KylinEmbeddingClient（真实语义向量）
# 其他环境 → MockEmbeddingClient（确定性随机向量，100ms 模拟延迟）

vec = client.embed("你好世界")        # → List[float] (768 维)
vecs = client.embed_batch(["文本1", "文本2"])  # 批量
```

| 实现 | 适用场景 | 向量来源 |
|------|---------|---------|
| `MockEmbeddingClient` | Windows/Mac 开发 | SHA256 + 随机种子，同文本同向量 |
| `KylinEmbeddingClient` | Kylin OS 部署 | ctypes 加载 `libkylin-coreai-embedding.so`，DBus 通信 |

麒麟 SDK 调用链（`KylinEmbeddingClient` 就绪后自动走此链路）：

```
embed(text)
  → text_embedding_init_session_no_connect()
  → text_embedding_init_model("ensemble-embd_gte-base_uint8-text")
  → text_embedding(session, text, &result)
  → embedding_result_get_vector_data()  → float[768]
  → embedding_result_destroy()
```

### 2. 存储层 (`src/memory_store.py`)

SQLite 持久化，接口简洁，重启自动恢复：

```python
from src.memory_store import MemoryStore

store = MemoryStore()                    # 默认 data/memories.db
store = MemoryStore(":memory:")          # 纯内存（测试用）

record = store.add("文本", embedding=vec)
records = store.get_all()                # 从 SQLite 加载
store.delete(record.id)                  # 同步删除
store.close()
```

- 向量以 `numpy.float32.tobytes()` 存为 BLOB
- 元数据以 JSON 存储
- WAL 模式，读写并发友好
- 线程安全（`threading.Lock`）

### 3. 检索引擎 (`src/search_engine.py`)

三路检索，可独立调用也可混合加权：

```python
from src.search_engine import MemorySearchEngine

engine = MemorySearchEngine(store, embedding_dim=768)
engine.build_index()                     # 构建 + 自动保存到磁盘
# 或
engine.load_index()                      # 从磁盘恢复（无需重建）

# BM25 关键词检索
engine.search_bm25("密码", top_k=3)

# FAISS 语义向量检索
engine.search_faiss("密码", query_vector, top_k=3)

# Hybrid 混合检索（BM25 0.3 + FAISS 0.7）
engine.search_hybrid("密码", query_vector, top_k=3)
```

| 检索通道 | 底层 | 擅长 |
|---------|------|------|
| BM25 | `rank-bm25` + `jieba` 分词 | 精确关键词匹配 |
| FAISS | `faiss-cpu` IndexFlatIP | 语义相似度搜索 |
| Hybrid | 加权融合（3:7） | 兼顾精确与语义 |

## 快速开始

```python
from src.embedding import create_embedding_client
from src.memory_store import MemoryStore
from src.search_engine import MemorySearchEngine

# 1. 初始化
emb = create_embedding_client(dim=768)
store = MemoryStore()

# 2. 写入数据
texts = [
    "我的系统登录密码是 Admin@123456",
    "公司 Wi-Fi 密码是 Kylin_Office_2024",
    "数据库 root 账号密码是 RootDB!Pass#2024",
]
for t in texts:
    store.add(content=t, embedding=emb.embed(t))

# 3. 构建索引
engine = MemorySearchEngine(store)
engine.build_index()

# 4. 搜索
query_vec = emb.embed("密码")
results = engine.search_hybrid("密码", query_vec, top_k=3)
for r in results:
    print(f"[{r['score']:.2f}] {r['content']}")
```

## 测试

```bash
# 集成测试（10 条假数据，5 个断言）
PYTHONIOENCODING=utf-8 python tests/test_search.py

# 安全模块测试
PYTHONIOENCODING=utf-8 python -m pytest tests/test_safety_gate.py tests/test_user_sensitive_rules.py -v
```

**安全边界**: 规则加载/校验、递归扫描、策略决策、全值脱敏、同快照复检、
用户自定义规则 Overlay、实例内结果认证、最小化 JSONL 审计链、REVIEW 加密隔离
和强制写入 Gate 已实现。
普通 SQLite/向量/证据算法仍是脚手架；实现时只能注册为 Gate 的受保护 sink，
不得接收原始事件或裸文本

# 验证持久化（模拟重启）
PYTHONIOENCODING=utf-8 python -c "
from src.memory_store import MemoryStore
store = MemoryStore()
print(f'从磁盘恢复: {len(store)} 条记录')
"
```

VS Code 调试：打开 `tests/test_search.py`，`F5` → 选"调试: test_search.py"。

## 与 MemoryHub 主线的对接计划

前端可通过 `/api/memory/safety/user-rules` CRUD 管理当前用户的敏感规则。
`mask_match` 遮盖命中片段，`drop_event` 跳过整条待记忆事件；matcher 只写不读并以
AES-256-GCM 加密。启用前需把独立的 32 字节随机密钥以 Base64 写入
`MEMORYHUB_USER_RULE_KEY`，由认证网关注入可信 `X-MemoryHub-User` 请求头，并向
`create_app()` 注入基于认证会话的 `user_rule_identity_resolver`；缺少 resolver
时管理接口默认失败关闭。

当前仓库的 `/api/memory/events` 和普通存储业务仍是脚手架。本次已提供
`UserRuleService.detector_provider()` 与 `SafetyWriteGate.from_user_rule_config()`
接线点；实现真实写入端点时必须通过该 Gate，规则才会在每次实际记忆写入中生效。

安全配置与密钥要求见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)，数据契约、
轮转/保留和平台权限边界见 [`docs/INTERFACE.md`](docs/INTERFACE.md)，完整验收矩阵
见 [`docs/SAFETY_ACCEPTANCE.md`](docs/SAFETY_ACCEPTANCE.md)。

| 层 | 当前状态 | 下一步 |
|----|---------|--------|
| Embedding 抽象 | ✅ Mock + Kylin 骨架 | 拿到 .so 后即插即用 |
| 存储 | ✅ SQLite + FAISS 落盘 | - |
| 检索 | ✅ BM25 + FAISS + Hybrid | Reranker、元数据过滤 |
| REST API | ❌ 待建 | FastAPI `/search` `/events` |

## License

MIT
