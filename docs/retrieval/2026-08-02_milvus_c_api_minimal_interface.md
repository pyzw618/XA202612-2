# Milvus 向量引擎 C API 最小接口文档

**文档编号**：API-2026-08-02-001  
**日期**：2026-08-02  
**目标**：为 `libkysdk-vector-engine-client` C++ SDK 提供 ctypes 可调用的最小 C 函数接口  
**使用者**：Python 封装层 `memoryhub/storage/vector_engine/_milvus_ctypes.py`

> 本文档定义 MemoryHub 路线 B 实际需要的全部 C 函数。新增 `c_api_bridge.cpp` 时应严格按此实现。

---

## 一、设计原则

1. **C ABI 兼容**：所有导出函数使用 `extern "C"`，参数为 C 基本类型或指针
2. **opaque 句柄**：`vector_engine_t` 对 Python 侧是 `void*`，不暴露 C++ 类型
3. **错误码 int 化**：返回 `0` 表示成功，非零表示 `VectorDB::StatusCode`
4. **JSON 传递复杂数据**：搜索结果序列化为 JSON 字符串，Python 用 `json.loads()` 解析
5. **资源配对**：每个创建/连接必须有对应销毁/断开
6. **线程安全**：所有函数调用应假设在单线程或外部加锁条件下执行；必要时内部加锁

---

## 二、类型定义

```cpp
// c_api_bridge.h

#ifndef KYLIN_VECTOR_ENGINE_CAPI_H
#define KYLIN_VECTOR_ENGINE_CAPI_H

#ifdef __cplusplus
extern "C" {
#endif

// 不透明引擎句柄
typedef void* vector_engine_t;

// 搜索结果 JSON 释放函数
typedef void (*vector_engine_free_fn)(void* ptr);

#ifdef __cplusplus
}
#endif

#endif
```

---

## 三、生命周期函数

### 3.1 创建引擎实例

```cpp
vector_engine_t vector_engine_create();
```

**说明**：创建 `VectorDB::Database` 实例（当前为 `MilvusClientImpl`）。  
**返回值**：引擎句柄，失败返回 `NULL`。

### 3.2 连接 Milvus 服务

```cpp
int vector_engine_connect(vector_engine_t engine, const char* app_id, const char* host, int port);
```

**说明**：使用非空 `app_id`、host 和 port 连接 Milvus gRPC 服务。`app_id` 由测试/部署平台提供，不能用 collection 名或 user ID 猜测替代，也不得写入日志。
**参数**：
- `engine`：引擎句柄
- `app_id`：非空的 SDK 应用身份标识
- `host`：服务器地址，如 `"127.0.0.1"`
- `port`：服务器端口，如 `19530`

**返回值**：`0` 成功，非零失败。

### 3.3 断开连接

```cpp
int vector_engine_disconnect(vector_engine_t engine);
```

**说明**：断开与 Milvus 的连接。  
**返回值**：`0` 成功，非零失败。

### 3.4 销毁引擎实例

```cpp
void vector_engine_destroy(vector_engine_t engine);
```

**说明**：释放引擎实例，调用后句柄失效。  
**注意**：通常先 `disconnect` 再 `destroy`。

---

## 四、Collection 管理函数

### 4.1 创建集合

```cpp
int vector_engine_create_collection(
    vector_engine_t engine,
    const char* collection_name,
    int dim
);
```

**说明**：创建包含以下字段的集合：
- `memory_id`：VARCHAR(128)，主键
- `content`：VARCHAR(4096)，原始文本
- `dense_vector`：FLOAT_VECTOR(dim)
- `sparse_vector`：SPARSE_FLOAT_VECTOR

**参数**：
- `engine`：引擎句柄
- `collection_name`：集合名
- `dim`：稠密向量维度，如 `768`

**返回值**：`0` 成功，非零失败。

### 4.2 加载集合

```cpp
int vector_engine_load_collection(vector_engine_t engine, const char* collection_name);
```

**说明**：Milvus 搜索前必须加载集合到内存。  
**返回值**：`0` 成功，非零失败。

### 4.3 释放集合

```cpp
int vector_engine_release_collection(vector_engine_t engine, const char* collection_name);
```

**说明**：释放集合占用的内存。  
**返回值**：`0` 成功，非零失败。

### 4.4 删除集合

```cpp
int vector_engine_drop_collection(vector_engine_t engine, const char* collection_name);
```

**说明**：删除集合及所有数据。  
**返回值**：`0` 成功，非零失败。

---

## 五、数据操作函数

### 5.1 插入记忆

