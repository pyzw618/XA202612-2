# Phase C 实施记录：FACT 生产切换（消除双写 + /facts 转发 + 存量迁移）

> 日期：2026-08-18
> 分支：`dev-remem`
> 依据：`docs/refactor/REFACTOR_PLAN_V2.md` §4.8.8
> 验证环境：`mhub311` conda（Python 3.11.15）

## 1. 实施项（全部完成）

| 项 | 内容 | 关键文件 |
|---|---|---|
| **C1 ingestion 切换** | `RuntimeConfig.fact_mode`（默认 `legacy`，可 `knowledge`）；`ExtractionExecutor` 在 `knowledge` 模式：`run_knowledge` 产 FACT 知识（`extract_facts` + `_add_fact` 冲突 matcher）、`run_fact` 返回 0（旧管线停用）→ **消除双写**；`app.py` 传参 | `config.py`、`core/ingestion/extraction.py`、`app.py` |
| **C2 /facts 转发** | `/facts` 系列双读：`knowledge(FACT)` + legacy `fact_store` 并集（`_fact_memory_to_dict` / `_legacy_fact_to_dict` / `_fact_knowledge_lookup`）；list/get/evidence/delete/conflicts 均兼容两种来源 | `adapter/api.py` |
| **C3 迁移脚本** | `scripts/migrate_facts_to_knowledge.py`：facts→knowledge(FACT)（实体/谓词解析规范名、幂等 memory_id、`KnowledgeUpdater` 写入复用冲突 matcher）、`--dry-run`/`--report` | `scripts/migrate_facts_to_knowledge.py` |

## 2. 验证结果

- 新增测试 `tests/test_fact_knowledge_transition.py`（3 个）+ `test_api_acceptance.py` 1 个：
  1. `fact_mode=knowledge`：事件 → knowledge(FACT) 写入，legacy facts 表零写入；
  2. `fact_mode=legacy`：run_fact 照常走旧管线（默认不变）；
  3. 迁移脚本：facts→knowledge(FACT) 且重跑幂等；
  4. `/facts` 转发命中 knowledge(FACT)。
- 核心子集（改动覆盖区）：**200 passed / 2 skipped**。
- 全量：**859 passed / 16 failed / 7 skipped / 28 errors**；**失败集与基线逐条一致 → 无新增回归**。
- 期间发现并修复：`/facts` 纯转发会破坏 legacy facts 可见性（`test_api_09`、`test_competition_api` 2 个用例）→ 改为**双读**后全部恢复，失败集回到基线。

## 3. 已知问题（预存在）

- `test_api_02`/`test_api_03` 偶发失败（双重门禁 `invalid_safe_projection`，~1/5）——与 Phase A/B 记录一致；本次全量未触发。

## 4. 如何切换到 knowledge 模式

```yaml
# config.yaml
runtime:
  fact_mode: knowledge   # 生产翻开关；默认 legacy
```

切换后：事件中的工具结果 → knowledge(FACT)（经 `extract_facts` + 冲突 matcher），旧 `facts` 表零写入；`/facts` API 仍能读到存量 legacy facts（双读），随后可运行迁移脚本把存量合并进 knowledge。

## 5. 本次未做（后续）

- `FactStore`/`FactMemoryPipeline`/`FactIndexService` 物理删除（FACT 稳定一个迭代后）；
- 前端 FactPage 数据源切换；
- 生产 config.yaml 翻 `fact_mode=knowledge`（由团队择机）。
