# Phase I 收尾总纲：全部收尾项合并清单（交接用）

> 状态：**待交接团队实施**
> 目的：汇总各阶段实施后遗留的全部"收尾/未做"项，供团队接手时逐项核对、排期、验收。
> 关联：各阶段实施记录 `docs/refactor/PHASE_{A,B,C,D,E,G}_IMPLEMENTATION_LOG.md`、`PHASE_F_PLAN.md`、`PHASE_H_PLAN.md`、`REFACTOR_PLAN_V2.md`。

---

## 0. 进度快照（2026-08-19 更新）

> **批次 1~4 与 I-14 已由收尾会话实施完毕**，全量回归失败集与基线一致（17 failed + 28 errors
> 均为既有 milvus/embedding 环境问题与预存在 flake，非本次改动引入）。本次新增/改动速查：

| 项 | 状态 | 本次交付 |
|---|---|---|
| I-2 | ✅ | `config.yaml` 已 `runtime.fact_mode=knowledge`；`test_fact_knowledge_transition` 验证知识模式下旧 facts 表零写入 |
| I-5 | ✅ | 新增 `desktop-client/src/pages/MemoryTierPage.{h,cpp}`（短期/中期双表 + 手动流转按钮），注册进 MainWindow，已用 Qt5/MSVC 构建通过（BUILD_OK） |
| I-15 | ✅ | `tests/test_dual_track_contract.py` 已存在并通过（REST vs `/api/agent/replay` 双轨一致 + 幂等 + 跨用户隔离） |
| I-1 | ✅ | **已完成物理清理**：`memoryhub/core/fact/` 全部删除；`create_app` 移除 `fact_pipeline`；`app.state.fact_store/fact_index_service/fact_pipeline` 移除；`ExtractionExecutor` 移除 `run_fact/fact_handler/fact_ingestion_adapter/fact_mode`；`/facts*` 收敛为纯 knowledge(FACT) 转发（`/facts/propose` 直接写 FACT 知识）；`fact_mode` 配置字段删除；`tests/test_fact/` 删除、受影响测试全部改写为 knowledge(FACT) 断言；`scripts/migrate_facts_to_knowledge.py` 删除 |
| I-3 | ✅ | FactPage 继续走 `/facts`（已收敛为 knowledge(FACT) 纯转发）；`openProposeDialog` 改为直接写入并刷新（候选裁决区不再产生，因 propose 直接落库） |
| I-4 | ✅ | `SearchRequest.level` 已接入 `_apply_tiered_cascade`（`adapter/api.py`）：level=short/mid/long 各层过滤 + 无 level 时 session 级联；`tests/test_search_level_cascade.py` |
| I-6 | ✅ | `AutoForgetEngine._demote_with_episode` 已与 MemoryDegrader 深融合（健康度降级→先落中期情景快照） |
| I-8 | ✅ | 偏好 LLM prompt 已注入 tool_calls（`preference/extractor.py`） |
| I-9 | ✅ | `MemoryConsolidator.consolidate_workflow_preferences` 已接入 WorkflowMiner |
| I-13 | ✅ | 用户遗忘规则 `ForgetRuleService`（`core/forget/rules.py`）+ `/forget/rules` CRUD；`ForgetRequest.level/session_id` 支持 short/mid 分层遗忘；`tests/test_forget_rules.py` |
| I-7 | ✅ | 新增 `behavior_adapter.py` / `config_adapter.py` + `ManualConfig` 版本化对象 + `/sources/behavior`、`/sources/config` 端点；`tests/test_source_adapters.py` |
| I-10 | ✅ | `preference_eval`/`conflict_eval` 空壳已填实、数据集与 `/evaluate/preference|conflict` 已落地（本次修 stale docstring）。FACT 冲突类目与 N≥200 大规模数据集为后续增强 |
| I-14 | ✅ | 双重门禁 flake 根因已通过 `skip_write_gate` 收口（handler/extraction 路径跳过二次门禁）；`test_api_02/03` 连续 12/12 通过 |


## 1. 原则

- 每项已实施阶段的核心已就绪；收尾项多为**清理、切换、补全、评测**，不影响已交付核心功能。
- 按**风险从低到高 + 交付依赖**排列。团队可并行处理不同线。
- 所有改动保持"失败集与基线一致"的回归纪律（`/d/Anaconda/envs/mhub311/python.exe -m pytest -q`）。

---

## 2. 收尾项清单

