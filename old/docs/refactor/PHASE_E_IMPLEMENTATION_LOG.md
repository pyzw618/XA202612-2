# Phase E 实施记录：记忆分层落地（short/mid 存储 + 流转引擎 + 调度）

> 日期：2026-08-18
> 分支：`dev-remem`
> 依据：`docs/REFACTOR_PLAN_V2.md` §4.4（赛题要求 6：兼容短期/中期记忆流转）
> 验证环境：`mhub311` conda（Python 3.11.15）

## 1. 实施项（全部完成）

| 项 | 内容 | 关键文件 |
|---|---|---|
| **E1 存储** | `short_term_memory` / `mid_term_memory` 两新表；`ShortTermMemoryRepository`（add/list_by_session/list_all/delete_for_session/delete_expired）、`MidTermMemoryRepository`（add/get/list_active/mark_consolidated/delete）；`MemoryTierConfig`（short_ttl_hours/scheduler_enabled/consolidate_interval_seconds/degrade_health_threshold） | `storage/models.py`、`storage/database.py`、`config.py` |
| **E2 事件→短期** | `EventIngestionService` 保存安全事件后写一份 `short_term_memory`（TTL=24h），非破坏性 | `core/ingestion/service.py` |
| **E3 SessionConsolidator** | 按 `(user, session, task)` 聚合短期缓冲 → 中期情景（event_ids/summary/tools/occurred_at），清理短期 | `core/lifecycle/session_consolidator.py`（新增） |
| **E4 MemoryConsolidator** | 消费 active 中期情景 → 重放事件到 `ExtractionExecutor` → 长期；情景标记 `consolidated`（幂等） | `core/lifecycle/memory_consolidator.py`（新增） |
| **E5 MemoryDegrader** | 长期低健康度（<阈值）→ 写中期情景快照 + 归档长期 | `core/lifecycle/degrader.py`（新增） |
| **E6 LifecycleScheduler** | `threading.Thread(daemon=True)` 周期跑 `run_consolidation_cycle`；app.py startup 启动、shutdown 停止；`POST /lifecycle/consolidate` 手动触发 | `core/lifecycle/scheduler.py`（新增）、`app.py`、`management_api.py` |
| **E7 API/检索** | `SearchRequest.level/session_id`；`index_metadata.level`；`GET /short-term`（工作记忆）、`GET /mid-term`（情景） | `adapter/schemas.py`、`core/memory_write.py`、`management_api.py` |

## 2. 验证结果

- 新增测试 `tests/test_memory_tiers.py`（5 个）+ `test_api_acceptance.py` 1 个：
  1. 事件 → short_term 缓冲；
  2. `consolidate_sessions` → 中期情景 + 短期清理；
  3. `consolidate_episodes` → 长期 FACT 知识写入 + 情景标记 consolidated；
  4. 幂等（重跑不重复）；
  5. MemoryDegrader 低健康度 → 情景 + 归档；
  6. API：`POST /events` → `GET /short-term` 命中 → `POST /lifecycle/consolidate` → `GET /mid-term` 出现情景。
- 核心子集（改动覆盖区）：**205 passed / 2 skipped**。
- 全量：**865 passed / 16 failed / 7 skipped / 28 errors**；**失败集与基线逐条一致 → 无新增回归**（16+28 全为既有 milvus/embedding 环境问题）。
- 期间修复：ORM `DetachedInstanceError`（会话关闭后属性过期）→ 分层 repo 查询在会话内转 dict。

## 3. 已知问题（预存在）

- `test_api_02`/`test_api_03` 偶发失败（双重门禁 `invalid_safe_projection`，~1/5）——与 Phase A/B/C 记录一致；本次全量未触发。

## 4. 分层流转如何工作（供评审/文档引用）

```text
输入事件 → 短期记忆 short_term_memory（会话缓冲，TTL 24h）
  → SessionConsolidator（会话聚合）→ 中期记忆 mid_term_memory（情景，可查询/衰减）
  → MemoryConsolidator（重放抽取链）→ 长期记忆 preference/knowledge/fact
  → MemoryDegrader（长期低健康度）→ 中期情景快照（反哺流）
调度：LifecycleScheduler 周期执行（默认 300s，可配置）；也可 POST /lifecycle/consolidate 手动触发。
```

## 5. 本次未做（后续）

- 完整检索级联融合（session→mid→long 加权、短期注入对话上下文）——目前提供 level 过滤 + 短期/中期查询端点；
- 前端分层页面；
- AutoForgetEngine 字段级降级与分层深融合（降级已由 MemoryDegrader 轻量覆盖）。
