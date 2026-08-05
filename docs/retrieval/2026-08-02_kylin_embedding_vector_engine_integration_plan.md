# 麒麟原生 Embedding + 向量引擎接入方案

**文档编号**：PLN-2026-08-02-001  
**日期**：2026-08-02  
**状态**：待评审（基于无真实麒麟 OS 环境的前提，优先完成 SDK 适配与文档，真实环境测试由他人执行）  
**目标分支**：`dev_improve`  
**关联仓库**：
- `kylin-coreai-embedding`（文本向量化 SDK）
- `libkysdk-vector-engine-client`（Milvus 向量数据库 SDK）

> **重要前提**：当前执行者没有真实麒麟 OS 环境。因此本计划将工作重心调整为：
> 1. **SDK 适配层**：在通用环境（Windows/Linux）完成 Python 抽象、ctypes 桥接、Mock 实现；
> 2. **完整文档**：为后续在麒麟环境测试的人员提供充足信息（接口签名、编译步骤、环境 checklist、验证命令）；
> 3. **可交付代码**：保证非麒麟环境可运行 mock 链路，麒麟环境只需替换 `.so` 即可启用真实链路。

---

## 一、目标

### 1.1 总体目标

将 MemoryHub 当前的检索链路：

```text
Mock/Kylin Embedding → FAISS 稠密向量 + BM25 关键词 → Python 层 Hybrid 融合
```

升级为**可切换的、面向麒麟原生 SDK 的检索链路**：

```text
kylin-coreai-embedding（文本→768 维向量）
        ↓
libkysdk-vector-engine-client / Milvus（稠密向量 + 稀疏向量 + HybridSearch + RRF）
        ↓
MemoryHub SearchResponse
```

### 1.2 分阶段目标

由于当前执行者**没有真实麒麟 OS 环境**，本次工作按以下两阶段交付：

| 阶段 | 责任人 | 目标 |
|---|---|---|
| **阶段 1：SDK 适配与 Mock 链路** | 当前执行者 | 完成 Python 抽象层、ctypes 桥接、Mock `.so`、单元测试、文档；保证在 Windows/Linux 可运行 |
| **阶段 2：真实环境验证与性能测试** | 麒麟环境测试人员 | 按本文档 checklist 编译/部署 SDK，替换 `.so` 后验证真实链路，执行性能基准 |

### 1.3 文档目标

本文档必须包含足够信息，使得**从未参与本项目的人**拿到真实麒麟环境后，能在 1 天内完成部署并跑通端到端测试。

---

## 二、路线 B 技术架构

### 2.1 整体数据流

```text
┌─────────────────────┐
│   OS Agent / 用户    │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│  MemoryHub Adapter  │  REST API / FastAPI
│  (memoryhub/adapter) │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   Embedding 抽象层   │  选择 Kylin / Mock / OpenAI
│  memoryhub/embedding │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│  向量存储抽象层        │  选择 Milvus(Kylin SDK) / FAISS
│  memoryhub/storage/vector_engine  │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│  kylin-coreai-embedding  │  文本 → 稠密向量 (768d)
│  （DBus / GObject / .so）  │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ libkysdk-vector-engine-client │  Milvus Client (C++ / gRPC)
│    稠密向量 + 稀疏向量 + RRF   │
└─────────────────────┘
```

### 2.2 与当前实现的关键差异

| 维度 | 当前 MemoryHub（路线 A） | 麒麟原生链路（路线 B） |
|---|---|---|
| Embedding | `MockEmbeddingClient` / `KylinEmbeddingClient` | 同名，但要求真实 `kylin-coreai-embedding` SDK |
| 向量引擎 | `FAISS` 本地文件索引 | `Milvus` 服务端 / 本地模式 |
| 关键词路 | `BM25 + jieba` Python 实现 | `Milvus` 稀疏向量（Sparse Float Vector） |
| 混合检索 | Python 层加权融合 | Milvus `HybridSearch` + `RRFRanker` |
| 检索返回 | 仅 memory_id + 分数 | 可携带原始文本、向量、元数据 |
| 适用环境 | 任意平台（Mock） | 麒麟 OS + .so + Milvus 服务 |

