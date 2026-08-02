# kylin-coreai-embedding SDK 接口签名文档

**文档编号**：SIG-2026-08-02-001  
**日期**：2026-08-02  
**来源**：Gitee `openkylin/kylin-coreai-embedding` 分支 `openkylin/nile-sp2`  
**目标**：为 Python ctypes 封装提供完整接口签名参考

> 本文档基于 `TestTextEmbedding.cpp` 示例源码和 SDK 调用流程整理。真实头文件可能包含更多函数，封装时应以实际编译出的头文件为准。

---

## 一、核心概念

| 类型/概念 | 说明 |
|---|---|
| `TextEmbeddingSession` | Embedding 会话句柄，所有操作基于该会话 |
| `EmbeddingResult` | 单次推理结果，包含错误码、向量数据、向量长度 |
| `EmbeddingModelList` | 模型列表信息，用于查询可用模型 |
| `_EmbeddingModelInfo` | 单个模型信息（名称、维度、能力等） |
| 模型名称 | 默认文本模型：`ensemble-embd_gte-base_uint8-text`，输出 768 维 |
| 通信方式 | DBus + GObject（Linux/Kylin 环境） |

---

## 二、生命周期管理

### 2.1 创建会话（不连接后端）

```cpp
int text_embedding_init_session_no_connect(TextEmbeddingSession** session);
```

**说明**：`no_connect` 版本不主动连接 embedding 后端服务，适用于 mock 测试或需要手动控制连接的场景。  
**参数**：
- `session`：输出参数，返回创建的会话指针

**返回值**：
- `0` 或 `true`：成功
- 其他：失败

### 2.2 销毁会话

```cpp
void text_embedding_destroy_session(TextEmbeddingSession** session);
```

**说明**：释放会话资源，调用后 `session` 置空。  
**参数**：
- `session`：会话指针的指针

### 2.3 获取模型列表

```cpp
const EmbeddingModelList* text_embedding_get_model_list(
    TextEmbeddingSession* session,
    void* reserved
);
```

**说明**：查询当前会话支持的模型列表。  
**参数**：
- `session`：会话句柄
- `reserved`：保留参数，通常传 `nullptr`

**返回值**：模型列表指针，无需释放（由 SDK 管理）

### 2.4 释放模型列表

```cpp
void embedding_model_info_destroy(char* model_info);
```

> 注意：此函数名称可能用于释放 `text_embedding_get_model_info` 返回的字符串，需以头文件为准。

---

## 三、模型操作

### 3.1 初始化模型

```cpp
int text_embedding_init_model(
    TextEmbeddingSession* session,
    const char* model_name
);
```

**说明**：在会话中加载指定模型。  
**参数**：
- `session`：会话句柄
- `model_name`：模型名称，如 `ensemble-embd_gte-base_uint8-text`

**返回值**：
- `0` 或 `true`：成功
- 其他：失败

### 3.2 获取模型信息（字符串形式）

```cpp
int text_embedding_get_model_info(
    TextEmbeddingSession* session,
    char** model_info
);
```

**说明**：返回 JSON 格式的模型信息字符串。  
**参数**：
- `session`：会话句柄
- `model_info`：输出参数，返回字符串指针，调用方需释放

**释放函数**：`embedding_model_info_destroy(char* model_info)`

### 3.3 模型信息结构体操作

```cpp
int embedding_model_list_get_count(
    const EmbeddingModelList* model_list,
    int* error_code
);

const _EmbeddingModelInfo* embedding_model_list_get_model(
    const EmbeddingModelList* model_list,
    int index,
    void* reserved
);

const char* embedding_model_info_get_model_name(
    const _EmbeddingModelInfo* model_info,
    void* reserved
);

int embedding_model_info_get_model_dim(
    const _EmbeddingModelInfo* model_info,
    void* reserved
);
```

---

## 四、同步推理

### 4.1 文本向量化

```cpp
int text_embedding(
    TextEmbeddingSession* session,
    const char* text,
    EmbeddingResult** result
);
```

**说明**：将输入文本转换为稠密向量。  
**参数**：
- `session`：会话句柄
- `text`：输入文本（UTF-8 编码）
- `result`：输出参数，返回推理结果指针

**返回值**：
- `true` / `1`：调用成功（不代表结果无错误，需检查 `result` 内部错误码）
- `false` / `0`：调用失败

### 4.2 获取结果错误码

```cpp
int embedding_result_get_error_code(EmbeddingResult* result);
```

**说明**：获取推理结果的错误码，`0` 表示成功。  
**参数**：
- `result`：推理结果指针

### 4.3 获取结果错误信息

```cpp
const char* embedding_result_get_error_message(EmbeddingResult* result);
```

**说明**：获取错误描述字符串。  
**参数**：
- `result`：推理结果指针

### 4.4 获取向量数据

```cpp
float* embedding_result_get_vector_data(EmbeddingResult* result);
```

**说明**：获取向量数据指针。  
**参数**：
- `result`：推理结果指针

**返回值**：指向 `float` 数组的指针，数组长度由 `embedding_result_get_vector_length` 返回

### 4.5 获取向量长度

```cpp
int embedding_result_get_vector_length(EmbeddingResult* result);
```

**说明**：获取向量维度，默认应为 `768`。  
**参数**：
- `result`：推理结果指针

### 4.6 释放结果

```cpp
void embedding_result_destroy(EmbeddingResult** result);
```

**说明**：释放推理结果内存，调用后 `result` 置空。  
**参数**：
- `result`：结果指针的指针

---

## 五、异步推理

### 5.1 异步推理

```cpp
// 回调函数类型
typedef void (*EmbeddingResultCallback)(EmbeddingResult* result, void* callback_user_data);

int text_embedding_async(
    TextEmbeddingSession* session,
    const char* text,
    EmbeddingResultCallback callback,
    void* callback_user_data
);
```

