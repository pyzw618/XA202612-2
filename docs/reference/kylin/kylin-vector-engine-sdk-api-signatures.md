# libkysdk-vector-engine-client SDK 接口签名文档

**文档编号**：SIG-2026-08-02-002  
**日期**：2026-08-02  
**来源**：本地 `D:/project/libkysdk-vector-engine-client` + Gitee `openkylin/libkysdk-vector-engine-client` 分支 `openkylin/nile-sp2`  
**目标**：为 C API 桥接层封装提供完整 C++ 接口签名参考

> 本文档基于公开头文件和 demo 源码整理。实际封装时应以编译时的头文件为准。

---

## 一、核心概念

| 类型/概念 | 说明 |
|---|---|
| `VectorDB::Database` | 向量数据库客户端抽象基类 |
| `VectorDB::MilvusClientImpl` | 当前唯一可用的实现（Milvus 协议） |
| `VectorDB::CollectionSchema` | 集合（表）结构定义 |
| `VectorDB::FieldSchema` | 字段定义（id、文本、向量、稀疏向量） |
| `VectorDB::FieldData` | 字段数据（插入/查询时使用） |
| `VectorDB::IndexDesc` | 索引描述（向量索引、稀疏向量索引） |
| `VectorDB::SearchArguments` | 向量搜索参数 |
| `VectorDB::SearchResults` | 搜索结果 |
| `VectorDB::AnnSearchRequest` | 混合检索中的单路检索请求 |
| `VectorDB::RRFRanker` | Reciprocal Rank Fusion 融合排序器 |
| `VectorDB::Status` | 操作结果状态（成功/错误码/消息） |
| `VectorDB::ConnectParam` | 连接参数（app_id/host/port） |

---

## 二、Database 客户端生命周期

### 2.1 创建客户端

```cpp
namespace VectorDB {
    class Database {
    public:
        static std::shared_ptr<Database> Create();
        
        virtual Status Connect(const ConnectParam& connect_param) = 0;

        virtual Status Disconnect() = 0;
    };
}
```

**说明**：`Database::Create()` 当前只返回 `MilvusClientImpl` 实例。  
**参数**：
- `ConnectParam`：必须包含非空 `appId`；可用 host/port 构造函数指定服务地址

### 2.2 ConnectParam 结构

```cpp
class ConnectParam {
public:
    explicit ConnectParam(std::string appId);
    ConnectParam(std::string appId, const std::string& host, uint16_t port);
    
    std::string Uri() const;
    uint32_t ConnectTimeout() const;
    void SetConnectTimeout(uint32_t timeout);
    std::string AppId() const;
};
```

---

## 三、Collection 管理

### 3.1 创建集合（带完整 schema）

```cpp
virtual Status CreateCollection(
    const CollectionSchema& schema,
    const IndexDesc& index_desc
) = 0;
```

**说明**：创建集合并创建索引（可选）。  
**参数**：
- `schema`：集合结构
- `index_desc`：索引描述

### 3.2 快速创建集合

```cpp
virtual Status CreateCollection(
    const std::string& collection_name,
    int dim,
    bool auto_id,
    bool enable_dynamic_field
) = 0;
```

**说明**：快速创建只包含 id 和向量字段的集合。  
**参数**：
- `collection_name`：集合名
- `dim`：向量维度
- `auto_id`：是否自动生成 id
- `enable_dynamic_field`：是否开启动态字段

### 3.3 检查集合是否存在

```cpp
virtual Status HasCollection(
    const std::string& collection_name,
    bool& has
) = 0;
```

### 3.4 删除集合

```cpp
virtual Status DropCollection(
    const std::string& collection_name
) = 0;
```

### 3.5 加载/释放集合

```cpp
virtual Status LoadCollection(const std::string& collection_name) = 0;
virtual Status ReleaseCollection(const std::string& collection_name) = 0;
virtual Status GetLoadState(const std::string& collection_name, bool& is_loaded) = 0;
```

**说明**：Milvus 中搜索前必须 `LoadCollection`，否则数据不在内存中。

### 3.6 查看所有集合

```cpp
virtual Status ShowCollections(std::vector<std::string>& collections) = 0;
```

### 3.7 描述集合

```cpp
virtual Status DescribeCollection(
    const std::string& collection_name,
    CollectionDesc& collection_desc
) = 0;
```