---

## 三、当前状态盘点

### 3.1 已存在且可直接复用的模块

| 模块 | 路径 | 状态 | 说明 |
|---|---|---|---|
| Embedding 抽象基类 | `memoryhub/embedding/base.py` | ✅ 可用 | `embed`, `embed_batch`, `get_dimension`, `is_available` |
| Embedding 工厂 | `memoryhub/embedding/__init__.py` | ✅ 可用 | `create_embedding_client` 自动选择 Kylin/Mock |
| Kylin Embedding Python 封装 | `memoryhub/embedding/kylin_client.py` | ⚠️ 需验证 | API 名称与 SDK 一致，但未在真实环境验证 |
| Mock Embedding | `memoryhub/embedding/mock_client.py` | ✅ 可用 | 用于本地开发与测试 |
| 配置管理 | `memoryhub/config.py` | ✅ 可用 | 需扩展 `EmbeddingConfig` / `StorageConfig` |
| 检索抽象 | `memoryhub/retrieval/hybrid.py` | ✅ 可扩展 | 需要新增 `MilvusHybridRetriever` 实现 |
| 评测脚本 | `evaluation/run_retrieval_eval.py` | ✅ 可用 | 只需增加 provider/engine 配置 |

### 3.2 需要新建或大幅改动的模块

| 模块 | 路径 | 工作量 | 说明 |
|---|---|---|---|
| 向量引擎抽象基类 | `memoryhub/storage/vector_engine/base.py` | 中 | 定义统一的 `insert`, `search`, `hybrid_search`, `delete`, `persist` 接口 |
| FAISS 向量引擎实现 | `memoryhub/storage/vector_engine/faiss_engine.py` | 中 | 将现有 `vector_store.py` 逻辑迁移到抽象实现 |
| Milvus 向量引擎实现 | `memoryhub/storage/vector_engine/milvus_engine.py` | 大 | 封装 `libkysdk-vector-engine-client` C++ SDK |
| C++ SDK ctypes 桥接 | `memoryhub/storage/vector_engine/_milvus_ctypes.py` | 大 | 加载 `.so`、定义结构体、回调函数 |
| 检索层 | `memoryhub/retrieval/milvus_hybrid.py` | 大 | 基于 Milvus HybridSearch 的检索器 |
| App 初始化 | `memoryhub/app.py` | 中 | 根据配置选择 FAISS / Milvus 引擎 |
| 配置 | `memoryhub/config.py` | 小 | 增加 `vector_engine` 配置段 |
| 测试 | `tests/` | 大 | 需要 Mock SDK 测试、真实环境测试 |

### 3.3 已知阻塞点

1. **C++ SDK 只有 Milvus 实现可用**：`SwClientImpl` 是空壳（全部返回 `NOT_SUPPORTED`），所以路线 B 只能对接 Milvus。
2. **Windows 无法运行真实链路**：`kylin-coreai-embedding` 依赖 DBus + GObject，`libkysdk-vector-engine-client` 是 C++ 库，两者都需要 Linux/Kylin 环境。
3. **本地缺少 SDK 源码**：`kylin-coreai-embedding` 仓库未在本地克隆，需要先在目标环境编译或安装 `.so`。
4. **当前 Python 环境为 Windows**：性能测试最终需要在麒麟设备或 Linux 容器内执行。
5. **当前 `memoryhub/embedding/kylin_client.py` 引用不存在的 API**：代码中调用 `text_embedding_init_session_no_connect()`，但公开头文件中只有 `text_embedding_create_session()` + `text_embedding_init_session()`。需要在适配阶段修复。

### 3.4 无真实麒麟环境的工作策略

由于当前没有麒麟 OS 环境，本次工作必须采用 **"接口先行、Mock 兜底、文档完整"** 的策略：

1. **SDK 接口签名先行**  
   从 Gitee 源码和本地 `libkysdk-vector-engine-client` 仓库中提取所有 C/C++ 接口签名，整理为 `docs/2026-08-02_kylin_sdk_api_signatures.md`，作为后续 ctypes 封装和真实环境验证的依据。

