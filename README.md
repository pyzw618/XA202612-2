# OS Agent Memory Engine

<<<<<<< HEAD
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
=======
面向 OS 智能体（Agent）的端侧记忆检索引擎原型，基于 **BM25 关键词检索 + FAISS 向量检索** 的混合搜索方案，在轻量环境下实现高召回率的记忆召回。

---

## 功能特性

- **双路混合检索**：BM25 负责关键词精确匹配，FAISS 负责语义向量相似度搜索。
- **统一搜索入口**：`MemorySearchEngine` 自动融合 BM25 与 FAISS 分数，按权重排序返回 Top-K。
- **Mock Embedding SDK**：内置模拟 Embedding 服务，保持与真实 SDK 一致的接口，方便离线验证。
- **可扩展存储**：`MemoryStore` 当前为内存存储，后续可无缝替换为 SQLite / 向量数据库。
- **记忆元数据支持**：每条记忆支持 `metadata` 字典，便于后续按标签过滤、分类管理。

---
>>>>>>> 481534d6dbac3fa568dac2655bdbe4753d4292d3

## 项目结构

```
OS_Agent_Memory_Engine/
<<<<<<< HEAD
├── requirements.txt
├── data/                          # 持久化文件（自动生成）
│   ├── memories.db                #   SQLite 数据库
│   ├── faiss.index                #   FAISS 向量索引
│   └── faiss.index.meta           #   id 映射表
├── src/
│   ├── embedding/                 # Embedding 抽象层
│   │   ├── base.py                #   BaseEmbeddingClient 抽象基类
│   │   ├── mock_client.py         #   Mock 实现（开发用，确定性随机向量）
│   │   ├── kylin_client.py        #   麒麟 SDK 实现（ctypes → .so → DBus）
│   │   └── __init__.py            #   create_embedding_client() 自动选择
│   ├── mock_embedding.py          # 向后兼容 re-export
│   ├── memory_store.py            # SQLite 持久化存储层
│   └── search_engine.py           # BM25 + FAISS + Hybrid 检索引擎
├── tests/
│   └── test_search.py             # 集成测试（10 条假数据）
└── .vscode/
    └── launch.json                # VS Code 调试配置
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

# 验证持久化（模拟重启）
PYTHONIOENCODING=utf-8 python -c "
from src.memory_store import MemoryStore
store = MemoryStore()
print(f'从磁盘恢复: {len(store)} 条记录')
"
```

VS Code 调试：打开 `tests/test_search.py`，`F5` → 选"调试: test_search.py"。

## 与 MemoryHub 主线的对接计划

| 层 | 当前状态 | 下一步 |
|----|---------|--------|
| Embedding 抽象 | ✅ Mock + Kylin 骨架 | 拿到 .so 后即插即用 |
| 存储 | ✅ SQLite + FAISS 落盘 | - |
| 检索 | ✅ BM25 + FAISS + Hybrid | Reranker、元数据过滤 |
| REST API | ❌ 待建 | FastAPI `/search` `/events` |
=======
├── src/
│   ├── __init__.py           # 包初始化
│   ├── memory_store.py       # 记忆数据存储层（MemoryRecord / MemoryStore）
│   ├── mock_embedding.py     # Mock Embedding SDK（随机向量 + 固定延迟）
│   └── search_engine.py      # BM25 + FAISS 双路检索引擎
├── tests/
│   ├── __init__.py           # 测试包初始化
│   └── test_search.py        # 端到端检索测试脚本
├── README.md                 # 项目说明文档
└── requirements.txt          # Python 依赖
```

---

## 安装依赖

```bash
pip install -r requirements.txt
```

依赖列表：

- `faiss-cpu>=1.7.4`
- `rank-bm25>=0.2.2`
- `numpy>=1.24.0`

---

## 快速使用

```python
from src.memory_store import MemoryStore
from src.mock_embedding import MockEmbeddingClient
from src.search_engine import MemorySearchEngine

# 1. 初始化
store = MemoryStore()
embed_client = MockEmbeddingClient(dim=768, latency=0.1)

# 2. 添加记忆
texts = [
    "我的系统登录密码是 Admin@123456",
    "公司 Wi-Fi 密码是 Kylin_Office_2024",
    "服务器 SSH 端口是 2222",
]
for text in texts:
    vec = embed_client.embed(text)
    store.add(content=text, embedding=vec)

# 3. 构建索引并搜索
engine = MemorySearchEngine(store, embedding_dim=768)
engine.build_index()

query = "密码"
query_vec = embed_client.embed(query)
results = engine.search_hybrid(query, query_vec, top_k=3)

for r in results:
    print(f"score={r['score']:.4f} -> {r['content']}")
```

---

## 运行测试

```bash
python tests/test_search.py
```

测试脚本会：

1. 生成 10 条 Mock 记忆数据；
2. 构建 BM25 + FAISS 双路索引；
3. 对多个查询分别执行 BM25、FAISS、Hybrid 检索；
4. 验证存储数量、向量维度、Embedding 确定性等核心断言。

---

## 核心模块说明

### `memory_store.py`

- `MemoryRecord`：单条记忆记录，包含 `id`、`content`、`embedding`、`created_at`、`metadata`。
- `MemoryStore`：提供 `add`、`add_batch`、`get_by_id`、`get_all`、`delete` 等接口。

### `mock_embedding.py`

- `MockEmbeddingClient`：模拟真实 Embedding SDK。
- 通过 SHA-256 哈希生成确定性种子，保证同一文本每次返回相同向量。
- 支持 `embed` 单条调用与 `embed_batch` 批量调用。

### `search_engine.py`

- `_simple_tokenize`：简易中英文分词器（生产环境建议替换为 jieba）。
- `BM25Retriever`：基于 `rank_bm25` 的全文检索器。
- `FaissRetriever`：基于 `faiss-cpu` 的向量检索器，使用 L2 归一化 + 内积实现余弦相似度。
- `MemorySearchEngine`：统一入口，支持 `search_bm25`、`search_faiss`、`search_hybrid`。

---

## 未来规划

- [ ] 接入真实麒麟 Embedding SDK，替换 Mock 实现。
- [ ] 支持索引增量更新，避免每次全量重建。
- [ ] 实现按 `id` 的精准遗忘操作。
- [ ] 基于 `created_at` 实现中短期记忆淘汰流转。
- [ ] 支持按 `metadata` 标签过滤搜索结果。
- [ ] 引入持久化存储（SQLite / JSON / 向量数据库）。
- [ ] 构建评测数据集，验证混合检索召回率 ≥ 85%。

---
>>>>>>> 481534d6dbac3fa568dac2655bdbe4753d4292d3

## License

MIT
