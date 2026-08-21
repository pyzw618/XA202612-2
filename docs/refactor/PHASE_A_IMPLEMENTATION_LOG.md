# Phase A 架构收尾实施记录

> 日期：2026-08-18
> 分支：`dev-remem`
> 依据：`docs/refactor/REFACTOR_PLAN_V2.md`（Phase A，用户已确认范围与半衰期取值）
> 验证环境：`mhub311` conda（Python 3.11.15）

## 1. 实施项（全部完成）

| 项 | 内容 | 关键文件 |
|---|---|---|
| **R4 统一 freshness** | 删除 `confidence.freshness_from_age_days`（双公式分歧源）；三个 Handler 统一走 `freshness.py:candidate_freshness`；半衰期对齐设计值 **Fact 90 / Preference 180 / Knowledge 120** 天 | `core/memory/freshness.py`、`core/memory/confidence.py`、`core/{fact,preference,knowledge}/handler.py` |
| **§4.5.3 艾宾浩斯强化** | `health.py` stability = `半衰期 / ln2`，使健康度与 freshness 共用同一条遗忘曲线；访问频率仍作"复习强化" | `core/forget/health.py` |
| **R8 门禁回执** | `upsert_memory` 门禁路径返回 `MemoryWriteReceipt`（替换 `return None`） | `core/memory_write.py` |
| **R6 旁路封堵** | `adapter/service.py` 偏好兜底改走 `MemoryWriteService`（保留版本归档语义，用 `action=SUPERSEDE` 表达）；旁路测试扩展覆盖整个 `adapter/` 层 | `adapter/service.py`、`tests/test_no_production_write_bypass.py` |
| **§4.9.2 反馈闭环** | `feedback confirm` → `access_count_30d+1` + `last_accessed_at` 刷新 + 健康度重算（艾宾浩斯复习反弹）；`reject` → 归档 + 健康度归零 | `adapter/api.py` |
| **R3 决策集合补全** | `MemoryAction` 扩为 8 动作（对齐 `schemas.MemoryDecision`）；`BaseMemoryHandler` 新增 `classify_relation` 钩子；偏好产 `duplicate/supersede/update`，知识产 `duplicate/update` | `core/memory/base.py`、`core/preference/handler.py`、`core/knowledge/handler.py` |
| **R1 双轨合一** | `EventProcessingCoordinator` 内部构建 Handler 链，偏好/知识抽取走统一 `process → apply`；**删除 CASE 知识丢弃过滤**；保留结构化直写、中文对话兜底、Fact 候选暂存 | `core/processing.py` |
| **KYLIN 契约** | 新增 `docs/kylin/KYLIN_EMBEDDING_RUNTIME_CONTRACT.md`（版本/架构/.so/DBus/模型/768 维/profile）与 `scripts/check_kylin_embedding_runtime.py`（8 项部署前检查） | `docs/`、`scripts/` |

## 2. 验证结果

| 指标 | 基线 | 实施后 |
|---|---|---|
| 核心子集（改动覆盖区） | 153 passed / 2 skipped | **169 passed / 2 skipped**（+新增测试） |
| 全量 passed | 843 | **847** |
| 全量 failed | 16 | **16**（集合与基线逐条一致） |
| errors | 28 | **28**（同基线） |

- **失败集与基线完全一致 → 无新增回归**。16 failed + 28 errors 全部是 milvus/embedding 环境问题（本机非麒麟/缺 mock `.so`，`embedding.mock_unavailable`），与本次改动无关。
- 新增测试：门禁回执（`test_domain_memory_writer.py`）、反馈闭环断言（`test_api_acceptance.py`）、R3 决策分类 ×2（`test_core_memory_unification.py`）。

## 3. 已知偶发问题（预存在，非本次引入）

**`tests/test_api_acceptance.py::test_api_03_preferences_list_detail_versions` 偶发失败（约 1/5）**

- 症状：`gate.downstream_failed` → 根因 `memory_write.invalid_safe_projection`（安全门禁在偏好抽取 → `upsert_memory` → 二次门禁路径上重建安全投影失败）。
- 验证：在干净 HEAD 上连跑 5 次也失败 1 次 → **预存在 flake**，非 Phase A 改动引入。
- 推测根因：事件级门禁 + 记忆级门禁的"双重门禁"路径偶发产生不一致的安全投影（`build_memory_write_event` 的 envelope 重建失败）。
- **待办**：单独立项排查"双重门禁"路径；缓解方向——抽取写入跳过第二次门禁（事件已安全）或统一为单次门禁。

## 4. 本次未做（后续阶段）

- B/C：FACT 并入知识记忆 + 存量迁移（REFACTOR_PLAN_V2 §4.8）
- D：多源适配层、ToolPreferenceMiner、配置版本化
- E：记忆分层落地（short_term/mid_term 新表）
- F：评测闭环 + 检索召回攻坚
- G：NL 语义遗忘
- H：CLI/MCP/Plugin 统一 API 收敛（本次只做了 §4.9.2 反馈闭环一项）