2. **最小 C API 桥接层**  
   在 `libkysdk-vector-engine-client` 仓库中新增 `c_api_bridge.cpp`，只导出 MemoryHub 需要的最少函数（create/connect/create_collection/insert/hybrid_search/destroy）。  
   - 在 Windows 上先验证 CMake 能编译；
   - 在 Linux 上验证 `.so` 可加载；
   - 在麒麟环境上验证真实 Milvus 可连接。

3. **Mock `.so` 实现**  
   提供两个 Mock 动态库：
   - `libkylin-coreai-embedding-mock.so`：输入文本返回固定 768 维向量（可选 sleep 模拟延迟）；
   - `libkysdk-vector-engine-client-mock.so`：内存中模拟 Milvus 行为，支持 insert/search/hybrid_search。  
   这两个 mock 保证非麒麟环境可以跑通全部单元测试和端到端检索测试。

4. **Python 层完全可切换**  
   通过 `memoryhub/config.py` 中的 `provider` 配置，在同一份 Python 代码里切换：
   - `embedding.provider = kylin | mock`
   - `vector_engine.provider = milvus | faiss | mock`
   麒麟环境测试人员只需改配置 + 替换 `.so` 路径即可启用真实链路。

5. **测试交接文档**  
   在 `2026-08-02_kylin_environment_handoff_checklist.md` 中提供：
   - 麒麟环境准备步骤；
   - SDK 编译命令；
   - Milvus 部署命令；
   - 验证命令；
   - 常见问题排查。

---

## 四、详细执行步骤（按无真实环境重新排序）

### 阶段 1：SDK 接口签名提取与文档化（2 天）

本阶段不依赖麒麟环境，在 Windows/Linux 上即可完成，产出是后续所有适配工作的基础。

#### 4.1.1 提取 Embedding SDK 接口签名

基于 Gitee 仓库 `openkylin/kylin-coreai-embedding` 的源码和测试文件，整理完整 C API 签名。

重点关注：
- 头文件路径（`include/` 下所有 `.h`）
- `TextEmbeddingSession` 类型定义
- `EmbeddingResult` 结构体及 getter 函数
- 同步/异步 API 差异
- 模型列表相关 API（`text_embedding_get_model_list`）
- 错误码定义
- 资源释放函数

输出文件：`2026-08-02_kylin_embedding_sdk_api_signatures.md`

#### 4.1.2 提取 Vector Engine SDK 接口签名

基于本地 `D:/project/libkysdk-vector-engine-client` 仓库和 Gitee 源码，整理：
- `Database` 类所有 public 方法签名
- `CollectionSchema`、`FieldSchema`、`FieldData` 继承体系
- `SearchArguments`、`SearchResults`、`AnnSearchRequest`、`RRFRanker` 用法
- `ConnectParam` 默认值
- 错误处理模式（`Status.IsOk()`）
- `HybridSearch` 完整参数顺序和类型

输出文件：`2026-08-02_kylin_vector_engine_sdk_api_signatures.md`

#### 4.1.3 输出最小可用 C API 清单

结合 MemoryHub 需求，确定必须从 C++ 类封装为 C 函数的接口：

```cpp
extern "C" {
    // 生命周期
    void* vector_engine_create();
    int vector_engine_connect(void* engine, const char* app_id, const char* host, int port);
    int vector_engine_disconnect(void* engine);
    void vector_engine_destroy(void* engine);

    // Collection
    int vector_engine_create_collection(void* engine, const char* name, int dim);
    int vector_engine_load_collection(void* engine, const char* name);
    int vector_engine_release_collection(void* engine, const char* name);

    // 数据操作
    int vector_engine_insert(void* engine, const char* collection,
                             const char* id, const char* text,
                             const float* dense_vector, int dim);

    // 检索
    int vector_engine_hybrid_search(void* engine, const char* collection,
                                    const float* dense_vector, int dim,
                                    const uint32_t* sparse_indices,
                                    const float* sparse_values, int sparse_count,
                                    int top_k,
                                    char** out_json);  // JSON 数组 [{id, score, text}, ...]
}
```

