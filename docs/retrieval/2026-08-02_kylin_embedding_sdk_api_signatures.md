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

### 2.1 创建会话

```cpp
TextEmbeddingSession *text_embedding_create_session();
```

**说明**：创建 Embedding 会话实例，返回会话指针。此时会话尚未初始化。  
**返回值**：会话句柄，失败返回 `NULL`。

> **重要纠正**：公开头文件中没有 `text_embedding_init_session_no_connect()` 函数。测试文件 `TestTextEmbedding.cpp` 中的该函数是 mock 测试内部使用的，不是 SDK 公开 API。  
> MemoryHub 当前 `memoryhub/embedding/kylin_client.py` 引用了不存在的 `text_embedding_init_session_no_connect`，需要修复为 `text_embedding_create_session()` + `text_embedding_init_session()`。

### 2.2 初始化会话（连接后端）

```cpp
int text_embedding_init_session(TextEmbeddingSession *session);
```

**说明**：初始化会话，此函数会连接后端 embedding 服务。  
**参数**：
- `session`：通过 `text_embedding_create_session()` 创建的会话

**返回值**：错误码，`0` 表示成功，其他见 `CoreAiEmbeddingErrorCode`

### 2.3 销毁会话

```cpp
void text_embedding_destroy_session(TextEmbeddingSession **session);
```

**说明**：释放会话资源，调用后 `session` 置空。  
**参数**：
- `session`：会话指针的指针

### 2.4 获取模型列表

```cpp
EmbeddingModelList *text_embedding_get_model_list(
    TextEmbeddingSession *session,
    int *error_code
);
```

**说明**：查询当前会话支持的模型列表。  
**参数**：
- `session`：已初始化的会话句柄
- `error_code`：输出参数，返回错误码

**返回值**：模型列表指针，生命周期与 `session` 绑定，无需单独释放。

---

## 三、模型操作

### 3.1 初始化模型

```cpp
int text_embedding_init_model(TextEmbeddingSession *session,
                              const char *model_name);
```

**说明**：在已初始化的会话中加载指定模型。  
**参数**：
- `session`：已初始化的会话句柄
- `model_name`：模型名称，如 `ensemble-embd_gte-base_uint8-text`

**返回值**：错误码，`0` 表示成功

### 3.2 获取模型信息（已废弃，改用 model list）

```cpp
__attribute__((deprecated("Use func text_embedding_get_model_list instead")))
bool text_embedding_get_model_info(TextEmbeddingSession *session, char **model_info);
```

**说明**：已废弃，返回 JSON 字符串。新代码应使用 `text_embedding_get_model_list` + 模型信息 getter。

### 3.3 模型列表结构体操作

```cpp
int embedding_model_list_get_count(const EmbeddingModelList *model_list,
                                   int *error_code);

const EmbeddingModelInfo *embedding_model_list_get_model(
    const EmbeddingModelList *model_list, int index, int *error_code);

const char *embedding_model_info_get_model_name(
    const EmbeddingModelInfo *model_info, int *error_code);

int embedding_model_info_get_model_dim(
    const EmbeddingModelInfo *model_info, int *error_code);
```

**注意**：所有 getter 都通过 `error_code` 输出参数返回错误码，`0` 表示成功。返回的字符串/指针生命周期与 `model_list` / `model_info` 绑定。

---

## 四、同步推理

### 4.1 文本向量化

```cpp
bool text_embedding(TextEmbeddingSession *session, const char *text,
                    EmbeddingResult **result);
```

**说明**：将输入文本转换为稠密向量。  
**参数**：
- `session`：已初始化并加载模型的会话句柄
- `text`：输入文本（UTF-8 编码）
- `result`：输出参数，返回推理结果指针；调用前定义为 `EmbeddingResult *result = nullptr`，传入 `&result`

**返回值**：
- `true`：调用成功（不代表结果无错误，需检查 `result` 内部错误码）
- `false`：调用失败

### 4.2 获取结果错误码

```cpp
int embedding_result_get_error_code(EmbeddingResult *result);
```

**说明**：获取推理结果的错误码，`0` 表示成功。  
**参数**：
- `result`：推理结果指针

### 4.3 获取结果错误信息

```cpp
const char *embedding_result_get_error_message(EmbeddingResult *result);
```

**说明**：获取错误描述字符串，生命周期与 `result` 绑定。  
**参数**：
- `result`：推理结果指针

### 4.4 获取向量数据

```cpp
float *embedding_result_get_vector_data(EmbeddingResult *result);
```

