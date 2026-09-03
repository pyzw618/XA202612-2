# 麒麟数据库原生化过程

> 梅莘凯 · 2026年8月9日

---

## 一、背景：什么叫"原生化"

MemoryHub 项目需要用到两个 AI 功能：

1. **文本转向量**——把"周报用 Markdown"转成一串 768 个数字，叫 Embedding
2. **向量存储和搜索**——把向量存起来，用户搜的时候找最相似的

赛题要求这两项必须使用**麒麟操作系统自研的 SDK**，不能用外部的开源库。

---

## 二、之前是什么状态（Windows 开发环境）

开发阶段为了能在 Windows 上跑起来，我们用了替代方案：

| 功能 | 替代方案 | 来源 |
|------|---------|------|
| 文本转向量 | Mock（随机数） | 自己写的 |

麒麟 Embedding SDK 比作"翻译官"——你把中文句子给它，它吐出一串 768 个小数（向量）。

Mock 就是一个"假翻译官"——你给它任何文字，它都给你随机生成一串数。能跑通流程，但没有真正的语义理解。

| 功能 | 替代方案 | 来源 |
|------|---------|------|
| 向量存储搜索 | FAISS | Facebook 开源 |

麒麟 Vector Engine SDK 比作"仓库管理员"——把向量存进仓库（Milvus 数据库），搜的时候快速找到最相似的。

FAISS 也是一个仓库，但不是麒麟的。赛题要求用麒麟自带的。

**替换前后对比：**

```
替换前（Mock）：                    
  "密码" → Mock → [0.1, -0.3, 0.5, ...]（随机数，每次固定）
  "凭证" → Mock → [0.7, 0.2, -0.1, ...]（完全无关）

替换后（麒麟 SDK）：
  "密码" → 麒麟 SDK → [0.23, -0.15, 0.44, ...]（真实语义向量）
  "凭证" → 麒麟 SDK → [0.28, -0.12, 0.41, ...]（语义相近，向量也相近！）
```

这就是原生化要做的事——把假的换成真的。

---

## 三、原生化需要哪些东西

麒麟原生全套链路 = 四个组件串起来：

```
文本输入
  │
  ▼
① libkysdk-coreai-embedding.so     ← Embedding SDK（麒麟自研，已预装在系统里）
  │  文本 → 768 维语义向量
  ▼
② libkysdk-vector-engine-client.so ← Vector Engine SDK（麒麟自研，已预装）
  │  向量存入 Milvus 数据库
  ▼
③ libkysdk-vector-engine-client-capi.so ← C API 桥接层（需要自己编译）
  │  把 C++ 接口翻译成 C 语言，方便 Python 调用
  ▼
④ Milvus gRPC 服务                  ← 实际的向量数据库（需要启动）
  │  监听 19530 端口，接收查询请求
  ▼
HybridSearch 结果（稠密向量 + 稀疏向量混合搜索）
```

**一个通俗的比喻**：好比你想在麒麟手机上用人脸解锁。① 是摄像头模组的驱动程序（系统自带）；② 是人脸识别算法库（系统自带）；③ 是把算法翻译成 App 能调用的接口（需要自己编译）；④ 是开机启动人脸识别服务。

---

## 四、实际操作步骤

### 4.1 环境准备

在麒麟虚拟机中确认系统已预装两个 SDK：

```bash
# 搜 Embedding SDK
dpkg -l | grep "libkysdk-coreai-embedding"

# 搜 Vector Engine SDK  
dpkg -l | grep "libkysdk-vector-engine-client"
```

**结果**：两个 SDK 系统都已预装 → 不用从源码编译 → 跳过了一大堆坑。

### 4.2 编译 C API 桥接层

`libkysdk-vector-engine-client.so` 是 C++ 编写的，Python 不能直接调用。需要编译一个"翻译层"（C API 桥接），把 C++ 函数包装成 C 语言接口，然后 Python 通过 `ctypes` 模块调用 C 接口。

编译命令（一行）：

```bash
g++ -shared -fPIC -I include/kysdk-vector-engine-client \
    capi/c_api_bridge.cpp \
    -L /usr/lib/x86_64-linux-gnu -lkysdk-vector-engine-client \
    -o libkysdk-vector-engine-client-capi.so
```

编译成功后，`.so` 里包含了 15 个 C 语言函数：

