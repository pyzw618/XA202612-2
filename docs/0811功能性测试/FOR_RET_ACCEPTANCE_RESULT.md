# FOR / RET 专项验收测试结果记录

对应 `docs/0811功能性测试/TEST_PLAN.md` 6.7 遗忘模块(FOR-01~07)与 6.8 检索链路(RET-01~09),实现为 `tests/test_for_acceptance.py` 与 `tests/test_ret_acceptance.py`。

## 执行结果

- 运行命令:`pytest tests/test_for_acceptance.py tests/test_ret_acceptance.py -q`
- 结果:**20 passed**,0 failed,0 skipped(2026-08-11)
- 全量回归:`pytest tests/ -q` → **703 passed,2 skipped**(另 sync 服务测试隔离复跑 11 passed)
- 变更文件 ruff check:passed

### FOR-01~07(9 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| FOR-01 | 1 | 通过 | target_memory_ids 精确软删除(status=deleted),其余记忆不受影响,返回审计 record_id |
| FOR-02 | 3 | 通过 | 按 scene 批量删除且 user 隔离;按 task_type 单独定位不误伤他 scene 记忆 |
| FOR-03 | 1 | 通过 | 指令"忘掉周报格式偏好"经规则关键词定位到偏好;向量/BM25/lookup/缓存级联清理,其他记忆保留 |
| FOR-04 | 1 | 通过 | 偏好+知识+事实混合级联:SQLite 软删除、向量/BM25/证据/conflicts/缓存全清理、孤立实体清理 |
| FOR-05 | 2 | 通过 | <0.2 归档、0.2~0.4 降级(MID→SHORT)、0.4~0.6 置 PENDING 待审查、≥0.6 保留;fact 低健康度归档 |
| FOR-06 | 1 | 通过 | 低健康度记忆排序权重下降但数据保留(被动遗忘) |
| FOR-07 | 1 | 通过 | 多次遗忘后 /forget/history 记录完整(含删除 ID),user 隔离 |

### RET-01~09(11 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| RET-01 | 1 | 通过 | final=0.6×向量+0.3×关键词+0.1×元数据,逐条精确核对 |
| RET-02 | 2 | 通过 | FAISS 与 Milvus(mock 引擎)切换召回同一集合;引擎侧携带 user/status 过滤;稀疏向量确定性可复算 |
| RET-03 | 1 | 通过 | BM25 精确词命中;jieba 分词中文/英文/数字正确 |
| RET-04 | 1 | 通过 | context 场景冲突被过滤;min_confidence 低置信度被过滤 |
| RET-05 | 1 | 通过 | rerank 综合 相关性/scope/新鲜度/健康度 因子,新鲜健康记忆靠前,元数据暴露各因子分 |
| RET-06 | 1 | 通过 | LRU 命中直接返回、TTL 过期重查、invalidate 清除含目标记忆的缓存条目 |
| RET-07 | 1 | 通过 | /context 返回可拼接 prompt 文本,含偏好与流程;context/context_text 双字段一致 |
| RET-08 | 1 | 通过 | /search 命中后 last_accessed_at/access_count_30d 落库递增 |
| RET-09 | 1 | 通过 | 空查询与空库均返回空结果不报错 |

## 修改内容

### 修复:自然语言遗忘定位失败(真实 Bug,FOR-03/04)

1. **`memoryhub/core/forget/forgetter.py` — `_extract_keywords` 中文分词**
   原实现按空白切分,指令"忘掉周报格式偏好"被当成**单个关键词**"忘掉周报格式偏好",与记忆文本"周报格式偏好 Markdown"的包含判断永远为假 → 自然语言遗忘**静默什么都不删**。现引入 jieba 精确分词(与 `keyword_search._tokenize` 一致)后再过滤指令动词/停用词,关键词变为 `["周报","格式","偏好"]`;英文按空白切分。无 jieba 时仍走旧逻辑(降级不崩溃)。

2. **`memoryhub/core/forget/forgetter.py` — `_locate_by_scope` 部分 scope 匹配**
   原实现直接透传 `get_by_scope(user_id, scene, task_type)`,导致:仅按 task_type/app 删除时会因 `scene=""` 严格等值而**漏掉带 scene 的记忆**;app 维度完全无法定位。改为在 active 记忆上按显式给出的 scene/task_type/app 逐项匹配,未给出的维度不参与过滤,统一支持三维度(对应 FOR-02 扩展)。

3. **`memoryhub/core/forget/auto_forget.py` — 日志中文乱码**
   源文件被以 ASCII 编码保存,4 处 `logger` 中文消息损坏为 `"???????"`,已恢复为正常中文描述。文件现为 UTF-8。

### 测试实现(新增 2 文件)

- `tests/test_for_acceptance.py`:FOR-01~07 共 9 用例;驱动真实 `MemoryForgetter` / `AutoForgetEngine` / `HealthCalculator`(注入映射健康度)/ `Reranker`(被动遗忘)/ `ForgetRepository`,含真实 facts pipeline 与多类索引 fake 的级联断言。
- `tests/test_ret_acceptance.py`:RET-01~09 共 11 用例;单元级驱动 `HybridRetriever` / `MilvusHybridRetriever` / `Reranker` / `SearchCache` / `KeywordSearcher` / `VectorSearcher`,API 级驱动 `/search` 与 `/context`(TestClient + seeded DB)。

### 状态

- 修改文件:`memoryhub/core/forget/forgetter.py`、`memoryhub/core/forget/auto_forget.py`(未提交)。
- 新增测试文件:`tests/test_for_acceptance.py`、`tests/test_ret_acceptance.py`(未跟踪)。
- 与既有回归语义对齐:`tests/test_data_flow_merge_regressions.py::test_knowledge_forget_enforces_owner_and_cascades`、`tests/test_sync_service.py::test_api_forget_removes_from_milvus`、`tests/test_search_integration.py` 全部继续通过,未破坏 owner 校验与检索接线约定。