输出文件：`2026-08-02_milvus_c_api_minimal_interface.md`

> **交付标准**：任何人拿到这三份文档，能在不看源码的情况下知道要封装哪些函数、参数含义、返回值格式。

---

### 阶段 2：最小 C API 桥接层（3~5 天）

#### 4.2.1 在 `libkysdk-vector-engine-client` 仓库新增 C 桥接文件

新增文件：
- `c_api_bridge.h`
- `c_api_bridge.cpp`
- 修改 `CMakeLists.txt` 增加 `libkysdk-vector-engine-client-capi.so` 编译目标

桥接层职责：
1. 把 `std::shared_ptr<VectorDB::Database>` 的 C++ 对象包装为 `void*`
2. 把 C++ 字符串/`std::vector` 转换为 C 指针
3. 把 `SearchResults` 序列化为 JSON 字符串（便于 Python 解析）
4. 所有错误码用 int 返回，0 表示成功

#### 4.2.2 在 Windows/Linux 上验证编译

由于当前环境是 Windows，先用 CMake 验证项目能编译：

```bash
cd D:/project/libkysdk-vector-engine-client
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
# Windows 下可能无法完整编译，但需验证 CMake 配置和头文件依赖
```

在 Linux 容器/WSL 中验证完整编译：

```bash
sudo apt install cmake g++ libgrpc++-dev protobuf-compiler
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j4
# 确认生成 libkysdk-vector-engine-client-capi.so
```

#### 4.2.3 处理 Milvus 依赖

C++ SDK 本身依赖 Milvus gRPC 客户端。在真实麒麟环境需要：
- Milvus 服务端运行（standalone 或 cluster）
- SDK 编译时链接 grpc++/protobuf

在测试/开发环境可使用：
- Milvus Lite（Python 内嵌，无需独立服务）
- Milvus Standalone Docker

> **文档要求**：在 `2026-08-02_kylin_environment_handoff_checklist.md` 中写明 Milvus 部署命令。

---

### 阶段 3：Mock SDK 实现（2~3 天）

本阶段确保非麒麟环境可以跑通全部测试。

#### 4.3.1 Embedding Mock `.so`

文件：`third_party/kylin-mock/embedding_mock.c`（或放在 `libkysdk-vector-engine-client` 仓库内）

功能：
- 导出与真实 `libkylin-coreai-embedding.so` 完全相同的 C API
- `text_embedding(...)` 返回固定 768 维向量（文本 hash 确定性）
- 可选 `sleep(latency)` 模拟真实推理延迟
- 不依赖 DBus/GObject，可在 Windows/Linux 编译

编译产物：`libkylin-coreai-embedding-mock.so` / `.dll`

#### 4.3.2 Vector Engine Mock `.so`

文件：`third_party/kylin-mock/vector_engine_mock.c`

功能：
- 导出与 `libkysdk-vector-engine-client-capi.so` 完全相同的 C API
- 在内存中维护 `collection → {id, text, dense_vector}` 映射
- `hybrid_search` 实现：稠密向量做余弦相似度，稀疏向量做关键词匹配，RRF 融合
- 不依赖 Milvus，不依赖 gRPC

编译产物：`libkysdk-vector-engine-client-capi-mock.so` / `.dll`

#### 4.3.3 测试 Mock 可加载

在 Python 中验证：

```python
from ctypes import CDLL
lib = CDLL("./libkysdk-vector-engine-client-capi-mock.so")
engine = lib.vector_engine_create()
# test-app-id is a non-sensitive mock fixture; production gets app_id from configuration.
assert lib.vector_engine_connect(engine, b"test-app-id", b"127.0.0.1", 19530) == 0
```

---

### 阶段 4：Python 抽象层实现（3~4 天）

#### 4.4.1 向量引擎抽象基类

文件：`memoryhub/storage/vector_engine/base.py`

```python
class BaseVectorEngine(ABC):
    @abstractmethod
    def insert(self, memory_id: str, text: str, vector: list[float], metadata: dict) -> None: ...
    @abstractmethod
    def search(self, query_vector: list[float], top_k: int, filters: dict | None = None) -> list[SearchResult]: ...
    @abstractmethod
    def hybrid_search(self, dense_vector: list[float], sparse_terms: list[tuple[int, float]], top_k: int) -> list[SearchResult]: ...
    @abstractmethod
    def delete(self, memory_id: str) -> None: ...
    @abstractmethod
    def persist(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
```