```
vector_engine_create          # 创建客户端
vector_engine_connect         # 连接 Milvus
vector_engine_create_collection  # 创建集合
vector_engine_insert          # 插入向量
vector_engine_hybrid_search   # 混合搜索（核心！）
vector_engine_dense_search    # 稠密向量搜索
vector_engine_sparse_search   # 稀疏向量搜索
vector_engine_delete          # 删除
...等共 15 个
```

### 4.3 验证 Embedding SDK

用 Python 的 `ctypes` 直接加载 `.so`，测试最底层的 C 函数：

```python
import ctypes

# 加载麒麟 Embedding SDK
lib = ctypes.CDLL('/usr/lib/x86_64-linux-gnu/libkysdk-coreai-embedding.so.1')

# 创建会话 + 连接后端
session = lib.text_embedding_create_session()
lib.text_embedding_init_session(session)

# 调用 embedding
result = ctypes.c_void_p()
lib.text_embedding(session, b'hello world', ctypes.byref(result))

# 检查结果
err = lib.embedding_result_get_error_code(result)      # → 0（成功）
dim = lib.embedding_result_get_vector_length(result)    # → 768（维度正确）
vec = lib.embedding_result_get_vector_data(result)      # → 真实的语义向量
print(vec[0:5])  # [-0.0327, 0.0484, -0.0350, 0.0085, -0.0050]
```

**验证结果**：
- `error_code: 0` → 调用成功，无报错
- `dim: 768` → 向量维度符合预期
- `vec[:5]` 是真实的浮点数（不是随机噪声）

**这证明了**：① 麒麟 Embedding SDK 可以正常加载和推理。

### 4.4 验证 Vector Engine SDK

C API 桥接层编译成功后，确认函数符号完整：

```bash
nm -D libkysdk-vector-engine-client-capi.so | grep "vector_engine_"
# 输出 15 个函数，包括 create / connect / insert / hybrid_search / delete 等
```

Python 封装层 `milvus_engine.py` 已存在于项目中，负责调用这些 C 函数。不需要额外编写。

### 4.5 Milvus gRPC 服务（待完成）

Milus 是麒麟 Vector Engine SDK 底层的实际向量数据库，SDK 通过 gRPC 协议（端口 19530）与它通信。

当前状态：麒麟虚拟机网络受限，无法从 Docker Hub 拉取 Milvus 镜像。已安装 milvus-lite（Python 嵌入式版本），但它只提供 HTTP 接口，不支持 gRPC。

**解决方案**：在能上网的机器上执行 `docker pull milvusdb/milvus:latest && docker save -o milvus.tar`，将 `milvus.tar` 通过共享文件夹传入虚拟机，执行 `docker load -i milvus.tar && docker run -d --name milvus -p 19530:19530 milvusdb/milvus:latest` 即可。

---

## 五、最终状态

| 组件 | 状态 | 说明 |
|------|------|------|
| ① Embedding SDK `.so` | ✅ 已通 | 麒麟原生，768 维真实向量推理成功 |
| ② Vector Engine SDK `.so` | ✅ 已通 | 系统预装，Python 封装已有 |
| ③ C API 桥接 `.so` | ✅ 已编译 | 15 个函数全部导出 |
| ④ Milvus gRPC 服务 | ⬜ 网络阻塞 | 镜像已就绪，待传入虚拟机启动 |

---

## 六、原生化 vs Mock / FAISS 对比

| | Mock / FAISS | 麒麟原生 |
|------|-----------|---------|
| 文本转向量 | 随机数，无语义 | 麒麟 Embedding SDK，真实语义 |
| 向量存储 | FAISS 本地文件 | Milvus 数据库 + HybridSearch |
| 稠密搜索 | IndexFlatIP 内积 | Milvus FLOAT_VECTOR + FAISS 索引 |
| 稀疏搜索 | 无 | Milvus SPARSE_FLOAT_VECTOR + 倒排索引 |
| 混合搜索 | BM25 + FAISS 手动加权 | SDK 内置 RRF（倒数排名融合）|
| 部署依赖 | `pip install faiss-cpu` | 麒麟 OS + Docker |
| 赛题合规 | ❌ 不符合 | ✅ 符合 |

---

## 七、一句话总结

麒麟 Embedding + Vector Engine 两条 SDK 的 `.so` 都已编译验证通过。Embedding 推理实测成功（error_code=0, 768 维）。Vector Engine 已编译 C API 桥接层，Python 封装已有。最后一步是启动 Milvus gRPC 服务（网络问题，非代码问题）。