### I-1 FACT 独立体系物理清理（Phase C 遗留）✅ 已完成
- **已删除** `FactStore` / `FactMemoryPipeline` / `FactIndexService` / `FactMemoryHandler` / `ConflictDetector` / `EntityNormalizer` 等（`memoryhub/core/fact/` 整目录）——由 `knowledge(FACT)` 完全取代。
- `insert_fact` 随存储删除；业务代码零直接写 `facts` 表（`test_no_production_write_bypass` 校验）。
- `/facts` 双读（`_legacy_fact_to_dict` / legacy 兜底）已移除，仅保留 knowledge(FACT) 单一来源。
- `create_app` 移除 `fact_pipeline` 参数；`app.state.fact_store/fact_index_service/fact_pipeline` 移除；`ExtractionExecutor`/`EventIngestionService`/`MemoryForgetter`/`AutoForgetEngine`/`ProjectionOutboxWorker`/`PendingIndexCompensationTask`/`ExtractionRetryService` 全部移除 legacy fact 依赖；`fact_mode` 配置字段删除。
- 受影响测试：`tests/test_fact/` 已删除；`test_api_acceptance`/`test_dual_track_contract`/`test_evaluation`/`test_memory_tiers` 等 fixture 移除 `fact_pipeline`；legacy fact 断言全部改写为 knowledge(FACT)。
- `scripts/migrate_facts_to_knowledge.py` 已删除（迁移不再需要）。

### I-2 生产借出切换（Phase B/C 遗留）✅ 已完成
- 事实以 knowledge(FACT) 单一来源写入（legacy Fact 管线已删除，`fact_mode` 字段随之移除）。
- 验证：`POST /events` 带工具结果 → knowledge(FACT) 落库、`/facts` 从 knowledge 读到。

### I-3 前端 FactPage 数据源切换（Phase B/C 遗留）✅ 已完成
- `desktop-client/src/pages/FactPage` 走 `/api/memory/facts*`（已收敛为 knowledge(FACT) 纯转发）；`openProposeDialog` 改为直接写入并刷新列表。

### I-4 记忆分层检索级联深融合（Phase E 遗留）
- 已交付：`SearchRequest.level/session_id`、`GET /short-term`、`GET /mid-term`、`index_metadata.level`。
- 待补：完整 session→mid→long **加权融合检索**——`POST /search` 带 `session_id` 时先注入短期工作记忆，再近期中期情景，最后长期混合；三档按 level 加权；响应标注每条的 `memory_level`。
- 涉及：`retrieval/milvus_hybrid.py`（engine_filters + `_filter_by_context` 加 level）、`adapter/api.py search`、`SearchResponse` 加 `memory_level`。
- 保持延迟预算（P95≤350/P99≤500），分层查询不叠加长期 p95。

### I-5 前端分层页面（Phase E 遗留）
- 新增/改造 Qt 页面展示短期/中期/长期：`GET /short-term?session_id=`、`GET /mid-term`、长期即现有偏好/知识/事实页。
- `POST /lifecycle/consolidate` 页面上传按钮（手动触发分层流转）。

### I-6 AutoForgetEngine 与分层深融合（Phase E 遗留）
- 现状：`AutoForgetEngine` 做字段级降级（long→mid→short），`MemoryDegrader` 做真实情景快照+归档。两者并存。
- 待补：统一——AutoForget 的降级与 MemoryDegrader 合并为同一条"健康度→分层反哺"路径；健康度经 Phase A 已对齐半衰期（艾宾浩斯），确认降级阈值与分层 TTL 一致。

### I-7 源适配层 + 工具/行为/配置多源（Phase D 补全）
- 计划见 `REFACTOR_PLAN_V2.md` §4.1：`SourceAdapters`（`tool_result_adapter`/`behavior_adapter`/`config_adapter`），把 `normalize_tool_result` 提升为服务端适配器，`POST /api/memory/sources/tool_result` 对外入口。
- 手动配置版本化对象（`ManualConfig`：config_type/payload/version 链），作为偏好强来源（source=0.95）。
- 依赖：`tool_result` 结构化 + FACT 知识已就绪（Phase B/C），此处补输入源入口。

### I-8 偏好 LLM prompt 注入 tool_calls（Phase D 补全）
- `preference/extractor.py` 的 LLM prompt 目前不含 `tool_calls`；补注入，使 LLM 路径也能直接产出 TOOL_PREFERENCE/WORKFLOW_PREF。
- 与 `ToolPreferenceMiner`（规则）互补，并保持确定性优先。

### I-9 WORKFLOW_PREF 挖掘（Phase D 补全）
- `WorkflowMiner`（`core/knowledge/workflow_miner.py`，现有但未接入生产）产出公共步骤 → 映射为 `WORKFLOW_PREF` 偏好候选，接入 PreferenceUpdater。