#### 4.4.2 FAISS 实现迁移

文件：`memoryhub/storage/vector_engine/faiss_engine.py`

- 将现有 `vector_store.py` 逻辑迁移到 `FAISSVectorEngine`
- 保持与旧接口兼容
- 作为默认 fallback，确保现有测试不中断

#### 4.4.3 Milvus 引擎实现

文件：`memoryhub/storage/vector_engine/milvus_engine.py`

- 加载 `libkysdk-vector-engine-client-capi.so` 或 `-mock.so`
- 实现 `insert`、`hybrid_search`、`delete`、`persist`、`close`
- 把稀疏向量生成逻辑放在 Python 层（`jieba` 分词 + TF 权重）

#### 4.4.4 引擎工厂

文件：`memoryhub/storage/vector_engine/__init__.py`

```python
def create_vector_engine(provider: str, **kwargs) -> BaseVectorEngine:
    if provider == "faiss":
        return FAISSVectorEngine(**kwargs)
    elif provider == "milvus":
        return MilvusVectorEngine(**kwargs)
    elif provider == "milvus_mock":
        return MilvusVectorEngine(so_path=".../libkysdk-vector-engine-client-capi-mock.so", **kwargs)
    else:
        raise ValueError(f"unknown vector_engine provider: {provider}")
```

---

### 阶段 5：检索层实现（2~3 天）

#### 4.5.1 Milvus Hybrid 检索器

文件：`memoryhub/retrieval/milvus_hybrid.py`

```python
class MilvusHybridRetriever:
    def __init__(self, engine: BaseVectorEngine, embedding_fn, ...):
        self.engine = engine
        self.embedding_fn = embedding_fn

    def search(self, request: SearchRequest) -> SearchResponse:
        dense_vector = self.embedding_fn(request.query)
        sparse_terms = self._build_sparse_vector(request.query)
        results = self.engine.hybrid_search(dense_vector, sparse_terms, request.top_k)
        return self._format_response(results)
```

#### 4.5.2 稀疏向量生成策略

使用 `jieba` 分词 + 词频作为稀疏向量：

```python
def _build_sparse_vector(self, text: str) -> list[tuple[int, float]]:
    tokens = jieba.cut_for_search(text)
    # token → index 映射（可用固定 hash 或维护词表）
    # value = TF 或 BM25 权重
    return [(hash(token) & 0xFFFFFFFF, weight) for token, weight in ...]
```

> 注意：Milvus 稀疏向量要求 `uint32` 索引 + `float` 值，且索引不能重复。需要定义词表或 hash 冲突处理策略。

---

### 阶段 6：Embedding 层验证与增强（1~2 天）

文件：`memoryhub/embedding/kylin_client.py`

- 确认当前 ctypes 加载逻辑与 SDK 接口一致
- 增加 `so_path` 可配置
- 增加异步 API 支持（可选）
- 增加错误码日志（不暴露原始文本）
- 提供 `kylin_mock` 模式：使用 `libkylin-coreai-embedding-mock.so`

---

### 阶段 7：App 配置与初始化改造（1~2 天）

文件：`memoryhub/config.py` 和 `memoryhub/app.py`

新增配置项：

```yaml
embedding:
  provider: kylin_mock  # kylin | kylin_mock | mock
  kylin:
    so_path: /usr/lib/libkylin-coreai-embedding.so
    model_name: ensemble-embd_gte-base_uint8-text
    dim: 768
  mock:
    dim: 768
    latency: 0.0

vector_engine:
  provider: milvus_mock  # faiss | milvus | milvus_mock
  app_id: <provided-by-deployment-platform>  # required for milvus/milvus_mock; use test-app-id in mock tests
  so_path: /usr/lib/libkysdk-vector-engine-client-capi.so
  host: 127.0.0.1
  port: 19530
  collection: memoryhub
  dimension: 768
  metric: cosine
  faiss:
    index_path: data/vector_index
```