**说明**：异步执行文本向量化，结果通过回调函数返回。  
**参数**：
- `session`：会话句柄
- `text`：输入文本
- `callback`：结果回调函数
- `callback_user_data`：用户自定义数据，原样传给回调

**返回值**：
- `true` / `1`：异步调用已提交
- `false` / `0`：提交失败

### 5.2 启用内部事件循环

```cpp
int text_embedding_enable_internal_event_loop(
    TextEmbeddingSession* session,
    bool enable
);
```

**说明**：启用 SDK 内部事件循环，使异步回调可在不依赖外部 GMainLoop 的情况下触发。  
**参数**：
- `session`：会话句柄
- `enable`：`true` 启用，`false` 关闭

---

## 六、模型列表示例 JSON

从 `TestTextEmbedding.cpp` 中的 mock 数据可以看到模型列表格式：

```json
{
  "models": [
    {
      "dim": 1024,
      "displayName": "cn-clip_512-uint8",
      "model": "ensemble-embd_cn-clip_512-uint8-text|embd_cn-clip_512-uint8-image",
      "modelName": "kylin-cn-clip_512-uint8-image",
      "model_capability": "IMAGE",
      "ondevice": true,
      "priority": 1
    },
    {
      "dim": 768,
      "displayName": "gte-base_uint8",
      "model": "ensemble-embd_gte-base_uint8-text",
      "modelName": "kylin-ensemble-embd_gte-base_uint8-text",
      "model_capability": "TEXT",
      "ondevice": true,
      "priority": 1
    }
  ]
}
```

---

## 七、Python ctypes 封装建议

### 7.1 加载 .so

```python
import ctypes
from ctypes import c_char_p, c_int, c_void_p, POINTER, c_float

lib = ctypes.CDLL("/usr/lib/libkylin-coreai-embedding.so")
```

### 7.2 定义不透明指针类型

```python
class TextEmbeddingSession(ctypes.c_void_p):
    pass

class EmbeddingResult(ctypes.c_void_p):
    pass

class EmbeddingModelList(ctypes.c_void_p):
    pass
```

### 7.3 绑定函数签名

```python
lib.text_embedding_init_session_no_connect.argtypes = [POINTER(TextEmbeddingSession)]
lib.text_embedding_init_session_no_connect.restype = c_int

lib.text_embedding_init_model.argtypes = [TextEmbeddingSession, c_char_p]
lib.text_embedding_init_model.restype = c_int

lib.text_embedding.argtypes = [TextEmbeddingSession, c_char_p, POINTER(POINTER(EmbeddingResult))]
lib.text_embedding.restype = c_int

lib.embedding_result_get_error_code.argtypes = [EmbeddingResult]
lib.embedding_result_get_error_code.restype = c_int

lib.embedding_result_get_vector_data.argtypes = [EmbeddingResult]
lib.embedding_result_get_vector_data.restype = POINTER(c_float)

lib.embedding_result_get_vector_length.argtypes = [EmbeddingResult]
lib.embedding_result_get_vector_length.restype = c_int

lib.embedding_result_destroy.argtypes = [POINTER(EmbeddingResult)]
lib.embedding_result_destroy.restype = None

lib.text_embedding_destroy_session.argtypes = [POINTER(TextEmbeddingSession)]
lib.text_embedding_destroy_session.restype = None
```

### 7.4 调用示例

```python
session = TextEmbeddingSession()
if not lib.text_embedding_init_session_no_connect(ctypes.byref(session)):
    raise RuntimeError("init session failed")

if not lib.text_embedding_init_model(session, b"ensemble-embd_gte-base_uint8-text"):
    raise RuntimeError("init model failed")

result = POINTER(EmbeddingResult)()
if not lib.text_embedding(session, b"测试文本", ctypes.byref(result)):
    raise RuntimeError("embedding call failed")

if lib.embedding_result_get_error_code(result) != 0:
    msg = lib.embedding_result_get_error_message(result)
    lib.embedding_result_destroy(ctypes.byref(result))
    raise RuntimeError(f"embedding failed: {msg}")

length = lib.embedding_result_get_vector_length(result)
data = lib.embedding_result_get_vector_data(result)
vector = [data[i] for i in range(length)]
lib.embedding_result_destroy(ctypes.byref(result))
lib.text_embedding_destroy_session(ctypes.byref(session))
```

---

## 八、MemoryHub 当前实现对照

MemoryHub 当前实现 `memoryhub/embedding/kylin_client.py` 已经包含上述大部分接口的封装：

- `text_embedding_init_session_no_connect` → `_init_session`
- `text_embedding_init_model` → 初始化模型
- `text_embedding` → `_call_embed`
- `embedding_result_get_vector_data` / `embedding_result_get_vector_length` → 提取向量
- `embedding_result_destroy` → 释放结果
- `text_embedding_destroy_session` → 析构中释放

**后续需要补充**：
1. 模型列表查询支持（用于动态选择模型）
2. 异步推理支持（`text_embedding_async`）
3. 错误码枚举整理
4. 非 768 维模型（如 cn-clip 1024 维）的适配

---

## 九、参考链接

- Gitee 测试源码：[TestTextEmbedding.cpp](https://gitee.com/openkylin/kylin-coreai-embedding/blob/openkylin/nile-sp2/test/TestTextEmbedding.cpp)
- MemoryHub 当前封装：`memoryhub/embedding/kylin_client.py`
- 集成方案：`docs/2026-08-02_kylin_embedding_vector_engine_integration_plan.md`
- 环境交接清单：`docs/2026-08-02_kylin_environment_handoff_checklist.md`