**说明**：获取向量数据指针。  
**参数**：
- `result`：推理结果指针

**返回值**：指向 `float` 数组的指针，数组长度由 `embedding_result_get_vector_length` 返回

### 4.5 获取向量长度

```cpp
int embedding_result_get_vector_length(EmbeddingResult *result);
```

**说明**：获取向量维度，默认应为 `768`。  
**参数**：
- `result`：推理结果指针

### 4.6 释放结果

```cpp
void embedding_result_destroy(EmbeddingResult **result);
```

**说明**：释放推理结果内存，调用后 `result` 置空。仅同步接口需要。  
**参数**：
- `result`：结果指针的指针

---

## 五、错误码定义

```cpp
typedef enum : int {
    /*< @deprecated 请使用 COREAI_EMBEDDING_SUCCESS */
    COREAI_EMBEDDING_SUCESS = 0,
    /*< @brief 成功 */
    COREAI_EMBEDDING_SUCCESS = 0,
    COREAI_EMBEDDING_INPUT_ERROR,
    COREAI_EMBEDDING_INIT_ERROR,
    COREAI_EMBEDDING_CONNECTION_ERROR,
    COREAI_EMBEDDING_RUNTIME_ERROR,
    COREAI_EMBEDDING_ERROR_UNKNOWN = 99,
} CoreAiEmbeddingErrorCode;
```

**注意**：枚举中同时存在拼写错误 `SUCESS` 和正确 `SUCCESS`，两者都等于 `0`。

## 六、异步推理

### 6.1 异步推理

```cpp
// 回调函数类型
typedef void (*TextEmbeddingResultCallback)(EmbeddingResult *result,
                                            void *callback_user_data);

void text_embedding_async(TextEmbeddingSession *session, const char *text,
                          TextEmbeddingResultCallback callback,
                          void *callback_user_data);
```

**说明**：异步执行文本向量化，结果通过回调函数返回。  
**参数**：
- `session`：已初始化并加载模型的会话句柄
- `text`：输入文本
- `callback`：结果回调函数
- `callback_user_data`：用户自定义数据，原样传给回调

**注意**：回调函数参数中的 `EmbeddingResult` 生命周期为 callback 作用域，资源由 SDK 侧管理，**不需要调用 `embedding_result_destroy`**。

### 6.2 启用内部事件循环

```cpp
void text_embedding_enable_internal_event_loop(TextEmbeddingSession *session,
                                               bool enable);
```

**说明**：启用 SDK 内部事件循环，使异步回调可在不依赖外部 GMainLoop 的情况下触发。默认值为 `false`。  
**参数**：
- `session`：会话句柄
- `enable`：`true` 启用，`false` 关闭

---

## 七、模型列表示例 JSON

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

## 八、Python ctypes 封装建议

### 8.1 加载 .so

```python
import ctypes
from ctypes import c_char_p, c_int, c_void_p, POINTER, c_float

lib = ctypes.CDLL("/usr/lib/libkylin-coreai-embedding.so")
```

### 8.2 定义不透明指针类型

```python
class TextEmbeddingSession(ctypes.c_void_p):
    pass

class EmbeddingResult(ctypes.c_void_p):
    pass

class EmbeddingModelList(ctypes.c_void_p):
    pass
```

### 8.3 绑定函数签名

```python
# 生命周期
lib.text_embedding_create_session.restype = TextEmbeddingSession
lib.text_embedding_create_session.argtypes = []

lib.text_embedding_destroy_session.restype = None
lib.text_embedding_destroy_session.argtypes = [POINTER(TextEmbeddingSession)]

lib.text_embedding_init_session.restype = c_int
lib.text_embedding_init_session.argtypes = [TextEmbeddingSession]

lib.text_embedding_init_model.restype = c_int
lib.text_embedding_init_model.argtypes = [TextEmbeddingSession, c_char_p]

# 模型列表
lib.text_embedding_get_model_list.restype = EmbeddingModelList
lib.text_embedding_get_model_list.argtypes = [TextEmbeddingSession, POINTER(c_int)]

lib.embedding_model_list_get_count.restype = c_int
lib.embedding_model_list_get_count.argtypes = [EmbeddingModelList, POINTER(c_int)]

lib.embedding_model_list_get_model.restype = c_void_p  # EmbeddingModelInfo
lib.embedding_model_list_get_model.argtypes = [EmbeddingModelList, c_int, POINTER(c_int)]

lib.embedding_model_info_get_model_name.restype = c_char_p
lib.embedding_model_info_get_model_name.argtypes = [c_void_p, POINTER(c_int)]

lib.embedding_model_info_get_model_dim.restype = c_int
lib.embedding_model_info_get_model_dim.argtypes = [c_void_p, POINTER(c_int)]

# 同步推理
lib.text_embedding.restype = c_bool
lib.text_embedding.argtypes = [TextEmbeddingSession, c_char_p, POINTER(POINTER(EmbeddingResult))]

lib.embedding_result_get_error_code.restype = c_int
lib.embedding_result_get_error_code.argtypes = [EmbeddingResult]

lib.embedding_result_get_vector_data.restype = POINTER(c_float)
lib.embedding_result_get_vector_data.argtypes = [EmbeddingResult]

lib.embedding_result_get_vector_length.restype = c_int
lib.embedding_result_get_vector_length.argtypes = [EmbeddingResult]

lib.embedding_result_destroy.restype = None
lib.embedding_result_destroy.argtypes = [POINTER(EmbeddingResult)]
```