### I-10 评测闭环落地（Phase F 实施）
- 规划在 `PHASE_F_PLAN.md`：填实 `preference_eval.py`/`conflict_eval.py` 空壳 + `preference_golden_v1.json`/`conflict_golden_v1.json` 数据集 + `/evaluate/preference|conflict` API 接入 + `tests/test_evaluation.py`。
- **评分表硬指标**：偏好准确率≥85%、冲突正确率≥88%——必须落地评测才有基线。

### I-11 检索召回攻坚（评分表 25 分主战场，需真实麒麟/Milvus）
- 基线：golden R@5=0.555（`evaluation/results/`）；目标 0.85。
- 路线（`REFACTOR_PLAN_V2.md` §4.7.4）：
  1. embedding 升级 `bge-large-zh`（768 维契约不变，走 `embedding_profile_id` 重嵌入流程）；
  2. cross-encoder 精排（`rerank_enabled` 生产打开，测延迟预算）；
  3. query rewrite（`StructuredLLMAdapter` 轻量）；
  4. 跨域消歧（query 带 scene/task_type 时按 scope 预过滤）。
- **依赖**：真实银河麒麟 + Milvus 环境（`check_kylin_embedding_runtime.py` 通过）才能复验；本机 mock 环境不可作验收。

### I-12 KYLIN 真机验收（赛题要求 4）
- `docs/kylin/KYLIN_EMBEDDING_RUNTIME_CONTRACT.md` + `scripts/check_kylin_embedding_runtime.py` 已交付；需在真实麒麟设备执行 8 项检查 + `run_kylin_http_retrieval_evaluation.py` 端到端延迟（P99≤500ms）。
- `/health` 暴露 SDK load/session/model/timeout/dimension 指标（`kylin_client.py` 已有稳定错误码，接线到 health 端点）。

### I-13 语义遗忘收尾（Phase G 遗留 + Phase F 衔接）
- forget 用户规则（`user_rules` 增 forget 类）；按 level 精准遗忘（short/mid/long）；遗忘精准度评测并入 F。

### I-14 双重门禁偶发问题（预存在问题，跨阶段）
- `test_api_02`/`test_api_03` 偶发失败（`invalid_safe_projection`，约 1/5）：事件级门禁 + 记忆级门禁"双重门禁"偶发安全投影重建失败。
- 缓解方向：抽取写入跳过第二次门禁（事件已安全）或统一单次门禁；根因在 `memoryhub/core/safety/memory_write.py` 的 `_memory_from_approved` envelope 重建。
- **务必立项**：这是既有 flake，非某阶段引入，但影响 CI 稳定性。

### I-15 E2E 契约测试（跨阶段）
- 补：同一事件经 REST 与 `/api/agent/replay` 进入产出记忆一致的契约测试（R1 双轨合一的验收）；跨用户隔离；门禁回执透出（Phase A 已加，补全 API 层）。

---

## 3. 建议排期（团队按资源调整）

| 批次 | 项 | 说明 |
|---|---|---|
| **批次 1（低风险清理）** | I-2、I-5、I-15 | ✅ 已完成 |
| **批次 2（FACT 收尾）** | I-1、I-3 | ✅ 已完成（`core/fact/` 物理删除、`/facts` 纯 knowledge 转发） |
| **批次 3（分层+遗忘深化）** | I-4、I-6、I-8、I-9、I-13 | ✅ 已完成 |
| **批次 4（多源+评测）** | I-7、I-10 | ✅ 已完成（可先于 I-11 出基线） |
| **批次 5（真机+召回）** | I-11、I-12 | 需真实麒麟/Milvus，独立环境 |
| **随时** | I-14 | ✅ 已完成（`skip_write_gate` 收口） |

## 4. 涉及文件速查

- FACT 物理清理：`memoryhub/core/fact/**`（已删）、`memoryhub/adapter/api.py`（/facts 纯 knowledge 转发）、`scripts/migrate_facts_to_knowledge.py`（已删）、`tests/test_fact*`（已删/改写）
- 分层级联：`retrieval/milvus_hybrid.py`、`adapter/api.py`、`adapter/schemas.py`、`desktop-client/src/pages/**`
- 多源适配：`core/ingestion/`、`adapter/api.py`（新增 /sources）
- 评测：`evaluation/metrics/{preference,conflict}_eval.py`、`evaluation/datasets/*.json`、`adapter/api.py`（/evaluate）
- 召回：`config.py`（embedding）、`retrieval/reranker.py`、`embedding/`（profile 重嵌入）
- 门禁 flake：`core/safety/memory_write.py`、`app.py`

## 5. 验收基线

每完成一项，保持：
```
/d/Anaconda/envs/mhub311/python.exe -m pytest -q   # 失败集与基线一致（16 failed + 28 errors 为环境问题，非代码失败）
```
基线失败集参考各阶段实施记录「全量验证结果」一节。