---

## 四、CollectionSchema / FieldSchema

### 4.1 集合 Schema

```cpp
class CollectionSchema {
public:
    CollectionSchema(const std::string& name = "");
    
    const std::string& Name() const;
    CollectionSchema& SetName(const std::string& name);
    
    void AddField(const FieldSchema& field);
    const std::vector<FieldSchema>& Fields() const;
    
    // 动态字段
    CollectionSchema& SetDynamicFieldEnabled(bool enabled);
    bool IsDynamicFieldEnabled() const;
    
    // 描述
    CollectionSchema& SetDescription(const std::string& desc);
};
```

### 4.2 字段 Schema

```cpp
class FieldSchema {
public:
    FieldSchema(
        const std::string& name,
        DataType data_type,
        const std::string& description = ""
    );
    
    // 链式配置
    FieldSchema& WithDimension(int dim);        // 向量字段
    FieldSchema& WithMaxLength(int max_len);    // VARCHAR 字段
    FieldSchema& IsPrimaryKey(bool is_pk);      // 主键
    FieldSchema& IsAutoID(bool auto_id);        // 自增 id
    FieldSchema& IsNullable(bool nullable);     // 可空
    
    const std::string& Name() const;
    DataType Type() const;
};
```

### 4.3 数据类型枚举

```cpp
enum class DataType : int {
    NONE = 0,
    BOOL = 1,
    INT8 = 2,
    INT16 = 3,
    INT32 = 4,
    INT64 = 5,
    FLOAT = 10,
    DOUBLE = 11,
    STRING = 20,
    VARCHAR = 21,
    JSON = 23,
    FLOAT_VECTOR = 101,
    BINARY_VECTOR = 102,
    SPARSE_FLOAT_VECTOR = 104,
};
```

### 4.4 典型集合 Schema 示例（MemoryHub 用）

```cpp
CollectionSchema schema("memoryhub");
schema.AddField(FieldSchema("memory_id", DataType::VARCHAR, "id")
                .WithMaxLength(128)
                .IsPrimaryKey(true));
schema.AddField(FieldSchema("content", DataType::VARCHAR, "text")
                .WithMaxLength(4096));
schema.AddField(FieldSchema("dense_vector", DataType::FLOAT_VECTOR, "embedding")
                .WithDimension(768));
schema.AddField(FieldSchema("sparse_vector", DataType::SPARSE_FLOAT_VECTOR, "sparse"));
```

---

## 五、索引描述

### 5.1 IndexDesc

```cpp
class IndexDesc {
public:
    IndexDesc(
        const std::string& field_name = "",
        const std::string& index_name = "",
        IndexType index_type = IndexType::INVALID,
        MetricType metric_type = MetricType::INVALID
    );
    
    // 设置额外参数
    IndexDesc& AddExtraParam(const std::string& key, const std::string& value);
    
    const std::string& FieldName() const;
    const std::string& IndexName() const;
    IndexType IndexType() const;
    MetricType MetricType() const;
};
```

### 5.2 索引类型

```cpp
enum class IndexType : int {
    INVALID = 0,
    FLAT = 1,
    IVF_FLAT = 2,
    IVF_SQ8 = 3,
    IVF_PQ = 4,
    HNSW = 5,
    SPARSE_INVERTED_INDEX = 7,
    SPARSE_WAND = 8,
};
```

### 5.3 距离度量类型

```cpp
enum class MetricType : int {
    INVALID = 0,
    L2 = 1,
    IP = 2,
    COSINE = 3,
    HAMMING = 4,
    JACCARD = 5,
};
```

### 5.4 典型索引示例

```cpp
// 稠密向量索引：FLAT + COSINE
IndexDesc dense_index("dense_vector", "dense_idx", IndexType::FLAT, MetricType::COSINE);

// 稀疏向量索引：SPARSE_INVERTED_INDEX + IP
IndexDesc sparse_index("sparse_vector", "sparse_idx", IndexType::SPARSE_INVERTED_INDEX, MetricType::IP);
```

### 5.5 创建/删除索引