`app.py` 根据 `provider` 初始化对应引擎。

---

### 阶段 8：测试体系（2~3 天）

#### 4.8.1 单元测试

- `tests/test_vector_engine/test_faiss_engine.py`
- `tests/test_vector_engine/test_milvus_mock_engine.py`
- `tests/test_retrieval/test_milvus_hybrid.py`

所有测试使用 mock `.so`，不依赖麒麟环境。

#### 4.8.2 端到端测试

- `tests/test_search_milvus_mock.py`：通过 `/api/memory/search` 走 Milvus mock 链路

#### 4.8.3 真实环境测试脚本（为测试人员准备）

- `scripts/verify_kylin_environment.py`：检测 `.so` 是否存在、Milvus 是否可连接
- `scripts/run_milvus_real_smoke_test.py`：在麒麟环境跑一次完整写入+检索

---

### 阶段 9：性能测试基准（与阶段 8 并行，1~2 天）

#### 4.9.1 实现 `latency_benchmark.py`

文件：`evaluation/metrics/latency_benchmark.py`

```python
class LatencyBenchmark:
    def benchmark_search(self, queries: list[str], iterations: int = 100) -> LatencyResult:
        # warm-up
        # 循环计时
        # 计算 P50/P95/P99/QPS
```

#### 4.9.2 新增驱动脚本

- `evaluation/run_milvus_mock_benchmark.py`：在 mock 环境下跑基准，验证代码路径
- `evaluation/run_milvus_kylin_benchmark.py`：在真实麒麟环境下跑基准（测试人员使用）

> mock 基准的延迟不具真实参考价值，但用于验证性能测试脚本本身正确。

---

### 阶段 10：真实环境验证（由测试人员执行，1~2 天）

#### 4.10.1 环境准备

按 `2026-08-02_kylin_environment_handoff_checklist.md` 执行：

1. 克隆并编译 `kylin-coreai-embedding`，安装 `.so`
2. 编译 `libkysdk-vector-engine-client` + `c_api_bridge.cpp`
3. 部署 Milvus（standalone Docker）
4. 配置 Python 环境，安装 MemoryHub 依赖

#### 4.10.2 验证命令

```bash
# 验证 embedding SDK
python -c "from memoryhub.embedding import create_embedding_client; c=create_embedding_client(provider='kylin'); print(c.embed('测试')[:5])"

# 验证 vector engine SDK
export MEMORYHUB_VECTOR_ENGINE_APP_ID="<provided-by-deployment-platform>"
python scripts/verify_kylin_environment.py --app_id "$MEMORYHUB_VECTOR_ENGINE_APP_ID"

# 跑端到端冒烟测试
python scripts/run_milvus_real_smoke_test.py --app_id "$MEMORYHUB_VECTOR_ENGINE_APP_ID"

# 跑性能基准
python evaluation/run_milvus_kylin_benchmark.py --app_id "$MEMORYHUB_VECTOR_ENGINE_APP_ID" --memory_count 10000
```

#### 4.10.3 问题反馈与修复

测试人员记录问题后，当前执行者远程修复代码并重新提交。

---

## 五、关键文件变更清单

