# KNO 专项验收测试结果记录

对应 `docs/tests/0811功能性测试/TEST_PLAN.md` 6.5 知识记忆(KNO-01~04)。knowledge 板块实现与算法重构已完成并提交(`de38770` / `56a6e7c` / `19b4a74`,详见 `docs/tests/0805数据流测试/DATA_FLOW_UPDATE.md`),测试位于 `tests/test_knowledge/`。本记录汇总该板块的修改内容与测试结果。

## 执行结果

- 运行命令:`pytest tests/test_knowledge -q`
- 结果:**13 passed**,0 failed,**1 skipped**(2026-08-11 复跑通过)
  - 跳过项 `tests/test_knowledge/test_knowledge_api.py`:会真实调用 LLM,按约定不运行。
- 变更文件 ruff check:passed(`knowledge/ingestion/memory_write` 相关)。
- 全量回归:`pytest tests/ -q` → **693 passed,2 skipped**(唯一 sync 失败为无关时序偶发)。

### 测试文件明细

| 文件 | 结果 | 覆盖 |
|------|------|------|
| `test_knowledge_data_flow.py` | 8 passed | 轨迹→knowledge 全链路(KNO-01~04 主干) |
| `test_knowledge_optimization.py` | 4 passed | 语义去重、置信度衰减、版本保留、LLM 富化降级 |
| `test_knowledge_ingestion_adapter.py` | 1 passed | 原始 ingestion payload 兼容轨迹抽取 |
| `test_knowledge_api.py` | 1 skipped | 真实 LLM API(不运行) |

## 修改内容

### 重构:KnowledgeExtractor 内部算法(准入/排序/抽取)

1. **`memoryhub/core/knowledge/extractor.py` — 抽取算法重写**
   事件按 `occurred_at → turn_id → event_id` 确定性排序;增加知识信号准入与轨迹完成态判断,**失败/取消/超时/运行中轨迹不产出知识**;workflow 至少 2 个有效步骤、case 需完成结果且有步骤或工具、template 仅从至少 2 步的 case 生成;标准 `tool_calls` 按 sequence 读取只纳入 success/partial 工具;从最新事件逆序提取结果,Evidence ID 按事件和摘要确定性生成;LLM 必需路径失败时抛出稳定 `KnowledgeExtractionError`(不落入内部 fallback 吞掉)。

### 新增:KnowledgeUpdater 语义去重与原位演进

2. **`memoryhub/core/knowledge/updater.py` — 新增 `KnowledgeUpdater`**
   在相同 owner/type/兼容 scope 内综合名称、内容、步骤相似度寻找等价 active knowledge;合并步骤、工具和 Evidence 并**原位增加 version**;证据集合不重叠才增加 `total_count/success_count` 并调整 confidence——同一 session 轨迹跨请求补全只演进版本而不重复计数。
3. **`memoryhub/core/knowledge/confidence.py` — 新增置信度模型**
   基于证据链/工具链一致性计算置信度;工具链不一致时置信度下降(见 `test_knowledge_optimization::test_confidence_falls_when_tool_chain_is_inconsistent`)。
4. **`memoryhub/core/knowledge/evaluation.py` — 新增离线评测 helper**(配套 `evaluation/knowledge_merge_cases.json`)。

### 接线:幂等写入、轨迹重建、重试与反馈

5. **`ExtractionExecutor.run_knowledge`** 生成稳定语义 ID 并调用 `KnowledgeUpdater.add`,不再直接写入随机/批次绑定 ID(修复旧实现失败后重复执行产生重复版本的问题)。
6. **`EventRepository.get_trajectory(user_id, session_id, task_type)` + `EventIngestionService`**:事件安全落库后加载完整轨迹,修复同一 session 多次 `/events` 调用把一条轨迹拆成多组 workflow/case/template 的问题;无 session_id 时保持只处理当前分组。
7. **`ExtractionRetryService`**:以任务中的安全 anchor 事件重新加载当前完整轨迹,避免旧失败任务用过期事件集合覆盖新演进结果。
8. **`KnowledgeRepository.get_by_scope`** 将空 scene/task_type 解释为"不限制";`search_by_name`、`increment_usage` 增加向后兼容的可选 `user_id`。
9. **`MemoryWriteService`**(`memoryhub/core/memory_write.py`)对 EvidenceStore 改为重写当前去重集合,半成功重试与原位演进幂等;`index_text` 统一覆盖 name、content、steps、tools、template_body;startup 关联统一写服务,LifecycleManager/AutoForgetEngine 自动同步 SQLite/向量/BM25/lookup/cache,非 active 状态移出运行时索引但保留持久化 Evidence。
10. **`/feedback` 接口** 兼容 `KnowledgeMemory`(confirm 更新成功统计 / update 更新内容与版本 / reject 归档并移出运行时索引),对外请求/响应契约不变。

### 保留边界

- 对外 HTTP API、Pydantic/ORM 契约、构造接口与数据流拓扑均未改变。
- 语义等价判断仍为规则化字符串+步骤集合相似度,尚未引入 embedding 聚类、冲突审计或离线阈值评测。
- 跨 SQLite/Evidence/向量/BM25 的全局事务补偿协议未实现,依赖统一写服务与持久化重试做最终一致修复。

### 状态

- knowledge 板块改动均已提交(`de38770` / `56a6e7c` / `19b4a74`);本记录为验收结果汇总,无新增未提交文件。
- `tests/test_knowledge/test_knowledge_api.py` 需真实 LLM,按协作约定不运行、未修改。