```cpp
virtual Status CreateIndex(
    const std::string& collection_name,
    const IndexDesc& index_desc
) = 0;

virtual Status DropIndex(
    const std::string& collection_name,
    const std::string& field_name
) = 0;

virtual Status DescribeIndex(
    const std::string& collection_name,
    const std::string& field_name,
    IndexDesc& index_desc
) = 0;
```

---

## 六、数据插入

### 6.1 字段数据类型

```cpp
typedef std::shared_ptr<FieldData> FieldDataPtr;

class Int64FieldData : public FieldData {
public:
    Int64FieldData(const std::string& name, const std::vector<int64_t>& data);
};

class VarCharFieldData : public FieldData {
public:
    VarCharFieldData(const std::string& name, const std::vector<std::string>& data);
};

class FloatVecFieldData : public FieldData {
public:
    FloatVecFieldData(const std::string& name, const std::vector<std::vector<float>>& data);
};

class SparseFloatVecFieldData : public FieldData {
public:
    SparseFloatVecFieldData(
        const std::string& name,
        const std::vector<std::vector<std::pair<uint32_t, float>>>& data
    );
};
```

### 6.2 插入数据

```cpp
virtual Status Insert(
    const std::string& collection_name,
    const std::vector<FieldDataPtr>& fields,
    DmlResults& results
) = 0;
```

**参数**：
- `collection_name`：集合名
- `fields`：字段数据数组，每个字段包含一批值
- `results`：返回插入结果，包含 id 列表

### 6.3 更新/删除

```cpp
virtual Status Upsert(
    const std::string& collection_name,
    const std::vector<FieldDataPtr>& fields,
    DmlResults& results
) = 0;

virtual Status Delete(
    const std::string& collection_name,
    const std::string& expression,
    DmlResults& results
) = 0;
```

---

## 七、向量搜索

### 7.1 单路向量搜索

```cpp
class SearchArguments {
public:
    SearchArguments(const std::string& collection_name, int top_k);
    
    SearchArguments& AddOutputField(const std::string& field_name);
    SearchArguments& SetExpression(const std::string& expression);  // 过滤条件
    SearchArguments& AddTargetVector(const std::string& field_name, std::vector<float>&& vector);
    SearchArguments& SetConsistencyLevel(ConsistencyLevel level);
};

class SearchResults {
public:
    const std::vector<SearchResultData>& Results() const;
};

class SearchResultData {
public:
    const IDArray& Ids() const;
    const std::vector<float>& Scores() const;
    FieldDataPtr OutputField(const std::string& field_name) const;
};

virtual Status Search(
    const SearchArguments& arguments,
    SearchResults& results,
    int timeout = 0
) = 0;
```

### 7.2 混合搜索（HybridSearch）

```cpp
class AnnSearchRequest {
public:
    AnnSearchRequest(const std::string& field_name, int top_k);
    
    AnnSearchRequest& AddTargetVector(const std::string& field_name, std::vector<float>&& vector);
    AnnSearchRequest& AddTargetVector(
        const std::string& field_name,
        std::vector<std::pair<uint32_t, float>>&& sparse_vector
    );
    AnnSearchRequest& SetExpression(const std::string& expression);
    AnnSearchRequest& AddOutputField(const std::string& field_name);
};

class RRFRanker {
public:
    RRFRanker();
    RRFRanker(int k);  // RRF 参数 k，默认 60
};

virtual Status HybridSearch(
    SearchResults& results,
    const std::string& collection_name,
    const std::vector<AnnSearchRequest>& requests,
    const RRFRanker& ranker,
    int top_k,
    const std::vector<std::string>& output_fields
) = 0;
```

**说明**：`HybridSearch` 是路线 B 的核心，可同时检索稠密向量和稀疏向量，并用 RRF 融合结果。

### 7.3 查询（结构化条件）

```cpp
class QueryArguments {
public:
    QueryArguments();
    QueryArguments& SetCollectionName(const std::string& name);
    QueryArguments& AddOutputField(const std::string& field_name);
    QueryArguments& SetExpression(const std::string& expression);
};

class QueryResults {
public:
    FieldDataPtr GetFieldByName(const std::string& name) const;
    const std::vector<FieldDataPtr>& OutputFields() const;
};

virtual Status Query(
    const QueryArguments& arguments,
    QueryResults& results,
    int timeout = 0
) = 0;
```

---

## 八、状态与错误处理

### 8.1 Status