| 操作 | 路径 | 说明 |
|---|---|---|
| 新增 | `2026-08-02_kylin_embedding_vector_engine_integration_plan.md` | 本方案文档 |
| 新增 | `2026-08-02_kylin_embedding_sdk_api_signatures.md` | Embedding SDK 接口签名文档 |
| 新增 | `2026-08-02_kylin_vector_engine_sdk_api_signatures.md` | Vector Engine SDK 接口签名文档 |
| 新增 | `2026-08-02_milvus_c_api_minimal_interface.md` | 最小 C API 接口文档 |
| 新增 | `2026-08-02_kylin_environment_handoff_checklist.md` | 麒麟环境测试交接清单 |
| 新增 | `third_party/kylin-mock/embedding_mock.c` | Embedding Mock `.so` 源码 |
| 新增 | `third_party/kylin-mock/vector_engine_mock.c` | Vector Engine Mock `.so` 源码 |
| 新增 | `memoryhub/storage/vector_engine/__init__.py` | 向量引擎工厂 |
| 新增 | `memoryhub/storage/vector_engine/base.py` | 抽象基类 |
| 新增 | `memoryhub/storage/vector_engine/faiss_engine.py` | FAISS 实现 |
| 新增 | `memoryhub/storage/vector_engine/milvus_engine.py` | Milvus 实现 |
| 新增 | `memoryhub/storage/vector_engine/_milvus_ctypes.py` | ctypes 桥接 |
| 新增 | `memoryhub/retrieval/milvus_hybrid.py` | Milvus 混合检索器 |
| 新增 | `tests/test_vector_engine/` | 向量引擎测试 |
| 新增 | `tests/test_retrieval/test_milvus_hybrid.py` | Milvus 检索测试 |
| 新增 | `evaluation/run_milvus_benchmark.py` | Milvus 性能基准 |
| 修改 | `memoryhub/storage/vector_store.py` | 标记为 legacy，或迁移到 faiss_engine |
| 修改 | `memoryhub/config.py` | 增加 vector_engine 配置 |
| 修改 | `memoryhub/app.py` | 根据配置选择引擎 |
| 修改 | `memoryhub/retrieval/hybrid.py` | 改名为 legacy_hybrid 或保留为 FAISS 专用 |
| 修改 | `memoryhub/embedding/kylin_client.py` | 验证并修复真实环境 bug |
| 修改 | `evaluation/run_retrieval_eval.py` | 增加 `--engine milvus` 选项 |
| 修改 | `requirements.txt` | 增加 pybind11 / ctypes 相关依赖（如选方案 B） |
| 外部 | `libkysdk-vector-engine-client/c_api_bridge.cpp` | 新增 C 封装层 |
| 外部 | `libkysdk-vector-engine-client/CMakeLists.txt` | 增加 capi 动态库编译目标 |

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| C++ SDK 桥接复杂 | 高 | 先用 ctypes + 最小 C 封装，避免 pybind11；必要时可降级为 FAISS |
| 真实麒麟环境 unavailable | 高 | 提供 mock `.so`，先在 Windows/Linux 上跑通逻辑；真实环境测试延后 |
| Milvus 服务端部署复杂 | 中 | 使用 Milvus Lite 或 standalone Docker 容器 |
| 稀疏向量生成效果不佳 | 中 | 保留 BM25 作为 fallback，HybridSearch 用 jieba + TF 稀疏向量 |
| RRF 与当前加权融合结果不一致 | 中 | 两套检索器并行，对比效果后再切换默认 |
| 性能不如预期 | 中 | 测试不同索引类型和参数，保留调优空间 |
| 内存泄漏 / 段错误 | 高 | 所有 C 接口必须配对应释放函数；valgrind 检查 C++ 桥接层 |

---

## 七、建议的推进顺序（按无真实环境调整）

```text
Week 1：SDK 接口与 C 桥接层
  ├── 输出 Embedding SDK 接口签名文档
  ├── 输出 Vector Engine SDK 接口签名文档
  ├── 输出最小 C API 接口文档
  ├── 在 libkysdk-vector-engine-client 新增 c_api_bridge.cpp / h
  ├── 修改 CMakeLists.txt 增加 capi 编译目标
  └── 在 Windows/Linux 上验证 C 桥接层可编译

Week 2：Mock SDK + Python 抽象层
  ├── 实现 libkylin-coreai-embedding-mock.so
  ├── 实现 libkysdk-vector-engine-client-capi-mock.so
  ├── 验证 ctypes 可加载两个 mock .so
  ├── 实现 memoryhub/storage/vector_engine/ 抽象层
  ├── 迁移 FAISS 到 FAISSVectorEngine
  └── 实现 MilvusVectorEngine（基于 mock .so）

Week 3：检索层 + App 集成 + 单元测试
  ├── 实现 MilvusHybridRetriever
  ├── 改造 app.py / config.py 支持 provider 切换
  ├── 增强 KylinEmbeddingClient（支持 mock 模式）
  ├── 编写向量引擎单元测试
  ├── 编写 Milvus Hybrid 检索测试
  └── 实现 latency_benchmark.py

Week 4：文档 + 性能测试脚本 + 交接准备
  ├── 输出 kylin_environment_handoff_checklist.md
  ├── 实现 evaluation/run_milvus_mock_benchmark.py
  ├── 实现 evaluation/run_milvus_kylin_benchmark.py
  ├── 在 mock 环境下跑通检索评测 + 性能基准
  └── 整理代码、提交、合并到 dev_improve

Week 5+（由麒麟环境测试人员执行）
  ├── 按 checklist 准备麒麟环境
  ├── 编译真实 SDK 和 C 桥接层
  ├── 部署 Milvus
  ├── 改配置启用真实 provider
  ├── 跑通端到端测试
  └── 输出真实性能基准报告
```

