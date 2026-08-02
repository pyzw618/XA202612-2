# kylin-mock — 麒麟 SDK Mock 动态库

在无麒麟 OS / Milvus 的环境（如 Windows 开发机）下，为 Python ctypes 封装层提供与真实 SDK **符号级一致**的 Mock 动态库，使全部 Python 测试可以跑通。

## 内容

| 源文件 | 产物 | 模拟对象 |
|---|---|---|
| `embedding_mock.c` | `libkylin-coreai-embedding-mock.dll` | `libkylin-coreai-embedding.so`（文本 Embedding SDK） |
| `vector_engine_mock.c` | `libkysdk-vector-engine-client-capi-mock.dll` | `libkysdk-vector-engine-client-capi.so`（向量引擎最小 C API） |

行为要点：

- **embedding mock**：`text_embedding` 对输入文本做 FNV-1a hash 作为种子，确定性生成 768 维 float 向量（同文本恒得同向量），L2 归一化；环境变量 `KYLIN_EMBEDDING_MOCK_LATENCY_MS` 可注入延迟；异步 API 通过回调返回"不支持"错误码。
- **vector engine mock**：纯内存实现 collection → (memory_id, content, dense_vector) 存储；稀疏向量按与真实桥接层一致的规则从 content 生成（非字母数字/空白切词，中文按单字，FNV-1a 32-bit 索引，归一化 TF 权重）；`hybrid_search` = 稠密余弦 top_k + 稀疏点积 top_k，RRF 融合（`1/(60+rank)`）；结果 JSON 由 `vector_engine_free_buffer` 释放。

## 构建

需要项目 venv（已安装 `ziglang`）：

```bash
D:/project/XA202612-2/.venv/Scripts/python.exe third_party/kylin-mock/build_mock.py
```

产物输出到 `third_party/kylin-mock/build/`（按平台生成 `.dll` / `.so` / `.dylib`）。

## 验证

```bash
D:/project/XA202612-2/.venv/Scripts/python.exe third_party/kylin-mock/verify_mock.py
```

用 ctypes 加载两个动态库，断言 embedding 维度/确定性/归一化，以及向量引擎 insert → hybrid_search → JSON 解析全链路。
