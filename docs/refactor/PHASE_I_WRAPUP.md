# Phase I 收尾总纲：全部收尾项合并清单（交接用）

> 状态：**待交接团队实施**
> 目的：汇总各阶段实施后遗留的全部"收尾/未做"项，供团队接手时逐项核对、排期、验收。
> 关联：各阶段实施记录 `docs/refactor/PHASE_{A,B,C,D,E,G}_IMPLEMENTATION_LOG.md`、`PHASE_F_PLAN.md`、`PHASE_H_PLAN.md`、`REFACTOR_PLAN_V2.md`。

---

## 1. 原则

- 每项已实施阶段的核心已就绪；收尾项多为**清理、切换、补全、评测**，不影响已交付核心功能。
- 按**风险从低到高 + 交付依赖**排列。团队可并行处理不同线。
- 所有改动保持"失败集与基线一致"的回归纪律（`/d/Anaconda/envs/mhub311/python.exe -m pytest -q`）。

---

## 2. 收尾项清单

### I-1 FACT 独立体系物理清理（Phase C 遗留，最高风险，需 FACT 稳定后做）
- **删除** `FactStore` / `FactMemoryPipeline` / `FactIndexService` / `FactMemoryHandler`（`memoryhub/core/fact/` 大部分 + `Fact` dataclass 相关）——由 `knowledge(FACT)` 完全取代。
- 删除 `facts`/`fact_evidence`/`conflicts`（fact 专属）表；`insert_fact`（`store.py:326`）随存储删除。
- 迁移期 `/facts` 双读（`_legacy_fact_to_dict` / `_fact_knowledge_lookup`）在存量 `facts` 表清空后移除，仅保留 knowledge(FACT) 单一来源。
- **前置**：①`config.yaml` 翻 `runtime.fact_mode=knowledge`；②运行 `scripts/migrate_facts_to_knowledge.py` 迁移存量；③验证 `GET /facts` 仅从 knowledge 读到（+ 旧 /facts 测试改为 FACT 知识）。
- 受影响测试：`test_fact/`、`test_api_09_facts_crud`（改为 FACT 知识断言）、`test_migrate_facts_to_knowledge`（删除或改迁脚本）。

### I-2 生产借出切换（Phase B/C 遗留）
- `config.yaml` 设 `runtime.fact_mode=knowledge`（默认仍 `legacy`）。
- 验证：`POST /events` 带工具结果 → knowledge(FACT) 落库、`facts` 表零写入、`/facts` 仍能读到（双读期间）；随后可 I-1。

### I-3 前端 FactPage 数据源切换（Phase B/C 遗留）
- `desktop-client/src/pages/FactPage` 当前走 `/api/memory/facts*`（双读已兼容）；迁移完成后改为 `GET /api/memory/knowledge?knowledge_type=fact`。
- 依赖：I-1 将 `/facts` 收敛为 knowledge 单一来源后，前端可直接切，无需双读。

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
- `docs/KYLIN_EMBEDDING_RUNTIME_CONTRACT.md` + `scripts/check_kylin_embedding_runtime.py` 已交付；需在真实麒麟设备执行 8 项检查 + `run_kylin_http_retrieval_evaluation.py` 端到端延迟（P99≤500ms）。
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
| **批次 1（低风险清理）** | I-2、I-5、I-15 | 切配置、前端分层页、契约测试 |
| **批次 2（FACT 收尾）** | I-1、I-3 | 依赖 I-2；物理清理 + 前端切换 |
| **批次 3（分层+遗忘深化）** | I-4、I-6、I-8、I-9、I-13 | 检索级联、健康度融合、偏好调查补全 |
| **批次 4（多源+评测）** | I-7、I-10 | 源适配层 + 评测闭环（可先于 I-11 出基线） |
| **批次 5（真机+召回）** | I-11、I-12 | 需真实麒麟/Milvus，独立环境 |
| **随时** | I-14 | 双重门禁偶发，影响 CI |

## 4. 涉及文件速查

- FACT 物理清理：`memoryhub/core/fact/**`、`memoryhub/adapter/api.py`（/facts 双读）、`scripts/migrate_facts_to_knowledge.py`、`tests/test_fact*`
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