---

## 八、验收标准

### 阶段 1 验收标准（当前执行者，无真实麒麟环境可完成）

1. **接口文档完整**：`2026-08-02_kylin_embedding_sdk_api_signatures.md`、`2026-08-02_kylin_vector_engine_sdk_api_signatures.md`、`2026-08-02_milvus_c_api_minimal_interface.md` 三份文档存在且可指导 ctypes 封装。
2. **C API 桥接层可编译**：`libkysdk-vector-engine-client` 能编译出 `libkysdk-vector-engine-client-capi.so`（在 Linux/WSL 验证）。
3. **Mock `.so` 可加载**：`libkylin-coreai-embedding-mock.so` 和 `libkysdk-vector-engine-client-capi-mock.so` 可在 Windows/Linux 被 ctypes 加载，并返回预期结果。
4. **Python 抽象层可切换**：`config.yaml` 中 `embedding.provider` 和 `vector_engine.provider` 可组合切换，不修改业务代码。
5. **单元测试通过**：`pytest tests/test_vector_engine/` 和 `pytest tests/test_retrieval/test_milvus_hybrid.py` 全部通过。
6. **端到端测试通过**：`/api/memory/search` 在 `milvus_mock` + `kylin_mock` 配置下可返回正确结果。
7. **性能测试脚本可跑**：`evaluation/run_milvus_mock_benchmark.py` 能输出 P50/P95/P99 和 QPS（mock 数值不具真实参考意义，但脚本路径正确）。
8. **交接文档完整**：`2026-08-02_kylin_environment_handoff_checklist.md` 包含环境准备、编译、部署、验证、排错全部步骤。

### 阶段 2 验收标准（麒麟环境测试人员）

1. 在麒麟设备上，`create_embedding_client(provider="kylin")` 可获取真实 768 维向量。
2. 在麒麟设备上，`create_vector_engine(provider="milvus", app_id="<provided-by-deployment-platform>")` 可连接真实 Milvus 并完成 HybridSearch。
3. `/api/memory/search` 在 `kylin` + `milvus` 配置下返回正确结果，与 `mock` 链路结果格式一致。
4. `evaluation/run_milvus_kylin_benchmark.py` 可输出 P50/P95/P99 延迟和 QPS。
5. 在 10K 记忆规模下，真实 Milvus 路线 P95 延迟 ≤ 350ms（目标）。
6. 提供 FAISS vs Milvus 对比报告。

---

## 九、下一步动作

当前执行者可立即开始：

1. **提取 SDK 接口签名文档**：基于现有 Gitee 源码和本地 `libkysdk-vector-engine-client` 仓库。
2. **实现最小 C API 桥接层**：在 `libkysdk-vector-engine-client` 新增 `c_api_bridge.cpp` 和 CMake 目标。
3. **实现 Mock `.so`**：保证非麒麟环境可跑测试。
4. **实现 Python 向量引擎抽象层**：先让 `milvus_mock` 链路跑通。

需要与麒麟环境测试人员同步：

1. 确认目标麒麟设备或容器规格；
2. 确认 Milvus 部署方式（Docker standalone / Milvus Lite / 其他）；
3. 确认测试规模（1K / 10K / 100K 记忆）。

是否现在开始执行 **Week 1：SDK 接口签名与 C 桥接层**？
