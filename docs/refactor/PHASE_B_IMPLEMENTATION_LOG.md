# Phase B 实施记录：FACT 并入知识记忆（后端核心）

> 日期：2026-08-18
> 分支：`dev-remem`
> 依据：`docs/REFACTOR_PLAN_V2.md` §4.8
> 验证环境：`mhub311` conda（Python 3.11.15）

## 1. 实施项（全部完成）

| 项 | 内容 | 关键文件 |
|---|---|---|
| **B1 数据模型** | `KnowledgeType.FACT`；`KnowledgeMemory` 加 `subject/predicate/object_value/object_type/single_value` 5 字段；`KnowledgeRow` 加对应列 + `(user_id, subject, predicate)` 索引；`_save`/`_know_row_to_pydantic` 映射；`index_text`/`index_metadata` 纳入 S/P/O | `adapter/schemas.py`、`storage/models.py`、`storage/database.py`、`core/memory_write.py` |
| **B2 共指修复** | `EntityNormalizer` 加 `RELATION_WORDS`（哥哥/妹妹/负责人/CEO…）；`normalize()` 顶部拦截返回稳定 `role:` 伪实体；`_add_alias_if_new` 跳过关系词 | `core/fact/normalizer.py` |
| **B3 FACT 冲突 matcher** | `KnowledgeUpdater.add()` 按 FACT 分支走 `_add_fact`：S/P/O 精确匹配 → 同则 REINFORCE、异且 `single_value` → SUPERSEDE（归档旧版+新版本）、异且多值 → COEXIST；连续冲突达 `_MAX_FACT_CONFLICT_VERSIONS=3` → REVIEW | `core/knowledge/updater.py` |
| **B4 FACT 抽取能力** | `KnowledgeExtractor.extract_facts()`：结构化工具结果确定性映射（不经 LLM）→ LLM 关系抽取兜底 → 无 LLM 返回空；`single_value` 仅明确单值谓词为 True；默认 ingestion 不切换（避免双写） | `core/knowledge/extractor.py` |
| **B5 API/检索** | `POST /memories/knowledge` 经 `KnowledgeMemory` 字段自动接受 `knowledge_type=fact`；检索经 `index_text` 命中 "S P O" | `adapter/api.py`（无需改端点） |

## 2. 验证结果

- 新增测试 `tests/test_knowledge/test_knowledge_fact.py`（7 个）+ `test_api_acceptance.py` 1 个：
  1. FACT duplicate → 证据合并不覆盖（REINFORCE）；
  2. 单值冲突 → 旧版归档 + 新版本（parent 链）；
  3. 多值冲突 → 共存；
  4. 连续冲突上限 → REVIEW；
  5. **共指用例**："哥哥/妹妹"不并入"老王"、不互为别名；
  6. `extract_facts` 结构化确定性映射 + 失败/空结果跳过；
  7. API 写 FACT + 混合检索命中。
- 核心子集（改动覆盖区）：**189 passed / 2 skipped**（含 8 个新测试）。
- 全量：**855 passed / 16 failed / 7 skipped / 28 errors**；**失败集与基线逐条一致 → 无新增回归**（16+28 全是既有 milvus/embedding 环境问题）。

## 3. 已知问题（预存在，非本次引入）

- `test_api_02`/`test_api_03` 偶发失败（双重门禁 `invalid_safe_projection`，约 1/5）——与 Phase A 记录一致；本次全量跑未触发。

## 4. 本次未做（归 Phase C）

- 存量 `facts` 表 → knowledge(FACT) 迁移、`fact_evidence`→`memory_evidence`、`FactStore`/`FactMemoryPipeline` 冻结删除、前端 FactPage 切换、默认 ingestion 切到 FACT（`extract_facts` 已备好但未接入 `run_knowledge`）。
