# OS Agent Memory Engine

面向 OS 智能体（Agent）的端侧记忆检索引擎原型，基于 **BM25 关键词检索 + FAISS 向量检索** 的混合搜索方案，在轻量环境下实现高召回率的记忆召回。

---

## 功能特性

- **双路混合检索**：BM25 负责关键词精确匹配，FAISS 负责语义向量相似度搜索。
- **统一搜索入口**：`MemorySearchEngine` 自动融合 BM25 与 FAISS 分数，按权重排序返回 Top-K。
- **Mock Embedding SDK**：内置模拟 Embedding 服务，保持与真实 SDK 一致的接口，方便离线验证。
- **可扩展存储**：`MemoryStore` 当前为内存存储，后续可无缝替换为 SQLite / 向量数据库。
- **记忆元数据支持**：每条记忆支持 `metadata` 字典，便于后续按标签过滤、分类管理。

---

## 项目结构

```
OS_Agent_Memory_Engine/
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

## License

MIT