### 8.4 调用示例

```python
session = lib.text_embedding_create_session()
if not session:
    raise RuntimeError("create session failed")

rc = lib.text_embedding_init_session(session)
if rc != 0:
    lib.text_embedding_destroy_session(byref(session))
    raise RuntimeError(f"init session failed: {rc}")

rc = lib.text_embedding_init_model(session, b"ensemble-embd_gte-base_uint8-text")
if rc != 0:
    lib.text_embedding_destroy_session(byref(session))
    raise RuntimeError(f"init model failed: {rc}")

result = POINTER(EmbeddingResult)()
if not lib.text_embedding(session, b"测试文本", byref(result)):
    lib.text_embedding_destroy_session(byref(session))
    raise RuntimeError("embedding call failed")

if lib.embedding_result_get_error_code(result) != 0:
    msg = lib.embedding_result_get_error_message(result)
    lib.embedding_result_destroy(byref(result))
    lib.text_embedding_destroy_session(byref(session))
    raise RuntimeError(f"embedding failed: {msg}")

length = lib.embedding_result_get_vector_length(result)
data = lib.embedding_result_get_vector_data(result)
vector = [data[i] for i in range(length)]

lib.embedding_result_destroy(byref(result))
lib.text_embedding_destroy_session(byref(session))
```

---

## 九、MemoryHub 当前实现对照与需要修复的问题

MemoryHub 当前实现 `memoryhub/embedding/kylin_client.py` 存在以下问题：

### 9.1 使用了不存在的 API

当前代码引用了 `text_embedding_init_session_no_connect()`，但**公开头文件中不存在该函数**。这是测试文件 `TestTextEmbedding.cpp` 中 mock 测试用的内部函数，不是 SDK 公开 API。

**修复**：改为：

```python
session = lib.text_embedding_create_session()
lib.text_embedding_init_session(session)
```

### 9.2 模型列表 API 不匹配

当前代码没有处理 `text_embedding_get_model_list` 的 `error_code` 输出参数。新 API 为：

```python
err = c_int()
model_list = lib.text_embedding_get_model_list(session, byref(err))
if err.value != 0:
    raise RuntimeError(f"get model list failed: {err.value}")
```

### 9.3 其他需要补充的功能

1. 模型列表查询支持（用于动态选择模型和确认维度）
2. 异步推理支持（`text_embedding_async`）
3. 非 768 维模型（如 cn-clip 1024 维）的适配
4. 更完善的错误码处理（`CoreAiEmbeddingErrorCode`）

---

## 十、参考链接

- 本地 SDK 主头文件：`/d/project/kylin-coreai-embedding/include/kylin-ai/coreai/embedding/embedding.h`
- 本地模型信息头文件：`/d/project/kylin-coreai-embedding/include/kylin-ai/coreai/embedding/modelinfo.h`
- 本地错误码头文件：`/d/project/kylin-coreai-embedding/include/kylin-ai/coreai/embedding/error.h`
- Gitee 测试源码：[TestTextEmbedding.cpp](https://gitee.com/openkylin/kylin-coreai-embedding/blob/openkylin/nile-sp2/test/TestTextEmbedding.cpp)
- MemoryHub 当前封装：`memoryhub/embedding/kylin_client.py`
- 集成方案：`2026-08-02_kylin_embedding_vector_engine_integration_plan.md`
- 环境交接清单：`2026-08-02_kylin_environment_handoff_checklist.md`