```cpp
int vector_engine_insert(
    vector_engine_t engine,
    const char* collection_name,
    const char* memory_id,
    const char* content,
    const float* dense_vector,
    int dim
);
```

**说明**：插入一条记忆。稀疏向量在桥接层内部根据 `content` 生成，**生成规则必须与附录 A 的分词规范逐位一致**（真实桥接层、mock 库、Python `sparse.py` 三方保持一致，否则 insert 与 query 的稀疏索引对不上）。
**参数**：
- `engine`：引擎句柄
- `collection_name`：集合名
- `memory_id`：记忆 ID，字符串主键
- `content`：原始文本内容
- `dense_vector`：稠密向量数组指针
- `dim`：向量维度

**返回值**：`0` 成功，非零失败。

### 5.2 删除记忆

```cpp
int vector_engine_delete(
    vector_engine_t engine,
    const char* collection_name,
    const char* memory_id
);
```

**说明**：按 `memory_id` 删除记忆。  
**返回值**：`0` 成功，非零失败。

---

## 六、检索函数

### 6.1 混合检索

```cpp
int vector_engine_hybrid_search(
    vector_engine_t engine,
    const char* collection_name,
    const float* dense_vector,
    int dim,
    const uint32_t* sparse_indices,
    const float* sparse_values,
    int sparse_count,
    int top_k,
    char** out_json
);
```

**说明**：对稠密向量和稀疏向量分别执行 ANN 检索，使用 Milvus `RRFRanker` 融合，返回 Top-K 结果。  
**参数**：
- `engine`：引擎句柄
- `collection_name`：集合名
- `dense_vector`：query 稠密向量
- `dim`：稠密向量维度
- `sparse_indices`：稀疏向量 token 索引数组（uint32）
- `sparse_values`：稀疏向量权重数组（float）
- `sparse_count`：稀疏向量非零元素个数
- `top_k`：返回结果数量
- `out_json`：输出参数，返回 JSON 字符串指针，调用方需用 `vector_engine_free_buffer` 释放

**返回 JSON 格式**：

```json
{
  "results": [
    {
      "memory_id": "mem_001",
      "content": "文本内容",
      "score": 0.95,
      "source": "hybrid"
    }
  ],
  "total": 1
}
```

**返回值**：`0` 成功，非零失败。

### 6.2 稠密向量单独检索（可选）

```cpp
int vector_engine_dense_search(
    vector_engine_t engine,
    const char* collection_name,
    const float* dense_vector,
    int dim,
    int top_k,
    char** out_json
);
```

**说明**：仅按稠密向量检索，用于调试或对比实验。  
**参数**：同 `vector_engine_hybrid_search`，无稀疏向量参数。

### 6.3 稀疏向量单独检索（可选）

```cpp
int vector_engine_sparse_search(
    vector_engine_t engine,
    const char* collection_name,
    const uint32_t* sparse_indices,
    const float* sparse_values,
    int sparse_count,
    int top_k,
    char** out_json
);
```

**说明**：仅按稀疏向量检索，用于调试或对比实验。

---

## 七、辅助函数

### 7.1 释放字符串缓冲区

```cpp
void vector_engine_free_buffer(void* buffer);
```

**说明**：释放 `out_json` 等函数返回的字符串缓冲区。  
**参数**：
- `buffer`：由 SDK 分配的字符串指针

### 7.2 获取最后一次错误信息

```cpp
int vector_engine_get_last_error(
    vector_engine_t engine,
    char** out_message
);
```

**说明**：获取最后一次失败的错误描述。  
**参数**：
- `engine`：引擎句柄
- `out_message`：输出参数，返回错误信息字符串，调用方需释放

**返回值**：`0` 成功，非零失败。

---

## 附录 A：稀疏向量分词规范（三端必须逐位一致）

真实桥接层（`c_api_bridge.cpp`）、mock 库（`third_party/kylin-mock/vector_engine_mock.c`）、Python 查询侧（`memoryhub/storage/vector_engine/sparse.py`）必须使用**完全相同**的稀疏向量生成规则：

1. **分词**：逐字符扫描文本。
   - ASCII 字母/数字（`[A-Za-z0-9]`）连写为一个 token，**保留原始大小写**（不做 tolower）；
   - 其余每个非 ASCII UTF-8 码点（如一个汉字）各自成为一个 token；
   - ASCII 空白与标点仅作分隔符，不产生 token。
2. **索引**：token 的 UTF-8 字节序列做 FNV-1a 32-bit hash（offset basis `2166136261`，prime `16777619`），结果为 uint32 索引。
3. **权重**：`token 出现次数 / 总 token 数`（归一化 TF）；同索引去重取最大权重。
4. **顺序**：输出按 uint32 索引升序排列。

