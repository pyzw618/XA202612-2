# 银河麒麟 Embedding 运行时契约

> 依据：`memoryhub/embedding/kylin_client.py`、`docs/REFACTOR_PLAN_V2.md` §4.6、`docs/refactor/MAIN_TO_REMEM_REFACTOR_ROADMAP.md` §7。
> 状态：部署/验收前置文档；真机验收前需按本契约逐项确认。

## 1. 目标运行环境

| 项 | 契约值 | 备注 |
|---|---|---|
| 操作系统 | 银河麒麟桌面操作系统（V10 系，含 SP1+） | 生产禁止非麒麟环境 |
| CPU 架构 | `x86_64` 或 `aarch64` | 动态库需匹配架构，禁止交叉加载 |
| Embedding SDK | `kylin-coreai-embedding` C API（`ctypes` 加载 `.so`） | 见 §2 |
| 模型 | `ensemble-embd_gte-base_uint8-text` | 与 SDK 服务内注册的模型名一致 |
| 向量维度 | **768** | 固定契约；生产维度不匹配即失败关闭 |
| 向量引擎 | Milvus（C API） | `vector_engine.provider=milvus`，需 `app_id` |

## 2. 动态库契约

`.so` 搜索路径（按优先级，`kylin_client.py:SO_CANDIDATES`）：

```text
libkylin-coreai-embedding.so
/usr/lib/libkylin-coreai-embedding.so
/usr/local/lib/libkylin-coreai-embedding.so
```

SDK 调用流程（`kylin_client.py` docstring，对应公开头文件）：

```text
text_embedding_create_session()      → 创建会话
text_embedding_init_session(session) → 连接后端（DBus）
text_embedding_init_model(session, model_name) → 初始化模型
text_embedding(session, text, &result)          → 调用 Embedding
...（查询/维度检查）...
text_embedding_destroy_session(&session)        → 销毁会话
```

- 加载失败 → 稳定错误码 `embedding.unavailable`（`kylin_client.py` 的 `KylinEmbeddingError`）。
- mock 库仅限开发/CI：`libkylin-coreai-embedding-mock.so`（`third_party/kylin-mock/build/`），**生产禁止**。

## 3. DBus 服务契约

- Embedding 服务通过 **DBus** 与后端通信；部署前需确认 DBus 会话可用、Embedding 服务已注册且可连接。
- `query_timeout_ms` 默认 **250ms**（`kylin_client.py:100`）；超时返回稳定错误码 `embedding.timeout`（ctypes 无法中断 C 调用，超时后返回错误而非崩溃）。
- 服务不可用 → `embedding.unavailable`；初始化会话失败 → `embedding.session_init_failed`。

## 4. 维度与 Profile 契约

- 生产链路固定 **768 维**（`DEFAULT_DIM`）；真实 SDK 模式 `dim != 768` 直接抛 `embedding.dimension_mismatch`。
- **`embedding_profile_id`**（模型/SDK/维度升级时启用）：
  ```text
  embedding_profile_id = sha256(provider + sdk_version + model_name + dimension + metric)
  ```
  profile 写入 outbox、collection metadata、检索响应与健康检查。**profile 变化必须**：新建 collection/namespace → 全量重嵌入 → 切换读取 → 保留旧 collection 至回滚窗口结束（新旧向量不可混用）。

## 5. 生产门禁

`config.py:validate_production_gate` + `validate_production_runtime` 要求：

```text
embedding.provider   = kylin            （禁止 mock / auto / fallback）
vector_engine.provider = milvus
embedding.dimension  = 768
runtime.allow_fallback = false
```

任一不满足 → `ProductionGateError` 启动失败（fail-closed）。

## 6. 部署前检查

运行 `scripts/check_kylin_embedding_runtime.py`（见其输出 `kylin_runtime_check.json`），逐项确认：

1. 操作系统 = 麒麟桌面、CPU 架构匹配；
2. `libkylin-coreai-embedding.so` 存在于预期路径且可 `ctypes.CDLL` 加载；
3. 依赖动态库（libstdc++/libgcc/DBus 库）可解析；
4. DBus 会话可用、Embedding 服务名可连接（能 create/init session）；
5. `init_model` 成功且模型名 = `ensemble-embd_gte-base_uint8-text`；
6. 单条 embedding 返回 **768 维**；
7. Milvus `app_id` 已配置且可连通；
8. 生产门禁配置通过（无 mock/fallback）。

## 7. 验收与回滚

- 真机验收：在目标麒麟设备执行 §6 检查 + `run_kylin_http_retrieval_evaluation.py` 端到端，产出延迟（P99≤500ms）与 QPS 报告。
- 模型/维度升级：按 §4 的 profile 流程重建索引；回滚窗口内保留旧 collection，`embedding_profile_id` 对照可追溯。

---

*关联：`docs/REFACTOR_PLAN_V2.md` §4.6、`docs/refactor/MAIN_TO_REMEM_REFACTOR_ROADMAP.md` §7、`scripts/check_kylin_embedding_runtime.py`。*