```cpp
class Status {
public:
    Status();
    Status(StatusCode code, const std::string& msg);
    
    bool IsOk() const;
    StatusCode Code() const;
    const std::string& Message() const;
};

enum class StatusCode : int {
    Success = 0,
    UnknownError = 1,
    NotConnected = 2,
    NotSupported = 3,
    // ... 其他错误码
};
```

**所有 API 调用后必须检查 `status.IsOk()`。**

---

## 九、典型 HybridSearch 示例

```cpp
auto client = VectorDB::Database::Create();
VectorDB::ConnectParam param("test-app-id", "127.0.0.1", 19530);
client->Connect(param);

// 第一路：稠密向量
VectorDB::AnnSearchRequest dense_request("dense_vector", 10);
dense_request.AddTargetVector("dense_vector", std::move(query_dense_vector));

// 第二路：稀疏向量
VectorDB::AnnSearchRequest sparse_request("sparse_vector", 10);
sparse_request.AddTargetVector("sparse_vector", std::move(query_sparse_vector));

// RRF 融合
VectorDB::RRFRanker ranker;
VectorDB::SearchResults results;
auto status = client->HybridSearch(
    results,
    "memoryhub",
    {dense_request, sparse_request},
    ranker,
    10,
    {"memory_id", "content", "dense_vector", "sparse_vector"}
);

if (!status.IsOk()) {
    std::cerr << "HybridSearch failed: " << status.Message() << std::endl;
}

for (const auto& result : results.Results()) {
    auto ids = result.Ids().IntIDArray();  // 或 StrIDArray()，取决于主键类型
    auto scores = result.Scores();
    auto content = std::static_pointer_cast<VectorDB::VarCharFieldData>(
        result.OutputField("content")
    )->Data();
    
    for (size_t i = 0; i < ids.size(); ++i) {
        std::cout << "ID: " << ids[i] << " Score: " << scores[i] 
                  << " Content: " << content[i] << std::endl;
    }
}
```

---

## 十、C API 桥接层设计建议

由于 `VectorDB::Database` 是 C++ 类，不能直接被 ctypes 调用，需要封装一层 C 函数。最小接口参见：

`2026-08-02_milvus_c_api_minimal_interface.md`

### 10.1 设计原则

1. **句柄 opaque**：用 `void*` 表示 `Database` 实例，避免暴露 C++ 类型
2. **错误码 int 化**：所有操作返回 `int`，`0` 表示成功，非零对应 `StatusCode`
3. **JSON 传复杂数据**：搜索结果序列化为 JSON 字符串，由 Python 解析
4. **资源配对**：每个 `create`/`connect` 必须有对应的 `disconnect`/`destroy`
5. **内存释放明确**：返回的字符串必须由调用方释放，提供 `free_buffer(void*)` 函数

### 10.2 推荐导出函数

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
    int vector_engine_drop_collection(void* engine, const char* name);

    // 数据
    int vector_engine_insert(void* engine, const char* collection,
                             const char* id, const char* text,
                             const float* dense_vector, int dim);
    int vector_engine_delete(void* engine, const char* collection, const char* id);

    // 检索
    int vector_engine_hybrid_search(void* engine, const char* collection,
                                    const float* dense_vector, int dim,
                                    const uint32_t* sparse_indices,
                                    const float* sparse_values, int sparse_count,
                                    int top_k, char** out_json);

    // 工具
    void vector_engine_free_buffer(void* buffer);
    int vector_engine_get_last_error(void* engine, char** out_message);
}
```

---

## 十一、参考链接

- Gitee 混合检索示例：[exampleHybridSearch.cpp](https://gitee.com/openkylin/libkysdk-vector-engine-client/blob/openkylin/nile-sp2/demo/client/exampleHybridSearch.cpp)
- 本地头文件：`D:/project/libkysdk-vector-engine-client/include/kysdk-vector-engine-client/`
- 本地实现：`D:/project/libkysdk-vector-engine-client/src/impl/MilvusClientImpl.cpp`
- 集成方案：`2026-08-02_kylin_embedding_vector_engine_integration_plan.md`
- 环境交接清单：`2026-08-02_kylin_environment_handoff_checklist.md`
- 最小 C API 接口：`2026-08-02_milvus_c_api_minimal_interface.md`