> 2026-08-02 实现时的决策记录：方案文档原建议查询侧用 jieba 分词，但为保证 insert（C 侧）与 query（Python 侧）稀疏索引可比对，三方统一采用上述确定性规则，放弃 jieba。若未来任一端修改规则（例如改为统一转小写），三端必须同步修改并重建索引。

---

## 八、Python ctypes 绑定示例

```python
import ctypes
from ctypes import CDLL, c_char_p, c_float, c_int, c_uint32, c_void_p, POINTER

lib = CDLL("/path/to/libkysdk-vector-engine-client-capi.so")

# 类型别名
vector_engine_t = c_void_p

# 绑定函数
lib.vector_engine_create.restype = vector_engine_t
lib.vector_engine_create.argtypes = []

lib.vector_engine_connect.restype = c_int
lib.vector_engine_connect.argtypes = [vector_engine_t, c_char_p, c_char_p, c_int]

lib.vector_engine_create_collection.restype = c_int
lib.vector_engine_create_collection.argtypes = [vector_engine_t, c_char_p, c_int]

lib.vector_engine_load_collection.restype = c_int
lib.vector_engine_load_collection.argtypes = [vector_engine_t, c_char_p]

lib.vector_engine_insert.restype = c_int
lib.vector_engine_insert.argtypes = [
    vector_engine_t, c_char_p, c_char_p, c_char_p,
    POINTER(c_float), c_int
]

lib.vector_engine_hybrid_search.restype = c_int
lib.vector_engine_hybrid_search.argtypes = [
    vector_engine_t, c_char_p,
    POINTER(c_float), c_int,
    POINTER(c_uint32), POINTER(c_float), c_int,
    c_int, POINTER(c_char_p)
]

lib.vector_engine_free_buffer.restype = None
lib.vector_engine_free_buffer.argtypes = [c_void_p]

lib.vector_engine_destroy.restype = None
lib.vector_engine_destroy.argtypes = [vector_engine_t]
```

---

## 九、调用示例

```python
import json
import ctypes
from ctypes import byref, c_char_p, c_float, c_uint32

engine = lib.vector_engine_create()
if not engine:
    raise RuntimeError("create engine failed")

try:
    # test-app-id is a non-sensitive fixture; production uses the deployment-provided value.
    rc = lib.vector_engine_connect(engine, b"test-app-id", b"127.0.0.1", 19530)
    if rc != 0:
        raise RuntimeError(f"connect failed: {rc}")

    rc = lib.vector_engine_create_collection(engine, b"memoryhub", 768)
    if rc != 0:
        raise RuntimeError(f"create collection failed: {rc}")

    rc = lib.vector_engine_load_collection(engine, b"memoryhub")
    if rc != 0:
        raise RuntimeError(f"load collection failed: {rc}")

    # 插入
    dense = [0.1] * 768
    dense_arr = (c_float * 768)(*dense)
    rc = lib.vector_engine_insert(
        engine, b"memoryhub", b"mem_001", b"测试内容", dense_arr, 768
    )
    if rc != 0:
        raise RuntimeError(f"insert failed: {rc}")

    # 检索
    query_dense = [0.1] * 768
    query_dense_arr = (c_float * 768)(*query_dense)
    sparse_indices = [123, 456]
    sparse_values = [0.5, 0.3]
    idx_arr = (c_uint32 * 2)(*sparse_indices)
    val_arr = (c_float * 2)(*sparse_values)

    out_json = c_char_p()
    rc = lib.vector_engine_hybrid_search(
        engine, b"memoryhub",
        query_dense_arr, 768,
        idx_arr, val_arr, 2,
        5, byref(out_json)
    )
    if rc != 0:
        raise RuntimeError(f"search failed: {rc}")

    results = json.loads(out_json.value.decode("utf-8"))
    print(results)

    lib.vector_engine_free_buffer(out_json)

finally:
    lib.vector_engine_disconnect(engine)
    lib.vector_engine_destroy(engine)
```

---

## 十、参考文档

- 集成方案：`2026-08-02_kylin_embedding_vector_engine_integration_plan.md`
- Embedding SDK 接口签名：`2026-08-02_kylin_embedding_sdk_api_signatures.md`
- Vector Engine SDK 接口签名：`2026-08-02_kylin_vector_engine_sdk_api_signatures.md`
- 环境交接清单：`2026-08-02_kylin_environment_handoff_checklist.md`
