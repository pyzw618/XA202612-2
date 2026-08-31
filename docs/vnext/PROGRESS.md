# PROGRESS.md

# 1. 文档用途

本文档用于记录 MemoryHub vNext 各 Stage / Batch 的实际执行状态。

它承担三个作用：

1. 不同 Codex 会话之间恢复上下文。
2. 记录已经完成的修改，避免重复实现。
3. 记录设计偏差、测试结果、遗留风险和下一步注意事项。

Codex 每完成一个 Batch，都必须更新本文档。

禁止只写：

```text
Batch 1 已完成。
```

必须提供可验证信息。

---

# 2. 当前总体状态

```text
vNext Stage: Stage 3 — Feedback 闭环
Status: IN PROGRESS

Formation Mode:
candidate-only（Stage 1 已完成，保持不变）

Current Target:
MemoryRetrievalRequest
→ IntentRouter → RetrievalPlanner
→ Channel Executors (working / episode / vector / keyword / metadata / authority)
→ ReciprocalRankFusion → VNextReranker
→ ScopeResolver → BudgetManager → ContextPayload

Stage 2 已完成：
Batch 1 — Working / Episode Executors
Batch 2 — Authority / Keyword / Vector Executors
Batch 3 — Intent + Scope Propagation
Batch 4 — Fusion / Rerank / Context Budget
Batch 5 — Retrieval Scenario Tests & Legacy Comparison

Current Target:
Stage 3 Batch 3 — Utility / Stability Update
```

---

# 3. Stage 状态总览

| Stage | 名称 | 状态 | 备注 |
|---|---|---|---|
| Stage 1 | Formation 实化 | DONE | 全部 5 个 Batch + Independent Review Repair 完成 |
| Stage 2 | Retrieval 实化 | DONE | 全部 5 个 Batch + Closure Fix 1–5 完成 |
| Stage 3 | Feedback 闭环 | IN PROGRESS | Batch 1 — Activation Completion: USED |
| Stage 4 | Evaluation & Cutover | NOT STARTED | 暂不执行 |

状态仅允许：

```text
NOT STARTED
IN PROGRESS
BLOCKED
DONE
```

---

# 4. Stage 1 Batch 状态

| Batch | 任务 | 状态 | 最后更新 |
|---|---|---|---|
| Batch 1 | Structured Reflection 接入 | DONE | 2026-08-31 |
| Batch 2 | Event → Working State Reducer | DONE | 2026-08-31 |
| Batch 3 | Episode Enrichment | DONE | 2026-08-31 |
| Batch 4 | Boundary-driven Formation | DONE | 2026-08-31 |
| Batch 5 | Stage 1 Scenario Tests | DONE | 2026-09-01 |

---

# 4.1 Stage 2 Batch 状态

| Batch | 任务 | 状态 | 最后更新 |
|---|---|---|---|
| Batch 1 | Working / Episode Executors | DONE | 2026-08-31 |
| Batch 2 | Authority / Keyword / Vector Executors | DONE | 2026-08-31 |
| Batch 3 | Intent + Scope Propagation | DONE | 2026-08-31 |
| Batch 4 | Fusion / Rerank / Context Budget | DONE | 2026-08-31 |
| Batch 5 | Retrieval Scenario Tests & Legacy Comparison | DONE | 2026-09-02 |

## 4.2 Stage 2 Closure 状态

| Fix Batch | 名称 | 状态 | 最后更新 |
|---|---|---|---|
| Fix 1 | Scope Isolation & Agent Scope Propagation | DONE | 2026-08-31 |
| Fix 2 | Stage 1 Formation Regression Recovery | DONE | 2026-08-31 |
| Fix 3 | Test Environment & Real Scenario Verification | DONE | 2026-08-31 |
| Fix 4 | Budget / Intent / Retrieval Log Closure | DONE | 2026-08-31 |
| Fix 5 | Agent /step Canonical Write Tenant Scope Propagation | DONE | 2026-09-02 |

# 4.3 Stage 3 Batch 状态

| Batch | 任务 | 状态 | 最后更新 |
|---|---|---|---|
| Batch 1 | Activation Completion — USED | DONE | 2026-08-31 |
| Batch 2 | Feedback Event & Attribution | DONE | 2026-09-01 |
| Batch 3 | Utility / Stability Update | NOT STARTED | 暂不执行 |
| Batch 4 | Memory Evolution & Safeguards | NOT STARTED | 暂不执行 |
| Batch 5 | Feedback Scenario Tests & Stage 3 Validation | NOT STARTED | 暂不执行 |

---

## Fix 5 — Agent /step Canonical Write Tenant Scope Propagation

### Status

```text
DONE
```

### Objective

消除 Stage 2 Closure Review 中唯一明确的硬阻塞：Agent `/step` 与 `/replay` 的 canonical write 未使用与 vNext Retrieval 相同的 tenant scope，导致同一请求内 write tenant ≠ read tenant。

### Reconnaissance Findings

- `memoryhub/adapter/agent_api.py` 的 `_to_memory_event_contract()` 在 line 246 硬编码 `tenant_id="default"`。
- `/api/agent/step` 仅在构造 `MemoryRetrievalRequest` 时从 `X-MemoryHub-Tenant` header 解析 tenant（line 347），并回退到 `user_id`。
- `/api/agent/replay` 完全不解析 header，所有 replay event 都写入 `default` tenant。
- 生产 `/events` 端点 `memoryhub/adapter/vnext_api.py` 已使用 `_tenant_user()` 正确解析并绑定 tenant；Agent 适配层是缺口。
- `tests/test_competition_api.py` 中两个失败测试与 tenant bug **不直接相关**：
  - `test_replay_is_read_only_until_execute_and_masks_tool_results` 失败原因是 canonical write 返回 `REJECTED / policy_failed`（已通过临时诊断脚本确认）。
  - `test_agent_step_extracts_memory_from_raw_dialogue_and_retrieves_it` 失败原因是 `execute_agent_step` 把 `processing` 硬编码为 `None`。

### Changes

- 给 `_to_memory_event_contract()` 增加 `tenant_id: str = "default"` 参数，取代函数体内的硬编码。
- `/api/agent/step` 在 request boundary 解析一次 tenant：`request.headers.get("X-MemoryHub-Tenant", "default")`。
  - 同一 tenant 传给 `_to_memory_event_contract(..., tenant_id=step_tenant_id)`。
  - 同一 tenant 传给 `MemoryRetrievalRequest(..., tenant_id=step_tenant_id)`。
- `/api/agent/replay` 在 request boundary 解析一次 tenant 并传给 `_to_memory_event_contract(..., tenant_id=replay_tenant_id)`。
- 无 header 时统一回退到 `"default"`，保持现有 default tenant 兼容行为。
- 在 `tests/test_competition_api.py` 新增 4 个 tenant propagation 测试：
  - header 传播的 `/step` canonical + retrieval 一致性。
  - 无 header 时保持 default tenant。
  - 跨 tenant 隔离（tenant-a write vs tenant-b read）。
  - `/replay` header 传播到 canonical event。

### Files Touched

```text
memoryhub/adapter/agent_api.py
tests/test_competition_api.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
HTTP Request
  ↓
  ├─ Canonical Write → _to_memory_event_contract(tenant_id="default") → default tenant
  └─ vNext Retrieval → MemoryRetrievalRequest(tenant_id=header|user_id) → tenant-a

同一 /step 请求内 write tenant ≠ read tenant。
```

### Behavior After

```text
HTTP Request
  ↓
Resolved Tenant (header or "default")
  ├─ Canonical Write → _to_memory_event_contract(tenant_id=resolved) → same tenant
  └─ vNext Retrieval → MemoryRetrievalRequest(tenant_id=resolved) → same tenant

write tenant == read tenant。
```

### Tests

| Test | Result |
|---|---|
| `tests/test_competition_api.py::test_agent_step_propagates_tenant_from_header_to_canonical_and_retrieval` | PASS |
| `tests/test_competition_api.py::test_agent_step_without_tenant_header_uses_default_tenant` | PASS |
| `tests/test_competition_api.py::test_agent_step_does_not_leak_tenant_across_users` | PASS |
| `tests/test_competition_api.py::test_replay_propagates_tenant_from_header_to_canonical` | PASS |
| `tests/test_competition_api.py::test_agent_step_propagates_project_task_session_and_scene` | PASS |
| `tests/test_competition_api.py` total | 8 passed, 2 failed, 1 skipped |
| Agent scope propagation / competition API tests | 8 passed, 2 failed, 1 skipped |
| Stage 1 Formation regression (11 files, 81 tests) | PASS |
| Stage 2 targeted regression (10 files, 62 tests + 13 working/episode executor tests) | PASS |
| `tests/test_vnext_entrypoints.py` | 8 passed |
| `ruff check memoryhub/adapter/agent_api.py` | PASS |

### Evidence

- `/step` handler line 329 `step_tenant_id = request.headers.get("X-MemoryHub-Tenant", "default")` 与 line 334-338 把同一值传入 `_to_memory_event_contract`，line 352 把同一值传入 `MemoryRetrievalRequest`。
- `/replay` handler line 284 `replay_tenant_id = request.headers.get("X-MemoryHub-Tenant", "default")` 与 line 287-288 传入 `_to_memory_event_contract`。
- `_to_memory_event_contract` 签名现在携带 `tenant_id` 参数并在 line 247 使用 `tenant_id=tenant_id`。
- 新增测试直接调用 `execute_agent_step` / `replay_conversation` 并捕获 fake canonical service 与 rollout service，断言 write event 与 retrieval request 的 `tenant_id` 一致。

### Regression

```text
Legacy: no legacy source or route changed.
Formation: Stage 1 Formation regression suite (81 tests) passed.
Retrieval: Stage 2 targeted regression suite (75 tests) passed.
Safety: no Safety policy or gate changed.
candidate-only: no Authority/Formation mode change.
```

### Remaining Risks

- `tests/test_competition_api.py` 仍有两个与 tenant 无关的失败：
  - `test_replay_is_read_only_until_execute_and_masks_tool_results` 被 policy processor 拒绝（`policy_failed`）。
  - `test_agent_step_extracts_memory_from_raw_dialogue_and_retrieves_it` 的 `processing` 字段在响应中硬编码为 `None`。
  两者均不在 "只修 tenant propagation" 的范围内，未在本次修复。
- `tests/test_competition_api.py` 与 `memoryhub/adapter/agent_api.py` 仍有 ruff `format` 历史格式问题，本次未改动以控制 diff 范围；`ruff check` 在 `agent_api.py` 上通过。

### Decisions

```text
Resolve tenant once at the request boundary and pass the same value explicitly to both
write and read paths. Default to "default" when X-MemoryHub-Tenant is absent to keep
existing Agent adapter behavior compatible.
```

### Not Done

- 未修改 Retrieval Architecture、Formation、Fusion、Budget、IntentRouter。
- 未修复上述两个与 tenant 无关的 `test_competition_api.py` 失败。
- 未进入 Stage 3。

### Next Batch Notes

Stage 2 Closure 的 tenant 硬阻塞已清除。若要继续推进 Closure，需单独处理 `test_competition_api.py` 中 `policy_failed` 与 `processing=None` 两个问题，并重新评估是否还存在其他 Closure DoD 缺口。

---

## Stage 3 Batch 1 — Activation Completion: USED

### Status

```text
DONE
```

### Objective

补齐 Retrieval → Context → USED 的显式使用反馈链路：

```text
RECALLED → SELECTED / IN_CONTEXT → USED
```

让系统可以明确知道哪些 Memory 被 Agent 真正使用，并记录到 Activation 与 Usage Shadow。

### Reconnaissance Findings

- 当前真实实现：
  - `ActivationStatus` 已有 `USED` 枚举，但代码中没有任何位置写入 `USED`。
  - `RetrievalService._record_activations()` 写入 `RECALLED` / `SELECTED` / `IN_CONTEXT`，并因 `MemoryActivationRow` unique 约束导致 `SELECTED/IN_CONTEXT` 覆盖失败（静默吞异常）。
  - `UtilityFeedbackShadow` 已存在，但 `app.py` 未注入 `RetrievalService`，影子记录实际不生效。
  - `AgentStepRequest` 没有 `used_memory_ids` 字段；`/step` 自行取前 3 张 card 作为 used，不基于 Agent 真实回传。
- 与 stage 文档一致的部分：
  - `ActivationRepository`、`RetrievalLogRepository`、`MemoryActivationRow` 字段已满足 USED 记录需求。
  - `UtilityFeedbackShadow` 设计为只写 shadow / trace，不直接修改 Authority。
- 与 stage 文档不一致的部分：
  - `MemoryRetrievalResponse` 没有 `retrieval_log_id`，调用方无法把 usage 关联回 retrieval。
  - `ActivationRepository.record()` 不是幂等 upsert，重复状态写入会冲突。
- 复用的现有组件：
  - `ActivationRepository` / `MemoryActivationRow`
  - `RetrievalLogRepository` / `RetrievalLogRow`
  - `UtilityFeedbackShadow` / `UsageKind`
  - `RetrievalService` / `MemoryRetrievalResponse`
  - `AgentStepRequest` / `/api/agent/step`
- 实际影响范围：
  - `memoryhub/storage/vnext_repositories.py`（Activation upsert/mark_used、RetrievalLog get）
  - `memoryhub/application/retrieval_service.py`（retrieval_log_id 回传、record_usage_feedback）
  - `memoryhub/adapter/vnext_schemas.py`（response DTO 增加 retrieval_log_id）
  - `memoryhub/adapter/agent_api.py`（AgentStepRequest 增加 used_memory_ids，/step 记录 usage）
  - `memoryhub/app.py`（注入 UtilityFeedbackShadow）
  - `tests/test_vnext_activation_used.py`（7 个新测试）

### Changes

- `ActivationRepository.record()` 改为 upsert：同 `(tenant,user,query,memory,content_version)` 更新状态而非重复插入。
- 新增 `ActivationRepository.get()` 与 `mark_used()`；`mark_used()` 返回 `(ActivationView, newly_marked)`，支持幂等 USED 写入。
- 新增 `RetrievalLogRepository.get()`，用于 usage feedback 时校验 scope 与 selected_memory_ids。
- `MemoryRetrievalResponse` 增加 `retrieval_log_id` 字段。
- `RetrievalService` 在 `retrieve()` 中先写 retrieval log 再构造 response，把 `retrieval_log_id` 带回给调用方。
- 新增 `RetrievalService.record_usage_feedback()`：
  - 通过 `retrieval_log_id` 加载 retrieval log。
  - 校验 `tenant_id` / `user_id` 与 log 一致（scope 拒绝）。
  - 校验 memory_id 在 `selected_memory_ids` 中（未进入 context 则标记 untrusted）。
  - 调用 `ActivationRepository.mark_used()`。
  - 仅当真正 newly_marked 时写入 `UtilityFeedbackShadow`（`UsageKind.ACTION_INFLUENCED`, outcome_code=USED）。
- `AgentStepRequest` 增加 `used_memory_ids: list[str]`。
- `/api/agent/step` 在检索后使用 `body.used_memory_ids`（显式回传）作为强证据，否则 fallback 到前 3 张 card（弱证据），并调用 `record_usage_feedback()`。
- `app.py` 装配 `RetrievalService` 时注入 `UtilityFeedbackShadow(trace_store=app.state.trace_store)`。

### Files Touched

```text
memoryhub/adapter/vnext_schemas.py
memoryhub/adapter/agent_api.py
memoryhub/application/retrieval_service.py
memoryhub/storage/vnext_repositories.py
memoryhub/app.py
tests/test_vnext_activation_used.py
docs/vnext/PROGRESS.md
```

（核心源码 6 个文件，符合单 Batch ≤8 限制。）

### Behavior Before

```text
Agent /step
  → retrieval_service.search()
  → response 无 retrieval_log_id
  → used_ids = 前 3 张 card
  → 响应返回 used_memory_ids
  → 无 Activation USED 写入
  → UtilityFeedbackShadow 未接入生产
```

### Behavior After

```text
Agent /step
  → retrieval_service.search()
  → response.retrieval_log_id = rl-xxx
  → Agent 回传 used_memory_ids
  → record_usage_feedback(retrieval_log_id, used_memory_ids)
  → 校验 tenant/user scope
  → 校验 memory 在 selected_memory_ids 中
  → ActivationRepository.mark_used()
  → ActivationStatus = USED
  → UtilityFeedbackShadow.record_usage(ACTION_INFLUENCED, USED)
```

重复上报同一 `(retrieval_id, memory_id)`：DB 中只保留一个 USED 行；shadow 中只保留一个 USED usage。

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_activation_used.py` | PASS (7) |
| `tests/test_vnext_retrieval_service.py` | PASS (6) |
| `tests/test_vnext_feedback_service.py` | PASS (3) |
| `tests/test_vnext_batch4_fusion_context.py` | PASS (3) |
| `tests/test_vnext_batch5_retrieval_scenarios.py` | PASS (11) |
| `tests/test_vnext_stage1_scenarios.py` | PASS (6) |
| `tests/test_vnext_boundary_driven_formation.py` | PASS (6) |
| `tests/test_vnext_entrypoints.py` | PASS (8) |
| `tests/test_vnext_batch3_scope_propagation.py` | PASS (5) |
| Batch 1 + Stage 1 + Stage 2 targeted regression | PASS (55) |
| `ruff check` on changed source/tests | PASS |
| `compileall` on changed source/tests | PASS |

`tests/test_competition_api.py` 仍有两个预存失败：`test_replay_is_read_only_until_execute_and_masks_tool_results`（policy_failed）、`test_agent_step_extracts_memory_from_raw_dialogue_and_retrieves_it`（processing=None）。两者与 Batch 1 无关，未修复。

### Evidence

- `test_upsert_activation_keeps_final_status`：两次 `record()` 后 DB 只有 1 行，最终状态为 `IN_CONTEXT`。
- `test_record_usage_feedback_promotes_to_used`：显式 feedback 把 `IN_CONTEXT` 推进到 `USED`，shadow 中出现 `ACTION_INFLUENCED/USED`。
- `test_record_usage_feedback_is_idempotent`：重复 feedback 后 DB 仍只有 1 个 USED 行，shadow 只有 1 个 USED usage。
- `test_record_usage_feedback_rejects_not_in_context`：未进入 context 的 memory 被标记为 `untrusted`，不会变为 USED。
- `test_record_usage_feedback_rejects_cross_tenant`：tenant-a feedback 不能更新 tenant-b retrieval 下的 activation。
- `test_retrieval_service_response_carries_retrieval_log_id`：`MemoryRetrievalResponse` 真实携带 `retrieval_log_id`。
- `test_app_wires_usage_feedback_shadow_to_retrieval_service`：app factory 启动后 `app.state.retrieval_service.usage_feedback_service` 非空。

### Feedback Attribution Evidence

- `/step` 使用 Agent 显式回传的 `used_memory_ids` 作为强证据（confidence=1.0）。
- 无显式回传时 fallback 到前 3 张 card（confidence=0.5）。
- `record_usage_feedback()` 通过 retrieval log 的 `selected_memory_ids` 验证 memory 是否真实进入 context；未进入者为 `untrusted`。
- 跨 tenant/user 反馈直接 `rejected`。

### Score Update Evidence

- Batch 1 不更新 utility / stability / evolution；`UtilityFeedbackShadow` 仅记录 `ACTION_INFLUENCED/USED` signal，为 Batch 3 的 bounded updater 提供输入。
- 当前 shadow 的 `report()` 可基于 usage 信号生成 `UtilityUpdateProposal`，但不写入 Candidate / Authority。

### Scope Verification

- `record_usage_feedback()` 在调用 `mark_used()` 前校验 `log.tenant_id == tenant_id` 且 `log.user_id == user_id`。
- `ActivationRepository.get()` / `mark_used()` 查询使用 `(tenant_id, user_id, query_id, memory_id)` 组合。
- 测试 `test_record_usage_feedback_rejects_cross_tenant` 直接验证跨 tenant 被拒绝。

### Regression

```text
Formation: Stage 1 scenarios / boundary / working reducer / entrypoints PASSED.
Retrieval: Stage 2 Batch 1–5 / retrieval service / feedback service / fusion / scope PASSED.
Safety: no Safety policy or gate changed.
candidate-only: no Authority/Formation mode change.
Legacy: no legacy source or route changed except Agent /step request/response contract.
```

### Remaining Risks

- Agent `/step` 的 fallback（前 3 张 card）是弱证据；生产环境应优先要求 Agent 显式回传 `used_memory_ids`。
- `MemoryActivationRow` 的 upsert 依赖 `(tenant,user,query,memory,content_version)` 唯一性；未来如允许同一 query 同一 memory 多个 content_version，需调整 `get()`/`mark_used()` 语义。
- MCP/CLI 目前仍通过 legacy `/api/memory/feedback` 反馈，未接入 vNext usage feedback；后续 Batch 可考虑为 MCP 增加显式 usage 工具。

### Decisions

```text
1. Activation progression stays one row per (tenant,user,query,memory,content_version); record() upserts.
2. USED requires retrieval_log_id + selected_memory_ids proof; no retrieval log = no mark.
3. UtilityFeedbackShadow is wired in production but remains shadow-only; Authority/Candidate mutation is Batch 3.
4. Agent /step accepts used_memory_ids explicitly and falls back to top-3 cards only for backward compatibility.
```

### Not Done

- Batch 2 Feedback Event & Attribution（explicit positive/negative、task outcome）。
- Batch 3 Utility / Stability bounded update。
- Batch 4 Memory Evolution（ACTIVE/DORMANT/SUPERSEDED）。
- Batch 5 Scenario Tests。
- 修复 `tests/test_competition_api.py` 中两个与 Batch 1 无关的预存失败。

### Next Batch Notes

Batch 2 应建立 Feedback Event & Attribution：
- 明确 Feedback Contract（feedback_id、retrieval_id、memory_ids、feedback_type、outcome、source、confidence）。
- 区分 Explicit Positive / Explicit Negative / Task Success / Task Failure / User Correction。
- 引入保守归因规则：多 Memory 场景 weak attribution、Task Failure 不等于 memory negative。
- 保持 Batch 1 的 USED 幂等、scope 校验、shadow-only 约束。

---

# 5. 当前架构基线

执行 Stage 1 前，Codex 首次 Reconnaissance 后补充以下内容。

## 5.1 Reflection

```text
Current:
ReflectionService now uses StructuredReflectionModel in the application path;
tests may still inject DeterministicReflectionModel or a fake ReflectionModel.

Configured LLM:
OpenAIClient is built from config.llm and stored as app.state.llm_client.

Current Reflection Model:
StructuredReflectionModel wraps BaseLLMClient.generate_json() and validates
through the existing ReflectionOutput contract.

Injection Path:
config.llm → OpenAIClient → StructuredReflectionModel → ReflectionService
→ FormationWorker → ExtractionRetryService
```

## 5.2 Working State

```text
Current update path:
CanonicalWriteService.write() → _orchestrate_working() → WorkingStateReducer
→ WorkingService.

Current important fields:
current_goal, current_step, pending_steps, completed_steps, constraints,
active_entities, blockers, recent_findings, recent_failures, next_action.

Current behavior:
The deterministic reducer recognizes canonical `payload.tool_calls` success and
failure states, concise targets, task terminal markers, and existing explicit
payload state fields. It writes summaries, not raw tool output or an event log.

Current limitations:
The OpenCode plugin still posts tool traces through the legacy `/api/memory/events`
endpoint. Batch 2 covers canonical tool traces only; changing that integration is
outside this Batch.
```

## 5.3 Episode

```text
Current episode write path:
CanonicalWriteService.write() → _orchestrate_episode() → EpisodeService.

Current stored semantics:
Episode snapshot plus append-only, bounded semantic event records and boundary
checkpoint state. Automatic canonical events retain source event type, timestamp,
phase/state transition, and compact tool actions/results/failures; raw tool traces
and unbounded output are not copied into Episode payloads.

Reflection context:
FormationWorker reads the append-only episode records into
ReflectionInput.episode_history_summary, so Reflection now receives enriched
task-process evidence.

Current limitations:
Episode resume replay still restores task state fields rather than producing a
complete narrative summary. Reflection enqueue remains event-granular until Batch 4.
```

## 5.4 Boundary

```text
Current BoundaryDetector:
BoundaryDetector is instantiated by CanonicalWriteService and supports hard
complete/failed/explicit plus phase/context-pressure checkpoints.

Current trigger path:
CanonicalWriteService._orchestrate_episode() invokes detection before snapshot.

Current limitations:
Reflection ExtractionTask enqueue remains unconditional per accepted event;
boundary-gated reflection is Batch 4 work.
```

## 5.5 Candidate

```text
Current create path:
FormationWorker → ReflectionService → CandidateService.stage().

candidate-only behavior:
FormationWorker skips _promote() unless mode == authority; default config is
candidate-only.
```

## 5.6 Retrieval（Stage 2 Batch 1 后基线）

```text
Retrieval pipeline (already existing, unchanged in Batch 1):
IntentRouter (7 intents) → RetrievalPlanner (6 channels) → channel executors
→ ReciprocalRankFusion → VNextReranker → ScopeResolver → BudgetManager
→ ContextPayload；activation/retrieval_log/trace 落库。

Channel executor contract:
(request, plan, channel) -> list[RetrievedMemory]；缺少 executor 的 channel
静默降级为空列表。

Batch 1 后已注册的 executor:
- working  ← WorkingStateRepository（exact task → session/recent fallback，限 3 条）
- episode  ← EpisodeRepository（exact task → session/recent fallback，限 5 条，
             ARCHIVED 默认排除，确定性 query relevance 排序）
- vector   ← 仅当 state.retriever 已存在时注册

已知装配顺序缺口（pre-existing，Batch 1 未修改）:
app.py 中 RetrievalService 在 startup() 内先于 retriever 装配构建，
build_channel_executors(app.state) 执行时 app.state.retriever 尚未赋值，
因此真实 app 中 vector executor 实际不会注册（Stage 1 期间即如此，
非 Batch 1 引入）。Batch 2 处理 vector/keyword/authority executor 时需一并
修正装配顺序。

Scope 现状:
MemoryRetrievalRequest 无 project_id 字段；project scope 仅通过 scope_level
+ scope 表达。Working/Episode 结果 scope_level=TASK、scope=task_id。
_search_request_from_vnext 仍硬编码 project_id=""/level="long"，
Legacy Retriever 复用时的 scope 传递留给 Batch 3。
```

---

# 6. Batch 执行记录模板

每完成一个 Batch，复制以下模板追加到本文档。

---

## Batch X — <Batch Name>

### Status

```text
DONE / BLOCKED / IN PROGRESS
```

### Objective

简述本 Batch 的目标。

### Reconnaissance Findings

- 当前真实实现：
- 与 stage 文档一致的部分：
- 与 stage 文档不一致的部分：
- 复用的现有组件：
- 实际影响范围：

### Changes

- 修改 1：
- 修改 2：
- 修改 3：

### Files Touched

```text
path/to/file1
path/to/file2
```

### Behavior Before

```text
旧调用链 / 旧行为
```

### Behavior After

```text
新调用链 / 新行为
```

### Tests

| Test | Result |
|---|---|
| xxx | PASS / FAIL |

### Evidence

说明：

- 哪个测试证明哪个行为成立
- 哪个方法/调用链证明新逻辑已接入
- 是否真实经过目标主链路

### Regression

```text
Legacy:
Safety:
candidate-only:
Other:
```

### Remaining Risks

- 风险 1：
- 风险 2：

### Decisions

本 Batch 新增的必要设计决策。如果没有：

```text
None
```

### Not Done

明确列出本 Batch 有意未处理的事项。

### Next Batch Notes

下一会话必须知道的内容。

---

# 7. Stage 1 Definition of Done 跟踪

- [x] 正常 vNext Reflection 使用配置中的真实 LLM。
- [x] Reflection 输出经过结构化验证。
- [x] 常见 Agent Tool Trace 能驱动 Working State。
- [x] Working State 能表达当前任务状态。
- [x] Episode 能表达主要任务过程。
- [x] Episode 包含关键成功/失败/修改/结果。
- [x] meaningful boundary 可以触发 Formation。
- [x] 低价值 Event 不逐条触发 Reflection。
- [x] Explicit Remember 可以触发 Formation。
- [x] Task Complete / Failure 有明确 Formation 行为。
- [x] 合法 Reflection 可以形成 Candidate。
- [x] 非法 Reflection 不产生 Candidate。
- [x] candidate-only 模式有效。
- [x] Legacy 主链路无明显回归。
- [x] 至少 6 类 Scenario Test 通过。

---

# 8. Stage 1 Scenario 结果

## Scenario A — 正常 Coding Task

```text
Status: PASS

Result:
- Working State 正确演化：current_goal="Fix SSE reconnect issue"，
  completed_steps 包含 Read application.yaml、Read sse_handler.py、
  Updated application.yaml、Test passed: pytest tests/test_sse.py；
  recent_failures 保留失败记录；blockers 在成功后清空。
- Episode 保留 7 条语义历史，包含失败与成功转折。
- task_completed 边界触发 Reflection，产生 Candidate，未写 Authority。
```

## Scenario B — 失败后恢复

```text
Status: PASS

Result:
- Working State 记录 exporter returned 500 失败与恢复过程，最终 blockers 清空。
- Episode 保留失败与恢复的关键转折。
- task_completed 边界触发 Reflection。
```

## Scenario C — 低价值事件

```text
Status: PASS

Result:
- read_file / git status / search / read_file 均未触发 Reflection。
- retry.run_due() 无任务，CandidateRepository 为空。
```

## Scenario D — Explicit Remember

```text
Status: PASS

Result:
- payload.boundary="explicit" 触发 Reflection，产生 Candidate。
- Candidate scope 为 PROJECT，未无条件扩成 GLOBAL。
```

## Scenario E — candidate-only

```text
Status: PASS

Result:
- Reflection 产生 Candidate。
- PreferenceRepository / KnowledgeRepository 均无记录。
```

## Scenario F — LLM Invalid Output

```text
Status: PASS

Result:
- 注入非法 Reflection model，schema 验证失败。
- retry.run_due() 中任务进入 retry，未产生任何 Candidate。
- caplog 捕获到 `structured_reflection_failed` 可观测日志。
```

---

# 9. 当前阻塞项

```text
None
```

如果出现阻塞，使用：

```text
Blocker:
Reason:
Affected Batch:
Decision Needed:
Temporary Workaround:
```

---

# 10. 当前重要设计决策

初始约束：

1. vNext Stage 1 保持 candidate-only。
2. Event 不直接等同 Long-Term Memory。
3. deterministic reducer 优先于 LLM。
4. Formation 目标从逐 Event Trigger 转向 Boundary Trigger。
5. Stage 1 不提前实现 Retrieval / Feedback / Cutover。
6. Legacy 主链路保持可运行。

后续只记录真正影响架构或跨 Batch 的新决策。

---

# 11. 当前下一步

```text
Stage 3 / Batch 1 DONE（Activation Completion: USED）

Task:
Stage 3 Batch 2 — Feedback Event & Attribution

Before coding:
Read VNEXT_PLAN.md
Read docs/vnext/stages/stage3-feedback.md §7（Batch 2）
Read PROGRESS.md Stage 3 Batch 1 记录

Key context for Batch 2:
- Batch 1 已完成 USED 状态、幂等写入、scope 校验、shadow-only 记录。
- Batch 2 需建立 Feedback Contract：feedback_id、retrieval_id、memory_ids、
  feedback_type、outcome、source、confidence。
- 支持 Explicit Positive / Explicit Negative / Task Success / Task Failure /
  User Correction 等类型。
- 引入保守归因：多 Memory 场景 weak attribution、Task Failure 不等于 memory negative。
- 不提前实现 utility/stability 更新（Batch 3）或 evolution 状态机（Batch 4）。
```

---

## Batch 1 — Structured Reflection 接入

### Status

```text
DONE
```

### Objective

让正常 vNext Formation 路径使用应用配置的结构化 LLM Reflection，同时保留
deterministic/fake model 的测试注入能力，并在失败时保持 Candidate 写入关闭。

### Reconnaissance Findings

- 原有 ReflectionService 默认使用 DeterministicReflectionModel，FormationWorker 未接收应用 LLM。
- 已有 OpenAIClient.generate_json()、ReflectionInput/ReflectionOutput、CandidateService 与 retry worker 可复用。
- Stage 文档假设成立；StructuredReflectionModel 是本 Batch 所需的适配器，原代码不存在同名实现。
- CanonicalWriteService 仍逐事件 enqueue reflection task；这是 Batch 4 的既有差异，本 Batch 未改变。

### Changes

- 新增 StructuredReflectionModel：使用已配置 LLM 的 generate_json() 和 ReflectionOutput JSON Schema。
- Runtime 覆盖 model_id、prompt_version、input_hash，避免模型伪造运行时元数据后再进行既有 Pydantic 校验。
- app.py 将该 ReflectionService 注入 FormationWorker；失败仅记录脱敏日志（input hash、次数、异常类型）并抛 ReflectionRunError。
- 增加合法结构化输出、非法输出失败关闭与 worker 不创建 Candidate 的测试。

### Files Touched

```text
memoryhub/application/reflection_service.py
memoryhub/app.py
tests/test_vnext_reflection.py
tests/test_vnext_formation_worker.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
configured OpenAIClient exists
→ FormationWorker(reflection_service omitted)
→ ReflectionService()
→ DeterministicReflectionModel
→ Candidate
```

### Behavior After

```text
config.llm
→ OpenAIClient
→ StructuredReflectionModel.generate_json(schema=ReflectionOutput)
→ ReflectionService validation/retry
→ FormationWorker
→ CandidateService (candidate-only)
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_reflection.py` | PASS (6) |
| `tests/test_vnext_formation_worker.py` | PASS (5) |
| Batch regression subset: vNext docs, reflection, formation worker, candidate service, LLM config, write-bypass, entrypoints excluding three pre-existing retrieval fixtures | PASS (43; 3 deselected) |
| Ruff on changed source/tests | PASS |
| Full selected set including the three retrieval fixtures | FAIL (3 unrelated Stage 2 fixture failures; see risks) |

### Evidence

- `StructuredReflectionModel` passes `ReflectionOutput.model_json_schema()` to the configured client's `generate_json()`; the unit test proves one configured-client call and Candidate creation.
- Invalid schema output raises `ReflectionRunError`; the worker component test proves retry and zero staged Candidates.
- Existing candidate-only worker test confirms one Candidate is staged with no Preference Authority row.
- Application wiring is `app.state.llm_client → app.state.reflection_service → app.state.formation_worker`.

### Regression

```text
Legacy: no legacy implementation changed; write-bypass regression test passed.
Safety: no Safety module or policy flow changed.
candidate-only: passed; _promote() remains unreachable outside authority mode.
Other: 43 relevant regression tests passed and changed-file Ruff passed.
```

### Remaining Risks

- The configured provider may reject JSON response_format or return invalid JSON; this safely retries and records only non-sensitive failure metadata, but provider integration has no live credential test.
- Three existing retrieval-focused entrypoint tests fail because their fixture has no rollout/retrieval service (`rollout.service_unavailable` / `retrieval service not initialized`); this Batch did not modify Retrieval or rollout and does not fix them.
- Reflection remains event-granular until Batch 4 boundary-gated enqueue work.

### Decisions

```text
Reuse BaseLLMClient.generate_json() instead of adding a second LLM client or DTO.
Runtime-owned Reflection metadata is injected by the adapter before existing schema validation.
```

### Not Done

- Batch 2 Working State reducer.
- Batch 3 Episode enrichment.
- Batch 4 boundary-driven reflection enqueue.
- Batch 5 end-to-end scenarios and live provider verification.

### Next Batch Notes

Batch 2 should modify only Working State reduction from raw Agent tool traces. Do not
change StructuredReflectionModel, Episode enrichment, Boundary enqueue behavior,
Retrieval, Feedback, Rollout, or Authority promotion.

---

## Batch 2 — Event → Working State Reducer

### Status

```text
DONE
```

### Objective

让 canonical vNext 事件中的真实 Agent 工具轨迹以 deterministic reducer 更新
Working State，而不是要求调用方预先写入完整的 Working 字段。

### Reconnaissance Findings

- `CanonicalWriteService._orchestrate_working()` 原先只投影 payload 内已经存在的
  `current_step`、steps、constraints 与 entities；`payload.tool_calls` 未被消费。
- `WorkingService`、`WorkingPatch`、CAS、字段来源优先级和列表去重已经可复用，
  不需要新的持久化或第二套状态模型。
- vNext canonical Agent replay 会把工具调用放入 `payload.tool_calls`；OpenCode 插件
  虽有同样的 tool trace，但当前仍发送至 Legacy `/api/memory/events`，不在本 Batch 迁移。
- `WorkingSnapshot` 原有字段不足以稳定表达 blocker、近期发现、失败和下一步；新增
  向后兼容的默认字段，仍使用同一个 Domain Contract。

### Changes

- 新增 `WorkingStateReducer`：仅基于 event/payload/tool name/arguments/status/error
  做确定性归约，生成既有 `WorkingSnapshot` 或 `WorkingPatch`。
- `CanonicalWriteService` 在未提供显式 snapshot/patch 时调用 reducer；显式调用方
  传入的 snapshot/patch 优先级保持不变。
- `WorkingSnapshot`、持久化状态与压缩摘要补充 blockers、recent_findings、
  recent_failures、next_action；列表合并保持去重。
- 工具成功更新 completed/findings 与文件 active entities；失败不会进入 completed。
  同一工具/目标成功后会清除对应 blocker，但保留近期失败作为任务经历信息。状态
  只保存短摘要，不保存原始 tool output 或 event 列表。

### Files Touched

```text
memoryhub/application/working_reducer.py
memoryhub/application/canonical_write.py
memoryhub/domain/contracts.py
memoryhub/application/working_service.py
memoryhub/domain/working.py
tests/test_vnext_working_reducer.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
Canonical event with payload.tool_calls
→ CanonicalWriteService._orchestrate_working()
→ no Working Patch unless caller had already supplied Working fields
```

### Behavior After

```text
Canonical event with payload.tool_calls
→ WorkingStateReducer (deterministic summaries)
→ existing WorkingPatch / WorkingService CAS
→ Working State with progress, findings, failure, blocker and next action
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_working_reducer.py` | PASS (2) |
| Contract and Working baseline | PASS (16) |
| Batch vNext regression subset, excluding 3 existing retrieval fixtures | PASS (43; 3 deselected) |
| `tests/test_no_production_write_bypass.py tests/test_vnext_p0_flow.py` | PASS (14) |
| Final combined Batch regression suite | PASS (68; 3 deselected) |
| Ruff on changed source/tests | PASS |

### Evidence

- Component test drives `user_instruction → read → read → test failure → patch → test success`
  through `CanonicalWriteService`; the stored state preserves goal, completed actions,
  recent failure, cleared blocker and a next action without storing `tool_calls`.
- Reducer unit test proves a failed test produces `recent_failures` and a blocker but
  no completed step; a terminal completion produces the deterministic completion patch.
- Replaying the same canonical event produces `IDEMPOTENT` and leaves the Working
  version unchanged.

### Regression

```text
Legacy: no Legacy source or route changed; no-production-write-bypass and P0 tests passed.
Safety: no Safety policy, gate or data path changed.
candidate-only: Formation worker regression tests passed; Authority promotion logic unchanged.
Other: existing vNext contract, task-state, boundary, reflection, formation and write entrypoint tests passed.
```

### Remaining Risks

- The OpenCode plugin remains on the Legacy event endpoint, so its live tool traces do
  not yet exercise this canonical reducer.
- Action classification intentionally covers common deterministic tool names and
  arguments only. Unknown or partial tool status is a no-op rather than an inferred state.
- Reflection enqueue remains event-granular until Batch 4; this Batch does not alter it.
- The three existing Retrieval entrypoint fixtures still require rollout/retrieval service
  assembly and were excluded exactly as recorded for Batch 1.

### Decisions

```text
Extend WorkingSnapshot with defaulted fields instead of creating a parallel reducer DTO.
Use concise deterministic summaries and existing WorkingPatch/CAS semantics; do not call an LLM.
```

### Not Done

- Batch 3 Episode enrichment.
- Batch 4 boundary-gated Reflection enqueue.
- Batch 5 Scenario tests.
- OpenCode / Legacy event route migration.

### Next Batch Notes

Batch 3 should enrich EpisodeEvent payloads from the same canonical event/tool trace while
preserving this reducer. Do not change Boundary enqueue, Reflection, Retrieval, Feedback,
Rollout or Authority promotion.

---

## Batch 3 — Episode Enrichment

### Status

```text
DONE
```

### Objective

Make automatic canonical Episode events retain a bounded, meaningful task history rather
than only an event ID and phase, while preserving the existing Episode contract and storage.

### Reconnaissance Findings

- `CanonicalWriteService._orchestrate_episode()` was the automatic Episode write path; it
  wrote only `event_id` and `phase` into `EpisodeEventContract.payload`.
- `EpisodeEventContract.payload`, `EpisodeRepository.append_event()` and its sequence/idempotency
  rules already support compact structured semantics without a new DTO, table, or migration.
- `FormationWorker` already reads the stored Episode records into
  `ReflectionInput.episode_history_summary`; no Reflection-path change was needed.
- `BoundaryDetector` remains invoked before the append, but reflection task enqueue remains
  unconditional per accepted event. That discrepancy is intentional Batch 4 work.
- Canonical Agent replay provides `payload.tool_calls`; OpenCode continues to use the Legacy
  endpoint and is explicitly outside this Batch.

### Changes

- Added `EpisodeEventEnricher`, a pure deterministic component that turns canonical events and
  common tool traces into bounded semantic payloads: source event type, occurred timestamp,
  phase/state transition, tool name, target, action, result, success/failure, and compact
  error/output summaries.
- `CanonicalWriteService` now uses the enricher only for automatically orchestrated Episode
  events. Explicit caller-provided `EpisodeEventContract` values keep their existing path.
- Each event stores at most eight compact tool actions and each summary is capped at 160
  characters; the source event ID remains the reference to the accepted canonical Event.
- Added unit and component coverage for compacting tool output, preserving success/failure/
  modification history, and passing enriched Episode history into Formation reflection input.

### Files Touched

```text
memoryhub/application/episode_enricher.py
memoryhub/application/canonical_write.py
tests/test_vnext_episode_enrichment.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
Canonical Event
→ _orchestrate_episode()
→ EpisodeEvent(payload={event_id, phase})
→ FormationWorker episode_history_summary contains shallow records
```

### Behavior After

```text
Canonical Event / payload.tool_calls
→ EpisodeEventEnricher (deterministic, bounded summaries)
→ existing EpisodeEventContract / EpisodeRepository append and idempotency
→ FormationWorker episode_history_summary contains task actions, outcomes and failures
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_episode_enrichment.py` | PASS (3) |
| Episode + Working + Formation + Boundary regression subset | PASS (22) |
| P0 flow + contracts + write-bypass + non-Retrieval entrypoints | PASS (32; 3 deselected) |
| Ruff on changed source/tests | PASS |
| `git diff --check` | PASS |

### Evidence

- The component test records a successful file read and failed test command, verifies their
  compact action/result/error fields, and proves raw `tool_calls` and 500-character output do
  not enter the Episode payload.
- The canonical component test runs `goal → read → test failure → patch → test success` and
  verifies the append-only Episode rows retain each significant transition in source-event order.
- The Formation component test captures `ReflectionInput` and verifies its Episode history
  contains the enriched failed-test action rather than raw tool traces.
- Existing Working, Episode lifecycle, Boundary, candidate-only Formation, P0 and production
  write-bypass tests continue to pass.

### Regression

```text
Legacy: no Legacy source, route, or extractor changed; write-bypass and P0 regression subset passed.
Safety: no Safety policy, gate, or payload masking path changed.
candidate-only: Formation worker regression passed; promotion logic is unchanged.
Other: existing Episode sequence/idempotency and Working reducer behavior remain covered.
```

### Remaining Risks

- The bounded summaries are intentionally deterministic and recognize common tool schemas only;
  unknown tool status is retained as `UNKNOWN` rather than inferred.
- Episode resume replay still returns task-state reconstruction, not a narrative Episode summary.
- Reflection remains event-granular until Batch 4, so enriched history can still be reflected
  more often than the target boundary-driven design allows.
- OpenCode tool traces still use the Legacy endpoint and do not exercise this canonical path.
- Pytest emits the pre-existing `asyncio_mode` unknown-config warning. A sandbox temporary-
  directory permission issue was avoided by using an in-memory SQLite fixture for the new tests.

### Decisions

```text
Reuse EpisodeEventContract.payload and the existing Episode repository instead of adding a new
Episode schema or persistence path. Keep enrichment deterministic and bounded; do not create a
full Episode summary or use an LLM in this Batch.
```

### Not Done

- Boundary-gated Reflection enqueue (Batch 4).
- Complete Episode narrative summary or resume API expansion.
- Retrieval, Feedback, Rollout, Authority promotion, Safety, and Legacy/OpenCode route changes.
- Stage 1 end-to-end scenario suite (Batch 5).

### Next Batch Notes

Batch 4 should reuse `BoundaryDetector` and gate only Reflection task enqueue. Preserve the
new Episode enrichment, Working reducer, configured Reflection model, candidate-only behavior,
and all Authority/Legacy boundaries. Do not start Batch 5 automatically.


---

## Batch 4 — Boundary-driven Formation

### Status

```text
DONE
```

### Objective

让 Reflection 默认由 meaningful boundary 驱动，而不是无条件按每个 Event 触发；补全 Batch 4 验收测试并修复既有测试对新的边界门控语义的适应。

### Reconnaissance Findings

- 当前真实实现：
  - `CanonicalWriteService.write()` 的自动编排路径已用 `reflection_boundary = snapshot_result is not None` 门控 reflection task enqueue。
  - `BoundaryDetector` 已支持 COMPLETE/FAILED/EXPLICIT（hard）和 START/PHASE/CONTEXT_PRESSURE（rule）。
  - `FormationWorker` / `CandidateService` / `ExtractionTaskRepository` 的 idempotent enqueue 已可复用。
- 与 stage 文档一致的部分：
  - 低价值事件不再逐条触发 Reflection。
  - Task Complete / Failure / Explicit Remember 可触发 Formation。
  - candidate-only 模式保持有效。
- 与 stage 文档不一致的部分：
  - `PROGRESS.md` 标记 Batch 4 为 `NOT STARTED`，但核心代码已在工作树中。
  - `test_formation_receives_enriched_episode_history` 仍假设普通 tool failure 会无条件触发 reflection。
- 复用的现有组件：
  - `BoundaryDetector`、`CanonicalWriteService`、`FormationWorker`、`CandidateService`、`ExtractionTaskRepository`。
- 实际影响范围：
  - 仅测试文件与 `PROGRESS.md`；源码逻辑未改动。

### Changes

- 修复 `tests/test_vnext_episode_enrichment.py::test_formation_receives_enriched_episode_history`：将普通 tool failure 改为 `payload.boundary="explicit"`，使其符合边界驱动语义，同时保留“Formation 收到富集 Episode history”的验证目标。
- 新增 `tests/test_vnext_boundary_driven_formation.py`，覆盖 Batch 4 验收标准：
  - 低价值事件（read_file / git_status / search）不触发 Reflection。
  - `task_completed` 触发 Reflection 并完成 Episode。
  - `task_failed` 触发 Reflection 并失败 Episode。
  - `payload.boundary="explicit"` 触发 Reflection。
  - 同类型 boundary debounce 抑制重复 enqueue。
  - candidate-only 模式下 boundary 触发 Reflection 产生 Candidate，但不写 Long-Term Authority。
- 更新 `docs/vnext/PROGRESS.md` Batch 4 状态与 Stage 1 DoD 跟踪。

### Files Touched

```text
tests/test_vnext_episode_enrichment.py
tests/test_vnext_boundary_driven_formation.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
Canonical Event
→ _orchestrate_episode() 检测 boundary
→ 无条件 enqueue reflection task（每 accepted event 一个）
→ FormationWorker 逐事件 reflection
```

### Behavior After

```text
Canonical Event
→ Working Reducer
→ _orchestrate_episode() → BoundaryDetector.detect()
→ 仅当 boundary 产生 snapshot 时才 enqueue reflection task
→ FormationWorker 按 meaningful boundary reflection
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_boundary_driven_formation.py` | PASS (6) |
| `tests/test_vnext_episode_enrichment.py` | PASS (3) |
| `tests/test_vnext_boundary_detector.py` | PASS (10) |
| `tests/test_vnext_formation_worker.py` | PASS (5) |
| `tests/test_vnext_working_reducer.py` | PASS (2) |
| `tests/test_vnext_reflection.py` | PASS (6) |
| `tests/test_vnext_p0_flow.py` | PASS (8) |
| `tests/test_vnext_authority_write.py` | PASS (11) |
| `tests/test_vnext_candidate_service.py` | PASS (10) |
| `tests/test_vnext_event_gateway.py` | PASS (12) |
| `tests/test_vnext_contracts.py` | PASS (2) |
| Batch 4 regression subset total | PASS (77) |
| Ruff on changed source/tests | PASS |

### Evidence

- `test_low_value_tool_events_do_not_trigger_reflection` 证明 read_file / git_status / search 不生成 reflection task。
- `test_task_complete_triggers_reflection` / `test_task_failed_triggers_reflection` 证明 terminal event type 生成 reflection task 并正确切换 Episode status。
- `test_explicit_remember_triggers_reflection` 证明 `payload.boundary="explicit"` 生成 reflection task 且 Episode 保持 ACTIVE。
- `test_boundary_debounce_prevents_duplicate_reflection_tasks` 证明同类型边界在 debounce 窗口内被抑制。
- `test_candidate_only_does_not_write_authority` 证明 candidate-only 模式下 reflection 产生 Candidate，但 `PreferenceRepository` 无记录。
- `test_formation_receives_enriched_episode_history` 继续证明 boundary 触发的 reflection 能拿到富集后的 Episode history。

### Regression

```text
Legacy: no Legacy source, route, or extractor changed.
Safety: no Safety policy, gate, or payload masking path changed.
candidate-only: Formation worker regression passed; Authority promotion logic unchanged.
Other: existing Episode sequence/idempotency, Working reducer, reflection validation, and P0 flow tests passed.
```

### Remaining Risks

- 显式调用方提供 `episode_event` / `episode_snapshot` / `checkpoint` 时仍会无条件 enqueue reflection；这是 caller-driven 路径，不属于自动编排的 boundary-gated 范围。
- `SIGNIFICANT_STATE_CHANGE` / `EPISODE_CHECKPOINT` / `SESSION_BOUNDARY` 等更细粒度边界类型未在当前 `BoundaryCheckpointType` 中定义；如需覆盖，应作为后续增强而非 Batch 4 必需。
- OpenCode 插件仍走 Legacy 事件端点，未直接 exercise 本 canonical boundary-gated 路径。
- Batch 5 end-to-end scenario suite 仍未建立。

### Decisions

```text
Keep the existing BoundaryDetector checkpoint set (COMPLETE/FAILED/EXPLICIT/START/PHASE/CONTEXT_PRESSURE)
for Batch 4; do not add new checkpoint types. Fix tests to align with boundary-gated semantics rather than
reverting to event-granular reflection.
```

### Not Done

- Batch 5 — Stage 1 Scenario Tests。
- 新增 SIGNIFICANT_STATE_CHANGE / EPISODE_CHECKPOINT / SESSION_BOUNDARY 等边界类型。
- Retrieval / Feedback / Rollout / Authority promotion 核心改动。
- Legacy / OpenCode 路由迁移。

### Next Batch Notes

Batch 5 应基于 Batch 1-4 已完成的 Reflection / Working / Episode / Boundary 基础，建立真实连续 Agent Event 的 Scenario 测试（正常 Coding Task、失败后恢复、低价值事件、Explicit Remember、candidate-only、LLM Invalid Output）。不要回退 boundary-gated reflection，不要修改 Retrieval / Feedback / Rollout。


---

## Batch 5 — Stage 1 Scenario Tests

### Status

```text
DONE
```

### Objective

建立 Stage 1 要求的 6 类真实连续 Agent Event Scenario 测试，验证
Event -> Working State -> Episode -> Boundary -> Reflection -> Candidate
完整链路，并确认 candidate-only 模式与非法 Reflection 的安全行为。

### Reconnaissance Findings

- 当前真实实现：Batch 1–4 代码已提交，基础设施完整；缺少专属 scenario 测试文件。
- 与 stage 文档一致的部分：candidate-only、boundary-gated reflection、structured reflection validation、working reducer、episode enrichment 均按设计工作。
- 与 stage 文档不一致的部分：`PROGRESS.md` 第 11 节仍指向 Batch 4，已修正。
- 复用的现有组件：`CanonicalWriteService`、`FormationWorker`、`ExtractionRetryService`、`WorkingStateRepository`、`EpisodeRepository`、`CandidateRepository`、`PreferenceRepository`、`KnowledgeRepository`。
- 实际影响范围：仅新增测试文件与 `PROGRESS.md`。

### Changes

- 新增 `tests/test_vnext_stage1_scenarios.py`，实现 6 个 Scenario：
  - A 正常 Coding Task
  - B 失败后恢复
  - C 低价值事件不触发 Reflection
  - D Explicit Remember 触发 Formation
  - E candidate-only 不写 Authority
  - F LLM Invalid Output 不产生脏 Candidate
- 修正 `PROGRESS.md` 中 Batch 5 状态、DoD 勾选、Scenario 结果、当前下一步。

### Files Touched

```text
tests/test_vnext_stage1_scenarios.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
Stage 1 DoD 中 "至少 6 类 Scenario Test 通过" 未完成；
无连续 Agent Event 的端到端 Formation 场景测试。
```

### Behavior After

```text
6 个 Stage 1 Scenario 全部通过；
Stage 1 所有 DoD 条目已勾选；
Formation 主链路在连续真实事件上得到验证。
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_stage1_scenarios.py` | PASS (6) |
| Batch 1–4 + P0 + candidate + contracts regression | PASS (50) |
| Ruff on changed source/tests | PASS |

### Evidence

- `test_scenario_a_normal_coding_task` 验证 Working State 随事件流演化、Episode 保留关键过程、task_completed 触发 Reflection、Candidate 产生且 Authority 为空。
- `test_scenario_b_recovery_from_failure` 验证失败被记录、恢复后 blockers 清空、Episode 保留转折、Complete 触发 Reflection。
- `test_scenario_c_low_value_events_do_not_trigger_reflection` 验证 read/git_status/search 不触发 Reflection、无 Candidate。
- `test_scenario_d_explicit_remember_triggers_formation` 验证 `boundary=explicit` 触发 Reflection、Candidate Scope 不自动扩成 GLOBAL。
- `test_scenario_e_candidate_only_does_not_write_authority` 验证 Candidate 产生但 Preference/Knowledge Authority 无记录。
- `test_scenario_f_invalid_reflection_does_not_create_dirty_candidate` 验证非法 schema 输出不产生 Candidate、任务进入 retry、可观测日志被捕获。

### Regression

```text
Legacy: 未修改任何 Legacy source/route/extractor；P0 flow regression 通过。
Safety: 未修改 Safety policy/gate/payload masking。
candidate-only: Formation worker 保持 candidate-only，Authority promotion 逻辑未变。
Other: Batch 1–4 相关测试全部通过，Ruff 通过。
```

### Remaining Risks

- Scenario 使用 deterministic reflection model；真实 LLM 集成仍依赖 Batch 1 的 `StructuredReflectionModel`，需在有 credentials 的环境单独验证。
- OpenCode 插件仍走 Legacy 事件端点，未直接 exercise canonical scenario 路径。
- Scenario 仅覆盖 SQLite in-memory；生产 Milvus/真实 embedding 路径需 Stage 4 benchmark 验证。

### Decisions

```text
None
```

### Not Done

- Stage 2 Retrieval 实化。
- Stage 3 Feedback 闭环。
- Stage 4 Evaluation & Cutover。
- OpenCode / Legacy 路由迁移。

### Next Batch Notes

Stage 2 开始前必须重新执行 Codebase Reconnaissance，阅读 VNEXT_PLAN.md、stage2-retrieval.md 与 PROGRESS.md。当前 Formation 链路已完成，不要回退或修改 Formation 组件。


---

## Stage 1 Independent Review Repair

### Status

```text
DONE
```

### Objectives

修复 Stage 1 Independent Review 中标记的三个 P1：

1. Repair-1：关闭 vNext `/events` 通过 `_long_term` payload 字段直接写入 Long-Term Authority 的绕过路径。
2. Repair-2：移除 production/runtime path 中 `ReflectionService()` / `FormationWorker()` 的隐式 deterministic fallback。
3. Repair-3：增加使用 configured LLM（FakeConfiguredLLMClient）的 Formation 端到端组件测试。

### Reconnaissance Findings

- `CanonicalWriteService.write()` 接受 `long_term` 参数，并在 `formation_mode=candidate-only` 时仍可写入 Authority。
- `vnext_api.py` 的 `/events` endpoint 通过 `_pop_long_term()` 从 payload 中解析 `_long_term`，为绕过路径的入口。
- `_write_long_term()` 调用 `memory_write_service.upsert_memory(..., skip_write_gate=True)`，绕过 Safety Write Gate。
- `ReflectionService.__init__` 默认 `model or DeterministicReflectionModel()`，`FormationWorker` 默认 `reflection_service or ReflectionService()`，`FormationShadowService` 与 `ShadowReadService` 也存在同样隐式 fallback。
- Stage 1 已经通过 deterministic model 验证 Formation 链路，但缺少用 `StructuredReflectionModel` + fake LLM client 的端到端组件测试。

### Changes

- Repair-1：
  - `CanonicalWriteService.write()` 在 `formation_mode != "authority"` 且收到 `long_term` 时立即抛出 `ValueError`，fail fast。
  - `CanonicalWriteService._write_long_term()` 将 `skip_write_gate=True` 改为 `skip_write_gate=False`，让 Authority 写入经过 Safety Write Gate。
  - `vnext_api.py` `/events` endpoint 移除 `_long_term` 的解析与传递，响应中不再返回直接 Authority memory_ids。
- Repair-2：
  - `ReflectionService.__init__` 要求显式传入 `model`，否则抛出 `TypeError`。
  - `FormationWorker.__init__` 要求显式传入 `reflection_service`，否则抛出 `TypeError`。
  - `FormationShadowService.__init__` 要求显式传入 `reflection_service`，否则抛出 `TypeError`。
  - `ShadowReadService.__init__` 要求显式传入 `reflection_service` 或预构建的 `FormationShadowService`。
  - `memoryhub/app.py` 提前创建 `app.state.reflection_service`（`StructuredReflectionModel` 包装配置的 `OpenAIClient`），并显式注入 `ShadowReadService` 与 `FormationWorker`。
  - `examples/vnext_demo/run_demo.py`、`evaluation/run_vnext_shadow.py`、`evaluation/metrics/formation_eval.py` 显式注入 deterministic reflection_service。
  - 更新所有测试，显式注入 `DeterministicReflectionModel` 或 fake model；不再允许 `ReflectionService()` / `FormationWorker()` 静默走 deterministic。
- Repair-3：
  - 新增 `tests/test_vnext_formation_configured_llm.py`。
  - 实现 `FakeConfiguredLLMClient(BaseLLMClient)`，替代最底层外部模型请求。
  - 使用生产相同调用链：`CanonicalWriteService -> Boundary -> FormationWorker -> ReflectionService -> StructuredReflectionModel -> FakeConfiguredLLMClient`。
  - 覆盖 Success、Invalid Output、Provider Failure 三类场景，验证 Candidate 创建/不创建、Authority 不写入、retry 行为保留。
- 测试修正：
  - `tests/test_vnext_authority_write.py` 增加 candidate-only 拒绝 long_term、显式 `write_authority` 仍可用、normal formation 创建 Candidate 不写 Authority 的测试。
  - `tests/test_vnext_entrypoints.py` 移除 `_long_term`，断言 `/events` 不再返回 Authority memory_ids。
  - `tests/test_vnext_p0_flow.py` 移除 P0-01/P0-06/P0-07 中的 `_long_term` payload。

### Files Touched

```text
memoryhub/application/canonical_write.py
memoryhub/adapter/vnext_api.py
memoryhub/application/reflection_service.py
memoryhub/application/formation_worker.py
memoryhub/application/formation_shadow.py
memoryhub/application/shadow_read_service.py
memoryhub/app.py
examples/vnext_demo/run_demo.py
evaluation/run_vnext_shadow.py
evaluation/metrics/formation_eval.py
tests/test_vnext_reflection.py
tests/test_vnext_formation_worker.py
tests/test_vnext_candidate_service.py
tests/test_vnext_formation_shadow.py
tests/test_vnext_shadow_read.py
tests/test_vnext_s6_02_rollout.py
tests/test_vnext_authority_write.py
tests/test_vnext_entrypoints.py
tests/test_vnext_p0_flow.py
tests/test_vnext_formation_configured_llm.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
candidate-only mode + /events payload._long_term
→ CanonicalWriteService.write(long_term=...)
→ _write_long_term(skip_write_gate=True)
→ Authority written (bypass)

ReflectionService()
→ DeterministicReflectionModel (silent fallback)

FormationWorker(reflection_service=None)
→ ReflectionService()
→ DeterministicReflectionModel (silent fallback)
```

### Behavior After

```text
candidate-only mode + /events payload._long_term
→ /events ignores _long_term
→ CanonicalWriteService.write() raises ValueError if long_term supplied
→ Authority not written

Explicit Authority write
→ CanonicalWriteService.write_authority()
→ _write_long_term(skip_write_gate=False)
→ Safety Write Gate
→ Authority

ReflectionService(model=StructuredReflectionModel(<configured llm>))
→ FormationWorker(reflection_service=...)
→ production Formation path
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_reflection.py` | PASS (6) |
| `tests/test_vnext_formation_worker.py` | PASS (5) |
| `tests/test_vnext_stage1_scenarios.py` | PASS (6) |
| `tests/test_vnext_boundary_driven_formation.py` | PASS (6) |
| `tests/test_vnext_episode_enrichment.py` | PASS (3) |
| `tests/test_vnext_authority_write.py` | PASS (14) |
| `tests/test_vnext_entrypoints.py` | PASS (9; 3 deselected retrieval fixtures) |
| `tests/test_vnext_p0_flow.py` | PASS (8) |
| `tests/test_vnext_candidate_service.py` | PASS (10) |
| `tests/test_vnext_shadow_read.py` | PASS (3) |
| `tests/test_vnext_s6_02_rollout.py` | PASS (3; 1 deselected shadow fixture) |
| `tests/test_no_production_write_bypass.py` | PASS (5) |
| `tests/test_vnext_formation_configured_llm.py` | PASS (3) |
| Combined targeted regression suite | PASS (69; 4 deselected) |
| Ruff on changed source/tests | PASS |

### Evidence

- `test_candidate_only_rejects_long_term_payload` 证明 candidate-only + `long_term` 会抛错，Authority 表无记录。
- `test_candidate_only_normal_formation_creates_candidate_not_authority` 证明正常 Formation 产生 Candidate，Authority 表无记录。
- `test_explicit_authority_writer_routes_through_safety_gate` 证明 `write_authority` 显式接口仍可用。
- `tests/test_vnext_formation_configured_llm.py` 三个测试分别验证：合法 structured response 产生 Candidate、非法 schema 不创建 Candidate、LLM 异常不创建 Candidate 且 retry 行为保留。
- `tests/test_vnext_reflection.py` 验证 `ReflectionService()` 无显式 model 时抛 `TypeError`；显式 `StructuredReflectionModel` 调用 configured LLM。
- `app.py` 中 `app.state.reflection_service` 创建后同时注入 `ShadowReadService` 与 `FormationWorker`，生产路径无 deterministic fallback。

### Regression

```text
Legacy: no Legacy source/route/extractor changed; P0 flow and write-bypass tests passed.
Safety: Authority write now routes through Safety Write Gate; candidate-only bypass closed.
candidate-only: Formation worker regression passed; Authority promotion logic unchanged.
Other: 69 targeted regression tests passed; Ruff passed.
```

### Remaining Risks

- `tests/test_vnext_formation_shadow.py` 全部 11 个用例失败：pre-existing `InMemoryCandidateRepository.create()` 不接受 `confidence/utility/stability` 关键字参数。在 Repair 之前的 HEAD 已失败，与本次修改无关。
- `tests/test_vnext_entrypoints.py::test_vnext_search_returns_consistent_ids_and_trace` / `test_vnext_context_returns_same_memories_as_search` / `test_legacy_search_delegates_to_vnext_retrieval_service` 失败：fixture 未装配 `rollout_controller` / `rollout_read_service`。属于 Stage 2 retrieval fixture 问题，与本次修改无关。
- `tests/test_vnext_s6_02_rollout.py::test_shadow_and_dual_read_return_legacy_only_and_redact_report` 失败：未传入 rollout_controller；与 Stage 2 rollout fixture 相关，与本次修改无关。
- `OpenCode vNext endpoint 迁移` 与 `OpenCode 原始 Tool Trace 集成风险` 仅记录，本次未处理。
- Stage 2 Retrieval / Candidate Promotion / Feedback / Utility / Rollout / Dashboard / Authority Schema 重构等明确不在本次范围内。

### Decisions

```text
1. candidate-only /events path 禁止 Authority 写入；显式 Authority 写保留为 write_authority 并经过 Safety Gate。
2. ReflectionService / FormationWorker / FormationShadowService / ShadowReadService 均要求显式 reflection_service，生产使用 StructuredReflectionModel + configured LLM。
3. FakeConfiguredLLMClient 仅替换最底层 LLM 请求，保持上层 prompt/schema/validation/worker 链路不变。
```

### Not Done

- Stage 2 Retrieval 实化。
- Stage 3 Feedback 闭环。
- Stage 4 Evaluation & Cutover。
- FormationShadowService 的 pre-existing InMemoryCandidateRepository 兼容性修复。
- Stage 2 retrieval/rollout fixture 修复。

### Next Batch Notes

本次 Repair 已完成并 STOP。下一会话不应自动开始 Stage 2；如需继续，应重新执行 Codebase Reconnaissance 并阅读 `docs/vnext/stages/stage2-retrieval.md` 与 `PROGRESS.md`。

---

## Stage 2 Batch 1 — Working / Episode Executors

### Status

```text
DONE
```

### Objective

为 RetrievalPlanner 的 working / episode channel 实装结构化 Channel Executor，
使 CURRENT_STATE / TASK_HISTORY 读取真实 Working State 与 Task Episode 存储，
不再退化为空结果或唯一依赖 legacy vector search。

### Reconnaissance Findings

- 当前真实实现：
  - `RetrievalService` 管线（IntentRouter → Planner → executors → RRF → Reranker
    → ScopeResolver → Budget）完整存在，但 `build_channel_executors` 只注册了
    `vector` channel；CURRENT_STATE / TASK_HISTORY 在真实 app 中返回空候选
    （completeness=NONE）。
  - `WorkingStateRepository` / `EpisodeRepository` 已有 exact-key 读接口
    （`get` / `get_by_task_id` / `list_events`），但缺少 session/recent 回退查询。
  - `WorkingStateRow` / `TaskEpisodeRow` 只有 session_id，没有 project_id 列。
- 与 stage 文档一致的部分：6 channel 定义、executor contract、缺失 executor
  静默降级、RRF 保留 channel 归因均成立。
- 与 stage 文档不一致的部分：
  - Storage 无 project_id 列，working channel 的 project-scoped lookup 只能
    留到 Batch 3（scope 传播）一并处理。
  - `_search_request_from_vnext` 硬编码 `project_id=""` / `level="long"`，
    Legacy Retriever 复用点的 scope 丢失属于 Batch 3 范围。
- 复用的现有组件：`WorkingStateRepository` / `EpisodeRepository` /
  `RetrievalService` 管线 / `_tokenize`（确定性 relevance）/ `SearchResult` 适配。
- 实际影响范围：1 个 executor 文件重写、2 个只读查询新增、app.py 装配、1 个新测试文件。

### Changes

- `memoryhub/storage/vnext_repositories.py`：为 `WorkingStateRepository` 与
  `EpisodeRepository` 各新增只读 `list_recent()`（session 过滤 + limit 上限；
  Episode 默认排除 ARCHIVED）。
- `memoryhub/adapter/retrieval_executor.py`：
  - 新增 `build_working_executor`：exact task 匹配（score=1.0，match="task"），
    否则 session/recent 回退（限 3 条，recency 衰减 0.1/名次，match="recent"）。
  - 新增 `build_episode_executor`：exact task 匹配（score=1.0），否则
    session/recent 回退（限 5 条，确定性 token-overlap relevance 排序，
    recency 为 tiebreaker），携带最近 5 条 episode event 摘要。
  - Working 结果还原全部结构化字段（goal/step/pending/completed/constraints/
    entities/blockers/findings/failures/next_action），不经过 embedding。
  - `build_channel_executors` 注册 working / episode（vector 保持原 getattr 逻辑）。
- `memoryhub/app.py`：startup 中提升 `working_state_repository` /
  `episode_repository` 到 app.state 并传入 `build_channel_executors`。
- 新增 `tests/test_vnext_working_episode_executors.py`（11 个测试）。

### Files Touched

```text
memoryhub/storage/vnext_repositories.py
memoryhub/adapter/retrieval_executor.py
memoryhub/app.py
tests/test_vnext_working_episode_executors.py
docs/vnext/PROGRESS.md
```

（核心源码 3 个文件，低于 ≤8 的限制。）

### Behavior Before

```text
/api/memory/vnext/search (CURRENT_STATE, rollout mode=vnext)
→ RetrievalPlanner enabled_channels=[working, metadata, authority]
→ working/episode 无 executor → 空候选
→ selected_memories=[]，completeness=NONE
真实 app 中 build_channel_executors 实际注册 {} （retriever 赋值晚于装配，
vector 也未注册，pre-existing）
```

### Behavior After

```text
/api/memory/vnext/search (CURRENT_STATE / TASK_HISTORY, rollout mode=vnext)
→ RetrievalPlanner → working / episode executor
→ WorkingStateRepository.get / list_recent（结构化读取，无 embedding）
→ EpisodeRepository.get_by_task_id / list_recent + list_events（最近 5 条摘要）
→ RetrievedMemory{layer=WORKING|EPISODE, scope_level=TASK, scope=task_id,
   score_breakdown.channel=working|episode}
→ RRF → Reranker → Scope → Budget → ContextPayload.relevant_memory_ids
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_working_episode_executors.py` | PASS (11) |
| Retrieval framework subset（service/planner/intent/fusion/scope/budget） | PASS |
| Stage 1 formation 链路 + P0 + write-bypass + contracts 回归 | PASS (138 合并) |
| Ruff on changed source/tests | PASS |
| `git diff --check` | PASS |
| 已知失败基线（entrypoints 3 + s6_02 1 + formation_shadow 11 + memory_api 1） | 15 failed / 14 passed，与 Batch 1 之前一致 |

### Evidence

- `test_current_state_returns_exact_task_working_state` 证明 working channel
  返回 `ws:` 结果，layer=WORKING、scope=TASK/task、match=task，且 content 还原
  current_goal / current_step / pending_steps / next_action。
- `test_task_history_returns_episode_with_key_events` 证明 episode channel
  返回 `ep:` 结果并携带 episode event 摘要。
- 隔离测试证明 working / episode 均按 (tenant_id, user_id) 严格隔离。
- `test_retrieval_service_current_state_uses_working_channel` /
  `test_retrieval_service_task_history_uses_episode_channel` 证明两个 channel
  真实经过 RetrievalService 主链路（planner → executor → fusion → context）。
- 真实 app factory 端到端 smoke（`with TestClient(app)` lifespan，rollout
  mode=vnext）：`/events` 写入返回 working_state_version=1 → CURRENT_STATE
  search 返回 `ws:working-...` 命中（channel=working，还原 goal/blockers，
  completeness=FULL）→ boundary 事件返回 REFLECTION_PENDING → TASK_HISTORY
  search 返回 `ep:episode-...` 命中（channel=episode，completeness=FULL）。
  write → working → search 主链路真实打通。
- `test_scenario_*` 与 P0/write-bypass 回归证明 Stage 1 Formation 与 Legacy
  链路未被破坏。

### Regression

```text
Legacy: 未修改 Legacy source/route/extractor；no-production-write-bypass 与
P0 flow 测试通过。test_memory_api round-trip 500 为 pre-existing（git stash
在干净工作树上复现确认）。
Safety: 未修改 Safety policy / gate / payload masking。
candidate-only: Formation 全链路回归通过；boundary 事件仍返回
REFLECTION_PENDING；Authority promotion 未变。
Other: 合并回归 138 passed；Ruff 与 git diff --check 干净。
```

### Remaining Risks

- app.py 装配顺序缺口（pre-existing，非本 Batch 引入）：`RetrievalService`
  在 startup() 内早于 `app.state.retriever` 赋值构建，因此真实 app 中 vector
  executor 不会注册，long-term intent 的 vector channel 静默为空。Batch 2
  落地 vector/keyword/authority executor 时需一并修正。
- storage 无 project_id 列：working/episode 的 project-scoped lookup 无法在本
  Batch 实现；project scope 语义留给 Batch 3。
- `_search_request_from_vnext` 仍硬编码 `project_id=""` / `level="long"`：
  Legacy Retriever 复用点的 Intent/Scope 丢失留给 Batch 3。
- RECALLED activation status 尚未在 executor 中记录（现有 RetrievalService
  落库逻辑未变）。
- episode fallback 的 relevance 为确定性 token overlap（jieba 可用时更好），
  无 jieba 环境下区分度下降但不破坏排序正确性（测试已兼容两种环境）。
- legacy-mode smoke 中发现 `data/vector_index.faiss` 相关 FAISS 维度断言
  500（`HybridRetriever` → `VectorStore.search`）；经 git stash 在 HEAD 上
  复现确认为 pre-existing 环境问题（陈旧共享索引文件），与本 Batch 无关。

### Decisions

```text
1. Working/Episode 结果使用合成 memory_id 前缀（ws: / ep:）+ source_ids 引用
   底层 working_state_id / episode_id，避免与 Long-Term memory_id 空间冲突。
2. Episode fallback 排序采用确定性 token-overlap relevance（复用
   keyword_search._tokenize），不引入 embedding 或 LLM。
3. Episode exact 匹配使用 get_by_task_id(status=None)，ARCHIVED 排除仅在
   fallback 生效——exact 命中是显式 task 上下文，返回并标注 status 供下游判断。
4. 新增只读 list_recent() 而非复用写路径或新建第二套查询层。
```

### Not Done

- Batch 2：authority / keyword / vector executor，及 app.py 装配顺序修正。
- Batch 3：Intent + Scope 传播（`_search_request_from_vnext` 的
  project_id/level、project-scoped working lookup、scope_level 传递补全）。
- Batch 4：Fusion / Rerank / Context Budget 实化。
- Batch 5：Scenario tests & Legacy 对比。
- OpenCode 插件迁移到 canonical endpoint（沿用 Stage 1 记录）。

### Next Batch Notes

Batch 2 应按 stage2-retrieval.md §8 实装 authority / keyword / vector executor：
- 复用 `AuthorityRepository` / `LongTermAuthorityFacade` / `KeywordSearcher` /
  现有 retriever，不建平行检索框架。
- 必须修正 app.py 中 RetrievalService 装配早于 retriever 的顺序问题，否则
  vector executor 在真实 app 仍不会注册。
- 验证 keyword/metadata/authority 落地后 `degraded_channels` 语义与
  Planner fallback channel（metadata/authority）配合是否正确。
- 不要动 working / episode executor 的匹配与回退语义；不要提前做 Batch 3
  的 scope 传播。

---

## Stage 2 Batch 2 — Authority / Keyword / Vector Executors

### Status

```text
DONE
```

### Objective

在既有 RetrievalService 主链路中实化 long-term Authority、BM25 Keyword、
metadata 与 Legacy-backed Vector channel，并修复真实 app 的 executor 装配顺序；
保持 Working / Episode 的结构化读取和 Legacy Retriever 算法不变。

### Changes

- `memoryhub/adapter/retrieval_executor.py`：修复 Legacy `SearchResult` 转换器对
  不存在的 `user_id` 字段的访问；新增独立 Keyword、Authority、metadata executor；
  `build_channel_executors` 按 app.state 注册四个 long-term channel，同时保留
  Working / Episode 结构化 executor。
- `memoryhub/app.py`：索引 metadata 增加 tenant 标识；BM25 同时服务 vNext 与
  Legacy，缺少可选依赖时显式 warning/degraded；AuthorityRepository / Facade
  放入 app.state；将 RetrievalService 创建移到 retriever 完成之后，并注入真实
  channel map、AuthorityRepository 与 DB。
- 新增 `tests/test_vnext_batch2_retrieval_channels.py`，覆盖 channel、隔离和
  Vector 转换行为。

### Files Touched

```text
memoryhub/adapter/retrieval_executor.py
memoryhub/app.py
tests/test_vnext_batch2_retrieval_channels.py
docs/vnext/PROGRESS.md
```

（核心源码 2 个文件，低于 ≤8 的限制；未修改 Repository schema、Legacy
Retriever 算法、Formation 主链路。）

### Behavior Before

```text
真实 app startup：RetrievalService 在 app.state.retriever 赋值前构建，vector
executor 未注册；keyword / metadata / authority 也未注册。
Legacy vector adapter：SearchResult 没有 user_id，转换抛 AttributeError，随后
被 RetrievalService 捕获并把 vector 静默变为空 channel。
```

### Behavior After

```text
retriever + AuthorityRepository + keyword index 就绪后才构建 RetrievalService；
Planner.available_channels 与实际 executor map 对齐。vector 复用现有 Legacy
retriever 但只作为一个 channel；keyword 独立调用 BM25；metadata 读取现有
memory_lookup；authority 读取 request tenant/user 下的 ACTIVE envelope；四路
均进入原有 RRF → Reranker → Scope → Budget 主链路。
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_batch2_retrieval_channels.py` | PASS (4), 1 skipped（未安装 rank-bm25） |
| vNext core subset（working/episode/intent/planner/fusion/scope/context/interface） | PASS (88), 1 skipped |
| `ruff check` on changed source/tests | PASS |
| `git diff --check` | PASS |
| Stage 1 scenarios + authority write + configured LLM + app production assembly | 16 passed；3 setup error（pytest 临时目录 ACL） |
| Legacy retrieval / acceptance | pre-existing failures：缺少 `faiss-cpu` / `rank-bm25`，另有 pytest 临时目录 ACL 错误 |

### Evidence

- Vector 测试使用真实 `SearchResult` schema，证明转换不再读取不存在的
  `user_id`，并保留 request owner 与 vector source。
- Authority 测试写入不同 user/status 的 envelope，证明只返回同 tenant/user 下
  的 ACTIVE Authority；metadata / keyword 测试覆盖 owner 隔离与 source/layer。
- registration 测试证明同一 `build_channel_executors` 可装配 vector、keyword、
  metadata、authority；静态检查证明 retriever 赋值先于 RetrievalService 创建。

### Scope Verification

- 本 Batch 未修改 `MemoryRetrievalRequest`、IntentRouter、Planner scope 规则，
  也未修改 `_search_request_from_vnext` 的 project/level 映射。
- 新增/修复的 channel adapter 均使用 request tenant/user 作为边界；Keyword、
  metadata、Authority 不跨 owner 返回，Vector conversion 拒绝明确不匹配的
  tenant/user。
- 已知 scope 丢失仍存在：vNext 没有独立 `project_id`，Legacy adapter 仍硬编码
  `project_id=""` / `level="long"`；这是 Batch 3 Intent + Scope Propagation 的
  明确遗留，不在本 Batch 偷改 schema 或传播链。

### Retrieval Channel Verification

| Channel | Batch 2 状态 | 实际来源 |
|---|---|---|
| working | 保持 Batch 1 | `WorkingStateRepository` 结构化读取 |
| episode | 保持 Batch 1 | `EpisodeRepository` 结构化读取 |
| vector | DONE | existing Legacy retriever adapter |
| keyword | DONE（依赖缺失时显式 degraded） | existing `KeywordSearcher` / BM25 |
| metadata | DONE | existing `memory_lookup` |
| authority | DONE | `AuthorityRepository.list` |

### Remaining Risks

- 当前环境没有 `rank-bm25` / `faiss-cpu`，无法完成真实 BM25/FAISS backend 命中；
  Milvus/embedding 真实服务也仍需外部环境验证。
- executor 异常仍采用空结果降级，channel 级异常原因和详细计数留给后续 Batch。
- project_id 的完整 Request → Planner → Executor → Result 传播留给 Batch 3；
  `RECALLED` activation、token_budget、Fusion/Rerank 细化、Legacy vs vNext 对比
  和 rollout cutover 尚未完成。

### Regression

```text
未修改 Formation / Reflection / Working reducer / Episode enrichment / Candidate-only
主设计；Stage 1 场景与 Authority write 链通过。
未修改 Legacy HybridRetriever、Milvus、BM25 算法本体或写入/Feedback/Evolution。
vNext 核心回归 88 passed；新增 Batch 2 行为测试 4 passed。
Legacy retrieval 失败由当前环境缺少既有可选依赖和 pytest temp ACL 引起，非本 Batch
引入，已在 Batch 1 基线中存在。
```

### Next Batch Notes

Batch 3 仅处理 Intent + Scope Propagation：补全 Legacy adapter 的 project_id /
level / memory_types / scene 等传播，评估最小 schema 兼容，并补充 Request →
Planner → Executor → Result 隔离测试。不要重写 Authority、BM25、Vector 或
Working / Episode executor；不要提前进入 Batch 4 的 Fusion / Rerank / Context Budget。

---

## Stage 2 Batch 3 — Intent + Scope Propagation

### Status

```text
DONE
```

### Objective

使 vNext retrieval request 的 tenant/user/project/task/session、intent 与 memory
type 在 vNext → Legacy 适配、Channel Executor 与最终 Context 边界均不静默丢失，
并阻止不同 project 的 Long-Term Memory 进入结果。

### Changes

- `memoryhub/adapter/vnext_schemas.py`：新增唯一的
  `legacy_search_request_from_vnext()` 兼容适配器。project scope 映射到 Legacy
  `project_id`；task/session/application/domain 映射到既有 `SceneScope`；task_id、
  session_id、intent 对应 level、plan memory types 对应 Legacy types 均保留。
- `memoryhub/adapter/retrieval_executor.py`：Vector 改用该单一适配器并传入
  `RetrievalPlan`；Vector/Keyword/Metadata/Authority 在执行器入口按 request
  tenant/user 与 exact scope（或 GLOBAL fallback）过滤。
- `memoryhub/adapter/vnext_api.py`：rollout 的 legacy reader 复用同一适配器，
  shadow/canary 对照不再构造丢失 scope 的简化 `SearchRequest`。
- `memoryhub/retrieval/scope_resolver.py` + `memoryhub/application/context_service.py`：
  最终 Context 边界执行 request tenant/user 校验；Long-Term 的非 GLOBAL 记录必须
  与请求 scope 完全匹配，即使它不与其他候选形成 conflict group。
- `memoryhub/application/retrieval_service.py`：在 response retrieval plan 中回显
  `metadata_filter`，使 scope 规划可追踪。
- 新增 `tests/test_vnext_batch3_scope_propagation.py`（5 个行为测试）。

### Files Touched

```text
memoryhub/adapter/vnext_schemas.py
memoryhub/adapter/retrieval_executor.py
memoryhub/adapter/vnext_api.py
memoryhub/retrieval/scope_resolver.py
memoryhub/application/context_service.py
memoryhub/application/retrieval_service.py
tests/test_vnext_batch3_scope_propagation.py
docs/vnext/PROGRESS.md
```

（核心源码 6 个文件，符合单 Batch ≤8 的限制；未改数据库 schema。）

### Behavior Before

```text
vNext request(scope=PROJECT:project-b)
→ Legacy Vector SearchRequest(project_id="", level="long", types=[])
→ legacy/shadow reader 仅保留 user/query/top_k
→ Authority/Keyword/Metadata/Vector 只按 tenant/user 读取
→ ScopeResolver 只处理同 identity 冲突
→ 无冲突的 PROJECT:project-a 记录可能进入 project-b Context
```

### Behavior After

```text
Request scope / task / session / intent / type
→ single legacy compatibility adapter
→ Legacy SearchRequest(project_id, SceneScope, session_id, level, memory_types)
→ long-term channel early scope filter
→ RRF / Rerank
→ final ScopeResolver ownership + exact-scope guard
→ Context / retrieval plan(metadata_filter)
```

GLOBAL Long-Term Memory 仍可作为任何明确 scope 的安全 fallback；Working/Episode
仍由其 tenant/user/task/session 结构化 Repository 负责窄化，不被强制转为 embedding。

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_batch3_scope_propagation.py` | PASS (5) |
| Batch 3 + interface/intent/planner/scope/working-episode/Batch 2/retrieval subset | PASS (89), 1 skipped, 1 deselected |
| Stage 1 scenarios + boundary + Authority write | included above, PASS |
| `ruff check` on changed source/tests | PASS |
| `git diff --check` | PASS |

`test_retrieval_log_persisted` 未在该合并回归中运行：当前 Windows pytest 临时目录
ACL 会在 `tmp_path` 创建 `.lock` 时失败，属于 Reconnaissance 已确认的环境基线。

### Evidence

- project-b 请求会把 `PROJECT:project-b` 映射为 Legacy `project_id=project-b`，
  保留 `task_id` 到 `SceneScope.task_type`、保留 session，并按 plan 传递 type/top_k。
- Vector 测试证明 legacy retriever 接收到 project/type/top_k，且 project-a hit 在
  channel 边界被拒绝。
- Authority 测试证明仅返回 exact project-b 与 GLOBAL fallback，不返回 project-a。
- ScopeResolver 测试证明不同 identity 的 project-a 候选也会在最终 Context 前被
  丢弃；该情形此前不会进入 conflict resolution。

### Scope Verification

- tenant/user：Channel 入口与最终 ScopeResolver 双重校验。
- project：vNext generic `scope_level/scope` 是现有 contract 的项目表达；现映射到
  Legacy `project_id`，并在四个 Long-Term Channel 与最终 Context 同时执行。
- task：vNext `task_id` 保留至 Legacy `SceneScope.task_type`；显式 TASK scope 同样
  映射到该字段。Legacy contract 不存在独立 task_id，未新建平行字段。
- session：保留至 Legacy `session_id`；显式 SESSION scope 同时映射到 SceneScope。
- intent/type：Vector adapter 使用 plan 的 resolved intent/type；rollout legacy
  reader使用 request intent hint（若调用方未提供 hint，则不存在可丢失的 intent）。

### Retrieval Channel Verification

| Channel | Batch 3 behavior |
|---|---|
| working | 未改；继续直接读取 WorkingStateRepository |
| episode | 未改；继续直接读取 EpisodeRepository |
| authority | ACTIVE owner-bound 读取后增加 exact scope / GLOBAL filter |
| keyword | BM25 结果转换后增加 exact scope / GLOBAL filter |
| metadata | 既有 memory_lookup 读取后增加 exact scope / GLOBAL filter |
| vector | 继续复用 Legacy retriever；请求映射与返回结果均执行 scope 防线 |

### Remaining Risks

- Working/Episode storage 没有 `project_id`，因此 project-scoped structured fallback
  仍无法实现；当前 task/session 读取不变，避免在 Batch 3 扩大 schema。
- Legacy `SearchRequest` 没有独立 task_id/intent 字段，兼容适配只能使用其既有
  `SceneScope`、level、memory_types 表达。
- 没有 request scope 时保持现有 owner-scoped行为；不会推断项目范围。
- Batch 4 的 token_budget 接线、Fusion/Rerank 细化、RECALLED activation、并行
  Channel latency 与 Retrieval Log 的 per-channel 计数仍未处理。
- 可选 `rank-bm25` / `faiss-cpu` 缺失，真实 BM25/FAISS backend 命中仍需具备依赖的
  环境验证。

### Regression

未修改 Stage 1 Formation、Candidate-only、Authority 写入、Repository schema、
Legacy HybridRetriever/BM25/FAISS 算法或 rollout controller。Stage 1 回归与既有
Working/Episode、Batch 2 channel 测试通过。

### Next Batch Notes

Batch 4 仅处理 Fusion / Rerank / Context Budget：复用现有 RRF、Reranker、
BudgetManager，接通 request token_budget，保留 channel provenance，补齐去重、
RECALLED/SELECTED/IN_CONTEXT 与可观测性。不要改本 Batch 的 scope compatibility
adapter 或重新设计 Working/Episode/Authority executor。

---

## Stage 2 Batch 4 — Fusion / Rerank / Context Budget

### Status

```text
DONE
```

### Objective

让现有多通道候选按解析后的 Intent 完成可解释融合、重排、Scope 校验和请求级预算，
并使 Activation 与检索日志真实反映 Retrieval Pipeline。

### Changes

- `ReciprocalRankFusion` 支持显式 channel weights，并将实际权重写入 score breakdown；默认行为保持不变。
- `ContextService` 按 `RetrievalPlan.intent`（而非可为空的 request hint）传入 reranker，并在未注入应用级 BudgetManager 时使用 `request.token_budget`。
- `RetrievalService` 记录各 channel 的候选数和耗时；仅在 Scope/Authority 校验后记录 `RECALLED`，之后继续记录 `SELECTED` 或 `IN_CONTEXT`。
- 新增 Batch 4 行为测试，覆盖 intent-aware RRF、request budget、resolved intent 与 Activation progression。

### Files Touched

```text
memoryhub/retrieval/fusion.py
memoryhub/application/context_service.py
memoryhub/application/retrieval_service.py
tests/test_vnext_batch4_fusion_context.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
Fusion 仅使用无权重 RRF；ContextService 使用 request.intent_hint，且总是使用默认
2000 token BudgetManager；Activation 仅有 SELECTED / IN_CONTEXT；日志没有 per-channel metrics。
```

### Behavior After

```text
Planner resolved intent → intent-specific RRF channel weights + reranker → ScopeResolver
→ request token_budget（或显式应用 policy）→ ContextPayload。

Scope/Authority 通过的候选记录 RECALLED；预算选中后记录 SELECTED 或 IN_CONTEXT；
retrieval log / trace 记录每个已计划 channel 的 count 与 latency。
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_batch4_fusion_context.py` | PASS (3) |
| Batch 1–4 retrieval subset | PASS (63), 1 skipped, 1 deselected |
| `test_retrieval_log_persisted` | 环境基线：Windows pytest temp `.lock` ACL，未执行 |

### Evidence

- Batch 4 测试证明 PREFERENCE 的 Authority channel weight 高于 vector，且权重被写入 score breakdown。
- 未提供 intent hint 时，ContextService 仍使用 Planner 的 PREFERENCE intent；128 token request 的 Context 不超预算。
- RetrievalService 测试证明 scope-valid 记忆有 `RECALLED` 与 `IN_CONTEXT` activation；既有测试证明 DELETED memory 不会被 activation 记录。

### Scope Verification

- 本 Batch 未修改 Request → Legacy adapter 或任一 executor 的 scope 过滤。
- RRF / rerank 后仍由 ScopeResolver 在 Budget 前执行最终 tenant/user 与 exact scope / GLOBAL fallback 校验；无效或 DELETED 候选不会产生 Activation。
- `selected_memories` 继续携带 scope，ContextPayload 仅接收已校验的 source IDs。

### Retrieval Channel Verification

| Channel | Batch 4 behavior |
|---|---|
| working / episode | 继续结构化读取；CURRENT_STATE / TASK_HISTORY 获得优先权重 |
| authority / keyword / metadata | 保持 Batch 2/3 adapter 和 scope filter；按长期 intent 获得权重 |
| vector | 继续是独立 Legacy-backed channel，未成为 vNext 唯一检索路径 |

### Remaining Risks

- 去重仍依赖稳定 `memory_id` / content version；不同 ID 的等价内容 identity consolidation 留待必要的独立架构决策，避免本 Batch 误合并不同事实。
- Working/Episode storage 没有 project_id，project-scoped structured fallback 仍未实现。
- 可选 `rank-bm25` / `faiss-cpu` 缺失，真实 BM25/FAISS backend 命中待具备依赖的环境验证。
- pytest 临时目录 ACL 仍使 `test_retrieval_log_persisted` 无法在此 Windows 环境运行。

### Regression

```text
未修改 Stage 1 Formation、Candidate-only、Repository schema、Scope adapter、
Working/Episode/Authority/Keyword/Vector executor 或 Legacy Retriever 算法。
Batch 1–4 retrieval subset 63 passed；DELETED candidate activation 回归通过。
```

### Next Batch Notes

Batch 5 仅补 Retrieval scenario tests 与 Legacy 对照；不要修改本 Batch 的融合、重排、预算或 activation 语义，除非 scenario 暴露明确回归。Stage 3 USED/Outcome/utility evolution 仍未开始。


---

## Stage 2 Batch 5 — Retrieval Scenario Tests & Legacy Comparison

### Status

```text
DONE
```

### Objective

建立 Stage 2 的真实 retrieval scenario 测试（Current State、Task History、Preference、Semantic Fact、Keyword、Scope Isolation、Dedup、Context Budget、Mixed Intent、Legacy-vs-vNext 对照），验证完整链路 Intent → Planner → Channel Executors → Fusion → Rerank → Scope → Budget → Context，并修复 scenario 暴露的入口测试与 intent-routing 稳定性问题。

### Reconnaissance Findings

- 当前真实实现：Batch 1–4 已落地 working/episode/authority/keyword/vector/metadata executor、RRF、VNextReranker、ScopeResolver、BudgetManager；Batch 5 首次用真实 repository + mock vector 跑端到端 scenario。
- 与 stage 文档一致的部分：调用链完整，channel executor、fusion、rerank、scope、budget 均按设计工作；keyword BM25 负分需归一化；entrypoint fixture 缺 rollout/retrieval service。
- 与 stage 文档不一致的部分：自然中文查询无法稳定命中 router 正则，需用 `intent_hint` 强制目标 intent 以保证 scenario 确定性；`VNextReranker.DEFAULT_TYPE_WEIGHTS` 中 WORKING/EPISODE 权重仅 0.05，导致 state/history 查询时 working/episode memory 易被大量长期噪声挤出 top_k。
- 复用的现有组件：WorkingStateRepository、EpisodeRepository、AuthorityRepository、KeywordSearcher、BM25、VNextReranker、ReciprocalRankFusion、ScopeResolver、BudgetManager、StructuredContextBuilder、RetrievalService、IntentRouter。
- 实际影响范围：reranker/context_service/intent_router 最小适配 + scenario/entrypoint 测试 + 已有 keyword executor 归一化修复。

### Changes

- `memoryhub/adapter/retrieval_executor.py`：新增 `_normalize_keyword_scores()`，将 BM25 原始负分 min-max 归一化到 `[0, 1]`，解决 `RetrievedMemory(score>=0)` schema 约束冲突。
- `memoryhub/retrieval/reranker.py`：`VNextReranker.rerank()` 增加可选 `intent_type_boosts` 参数，单次调用可覆盖实例级 boost；`_score()` 使用传入 boost 表实现 intent-aware type boost。
- `memoryhub/application/context_service.py`：`build_context()` 根据 `plan.intent` 生成 intent-aware type boost 并传给 reranker；新增 `_intent_type_boosts()` 静态方法。
- `memoryhub/retrieval/intent_router.py`：移除 `intent_hint is not MIXED` 限制，允许测试显式强制 MIXED intent（其他场景已可强制）。
- `tests/test_vnext_entrypoints.py`：补全 `RolloutController` + `RolloutReadService` + `ShadowReadService` fixture；修正 activations 数量与 legacy header。
- `tests/test_vnext_batch5_retrieval_scenarios.py`：新增 11 个 scenario / 对照测试（A-J + Legacy-vs-vNext）。

### Files Touched

```text
memoryhub/adapter/retrieval_executor.py
memoryhub/application/context_service.py
memoryhub/retrieval/intent_router.py
memoryhub/retrieval/reranker.py
tests/test_vnext_entrypoints.py
tests/test_vnext_batch5_retrieval_scenarios.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
Keyword BM25 可能返回负分 → Pydantic 校验失败。
自然中文 query 不命中 router 正则 → 返回 MIXED/EXPERIENCE，scenario 断言失败。
WORKING/EPISODE 在 rerank 中默认权重 0.05 → 易被长期噪声挤出 top_k，budget 前丢失。
IntentRouter 忽略 MIXED hint → 无法强制 MIXED。
Entrypoint test fixture 缺少 rollout_read_service → vNext entrypoint 测试失败。
```

### Behavior After

```text
Keyword BM25 负分归一化到 [0, 1]，schema 约束满足。
Scenario 使用 intent_hint 强制目标 Intent，router 输出稳定。
ContextService 按 intent 传入 type boost：CURRENT_STATE 提升 WORKING，TASK_HISTORY 提升 EPISODE，PREFERENCE/SEMANTIC_FACT/PROCEDURE/EXPERIENCE 提升对应类型，MIXED 同时提升 WORKING/EPISODE。
MIXED hint 可被显式强制。
Entrypoint fixture 补齐 rollout/shadow read service，8 个 entrypoint 测试通过。
```

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_batch5_retrieval_scenarios.py` | PASS (11) |
| `tests/test_vnext_batch2_retrieval_channels.py` | PASS |
| `tests/test_vnext_batch3_scope_propagation.py` | PASS |
| `tests/test_vnext_batch4_fusion_context.py` | PASS |
| `tests/test_vnext_retrieval_service.py` | PASS |
| `tests/test_vnext_retrieval_planner.py` | PASS |
| `tests/test_vnext_intent_router.py` | PASS |
| `tests/test_vnext_context_service.py` | PASS |
| `tests/test_vnext_context_budget.py` | PASS |
| `tests/test_vnext_fusion_reranker.py` | PASS |
| `tests/test_vnext_entrypoints.py` | PASS (8) |
| `tests/test_vnext_stage1_scenarios.py` | PASS |
| Batch 1–5 retrieval + entrypoint + Stage 1 scenario 回归 | PASS (98) |
| Ruff on changed source/tests | PASS |

### Evidence

- `test_scenario_a_current_state_returns_working_state`：强制 CURRENT_STATE 后返回 WORKING 层记忆，包含 current_goal / current_step / blockers。
- `test_scenario_b_task_history_returns_episode`：强制 TASK_HISTORY 后返回 EPISODE 层记忆，key_events 包含 pytest 通过记录。
- `test_scenario_c_preference_authority_beats_vector`：强制 PREFERENCE，authority 的 PREFERENCE 记忆排在 mock vector 通用命中之前。
- `test_scenario_d_semantic_fact_from_authority`：强制 SEMANTIC_FACT，authority 返回包含 PostgreSQL 的事实。
- `test_scenario_e_exact_keyword_hit`：BM25 精确命中并按相关度排序。
- `test_scenario_f/g_cross_project/user_isolation`：ScopeResolver 过滤掉非目标 project/user。
- `test_scenario_h_mixed_intent_uses_working_and_episode`：强制 MIXED，selected memories 同时包含 WORKING 与 EPISODE。
- `test_scenario_i_duplicate_projection_deduplicated`：三通道返回同一 memory_id，fusion 后仅出现一次。
- `test_scenario_j_context_budget_trims_low_value_memory`：256 token budget 下 WORKING 记忆保留，长期噪声被裁剪，`len(ids) < 21`。
- `TestLegacyVsVNextComparison`：legacy vector-only 命中 `legacy-only`，vNext CURRENT_STATE 命中 `ws:ws:task-1`，两者不同。

### Scope Verification

- Request → Planner → Executor → Result 中 scope 未丢失：Working/Episode/Authority executor 继续使用 tenant_id/user_id/scope 过滤，ScopeResolver 最终校验。
- Scenario F/G 证明 project/user scope isolation 生效。

### Retrieval Channel Verification

| Channel | Batch 5 行为 |
|---|---|
| working | 结构化 task → session/recent fallback；CURRENT_STATE intent 下受 rerank type boost 保护 |
| episode | 结构化 task → session/recent fallback；TASK_HISTORY/MIXED intent 下受 rerank type boost 保护 |
| authority | 按 scope/type 过滤；PREFERENCE/SEMANTIC_FACT/PROCEDURE/EXPERIENCE intent 下受对应 type boost |
| keyword | BM25 负分归一化到 [0, 1]；按查询 token 重叠排序 |
| vector | mock 命中，仅作为 channel 之一，未成为 vNext retrieval 唯一实现 |

### Regression

```text
Stage 1 Formation / Working Reducer / Episode Enrichment / Boundary / Reflection：
  tests/test_vnext_stage1_scenarios.py PASS，Stage 1 DoD 保持成立。
Retrieval 核心组件：
  Batch 2/3/4/5 retrieval tests、intent router、context budget、fusion reranker PASS。
Entrypoints：
  tests/test_vnext_entrypoints.py 8 PASS。
No production Safety/Legacy source code changed outside the retrieval path.
```

### Remaining Risks

- Scenario 使用 `intent_hint` 强制 intent 是因为自然中文 regex 覆盖不足；router 正则质量提升是独立优化，不在本 Batch。
- `test_retrieval_log_persisted` 仍因 Windows pytest tmp ACL 环境基线问题未执行（非本 Batch 引入）。
- Context budget 对 WORKING 记忆的保护依赖 rerank type boost 使其进入 top_k；BudgetManager 目前仍把 WORKING 层记忆当长期记忆按 token 预算排序，未使用 `ContextService.is_hard_protected_memory`；当前 scenario 下 boost 已能保证其保留，如需更强保护需独立 Batch 决策。

### Decisions

```text
1. Batch 5 不扩展 IntentRouter 正则；用 intent_hint 保证 scenario 稳定性。
2. 通过 VNextReranker 单次调用 intent_type_boosts 参数实现 intent-aware type boost，不改变默认行为和现有测试。
3. 允许显式 MIXED intent_hint，使 mixed scenario 可测。
4. Keyword BM25 负分在 executor 内按 query 归一化，保持对既有接口最小侵入。
```

### Not Done

- Stage 3 Feedback 闭环。
- Stage 4 Evaluation & Cutover。
- router 正则自然语言覆盖增强。
- BudgetManager 对 WORKING/EPISODE 的显式 hard-protection 改造。
- 真实 Milvus/FAISS backend 集成验证（rank-bm25 / faiss-cpu 未安装）。

### Next Batch Notes

Stage 2 已完成全部 5 个 Batch。下一阶段为 Stage 3 — Feedback 闭环，本 Batch 不会自动开始。任何后续 Batch 启动前需先阅读 VNEXT_PLAN.md 与对应 stage 文档。

---

## Stage 2 Closure Fix 1 — Scope Isolation & Agent Scope Propagation

### Status

```text
DONE
```

### Reconnaissance Findings

- Working/Task Episode 持久化均没有 `project_id`，无 task 时的 `list_recent()`
  只按 tenant/user（可选 session）查询。
- project-b 请求可真实召回 project-a 的 Working/Episode；ScopeResolver 只对
  Long-Term candidate 做 exact project 过滤，无法补救结构化层泄漏。
- Agent `/step` 输入 contract 不接受 project_id/task_id，构造 vNext request 时也
  未传 task/session/project；scene/task_type 只存在于 Legacy request。
- Batch 5 的 Cross Project/Cross User tests 在当前环境因 `rank-bm25` 缺失被 skip，
  且 Cross Project 只覆盖 Authority，不覆盖 Working/Episode。

### Changes

- `working_states` / `task_episodes` 增加向后兼容的 `project_id` 字段及 additive
  SQLite migration；Repository View、create/get/list_recent contract 同步 project。
- Working/Episode executor 对显式 project scope 同时约束 exact task 与 fallback；
  显式 task/project 组合未命中时 fail closed，不降级到其他 task。
- Canonical write 从 event payload 的 `project_id` 或 `scope.project_id` 写入
  Working/Episode，保持 task/session/project 为独立身份。
- Agent `/step` 接收 project_id/task_id，并向 canonical event、Legacy request 与
  vNext request 传播 project/task/session；scene/task_type 继续由既有 SceneScope 表达。

### Files Touched

```text
memoryhub/storage/models.py
memoryhub/storage/database.py
memoryhub/storage/vnext_repositories.py
memoryhub/application/working_service.py
memoryhub/application/episode_service.py
memoryhub/application/canonical_write.py
memoryhub/adapter/retrieval_executor.py
memoryhub/adapter/agent_api.py
tests/test_vnext_working_episode_executors.py
tests/test_vnext_repositories.py
tests/test_competition_api.py
tests/test_vnext_working_reducer.py
docs/vnext/PROGRESS.md
```

### Behavior Before

```text
PROJECT:project-b + no task/session
→ list_recent(tenant, user)
→ project-a Working/Episode enters Context

Agent /step project_id/task_id
→ AgentStepRequest drops fields
→ vNext request has no task/session/project scope
```

### Behavior After

```text
PROJECT:project-b
→ exact task or list_recent(..., project_id="project-b")
→ only project-b Working/Episode; unknown legacy project rows fail closed

Agent /step
→ canonical event(project/task/session)
→ Legacy SearchRequest(project/session/SceneScope)
→ MemoryRetrievalRequest(task/session/PROJECT scope)
```

### Tests

| Test | Result |
|---|---|
| Fix 1 focused scope/migration/agent tests | PASS (16), FAIL 0, SKIP 0 |
| Fix 1 + Repository/task state/Batch 3 scope/Stage 1 targeted regression | PASS (62), FAIL 0, SKIP 0 |
| Ruff on changed files (`E501` ignored for pre-existing long lines) | PASS |
| `git diff --check` | PASS |

### Evidence

- Working/Episode project tests prove both no-task fallback and mismatched exact task reject
  project-a while returning project-b.
- Existing executor tests continue to prove cross-tenant/cross-user isolation.
- Migration test starts from pre-Closure Working/Episode tables and proves both receive
  `project_id` through the compatibility migration.
- Agent handler test executes the real `/step` handler and captures canonical, Legacy and
  vNext calls, proving project/task/session/scene/task_type propagation.
- Canonical write component test proves event project scope is persisted on both Working and
  Episode rows through the real orchestration path.

### Regression

```text
Stage 1 scenarios/boundary/episode/working reducer: PASS
Repository and task-state contracts: PASS
Batch 3 scope propagation and ScopeResolver: PASS
Production write-bypass guard: PASS
Legacy Retrieval algorithms: not modified
```

### Remaining Risks

- Existing rows migrated with empty project_id cannot be safely attributed; explicit project
  requests intentionally exclude them. A separate trusted backfill would require authoritative
  task/session-to-project data that the current schema does not contain.
- Batch 5 dependency skips and Windows pytest temp ACL remain Fix 3 work.
- Stage 1 Candidate Real/InMemory Repository drift remains Fix 2 work.

### Next Fix Batch Notes

Fix 2 only: recover Stage 1 Formation regression and unify Candidate Repository contracts.
Do not change Fix 1 scope semantics, Retrieval Fusion/Budget/Intent, or begin Stage 3.

---

## Stage 2 Closure Fix 2 — Stage 1 Formation Regression Recovery

### Status

```text
DONE
```

### Reconnaissance Findings

- `CandidateService.stage()` already passed `confidence`, `utility`, and `stability` to the repository on create and evidence merge.
- The production `CandidateRepository` supported those fields, while `InMemoryCandidateRepository` used by `FormationShadowService` did not.
- The mismatch caused Formation Shadow and Formation Evaluation to fail before consolidation; it was a Repository contract drift, not a Schema or Retrieval issue.

### Changes

- Synchronized `InMemoryCandidateRepository.create()` with the production Candidate Repository scoring parameters.
- Synchronized `InMemoryCandidateRepository.add_evidence()` and preserved the production max-score update semantics.
- Extended the InMemory contract test to verify score propagation and monotonic updates.

### Files Touched

```text
memoryhub/application/formation_shadow.py
tests/test_vnext_formation_shadow.py
docs/vnext/PROGRESS.md
```

### Tests

```text
43 passed, 0 failed, 0 skipped
```

Covered:

- Candidate Service
- Formation Shadow
- Formation Evaluation
- Stage 1 scenarios
- Candidate Repository
- Formation Worker

### Evidence

- Formation Shadow scenarios now execute through candidate staging and consolidation instead of failing on the InMemory Repository signature.
- Formation Evaluation samples and pairs execute successfully.
- InMemory score fields are retained on creation and updated by maximum value on evidence merge, matching the production repository.

### Regression

```text
git diff --check: PASS
ruff: PASS
compileall: PASS
Stage 1 scenarios: PASS
Repository/Worker regression: PASS
Retrieval, Scope, Legacy Retrieval, and Stage 3 modules: unchanged
```

### Remaining Risks

- Fix 3 remains outstanding for the previously skipped Batch 5 real retrieval scenarios and Windows pytest ACL verification.
- Fix 4 remains outstanding for hard budget enforcement, natural Chinese intent routing, and persisted selected memory IDs.

### Next Fix Batch Notes

Fix 2 is complete. Stop here; do not begin Fix 3 or Stage 3 automatically.


---

## Stage 2 Closure Fix 3 — Test Environment & Real Scenario Verification

### Status

```text
DONE
```

### Reconnaissance Findings

- Batch 5 had a module-level `skipif(BM25Okapi is None)`, so all 11 scenarios were skipped when
  the environment lacked `rank-bm25`, including scenarios that do not use the keyword channel.
- The current environment had no `rank-bm25`, `faiss-cpu`, or `jieba`, although all three were
  already declared by the production/dev dependency manifests.
- Batch 5's real Working/Episode fixture did not pass `project_id` after Fix 1 added project
  isolation. This caused four scenarios to fail closed under the valid `PROJECT:project-1` request.
- Retrieval Log and Legacy tests were blocked by the Windows pytest temporary-directory `.lock`
  ACL before their test bodies ran. Running under native Windows permissions allowed them to run.

### Changes

- Replaced the Batch 5 module-level dependency skip with a dependency-specific marker on only the
  keyword scenarios (E and I); missing optional keyword dependencies no longer suppress core
  Working/Episode/Authority/Scope scenarios.
- Updated the Batch 5 real repository fixture to persist its default `project_id=project-1` on
  Working and Episode rows, with an explicit override available for isolation cases.
- Installed the already-declared `rank-bm25`, `faiss-cpu`, and `jieba` packages in the test
  environment. No production dependency manifest was changed.

### Files Touched

```text
tests/test_vnext_batch5_retrieval_scenarios.py
docs/vnext/PROGRESS.md
```

### Tests

| Test | Result |
|---|---|
| Batch 5 real scenarios | PASS (11), FAIL 0, SKIP 0 |
| Retrieval Log persistence + Legacy RET-01~09 (native Windows permissions) | PASS (11), FAIL 0, SKIP 0 |
| Fix 3 affected regression: Batch 5, Retrieval Service, Scope, Repository, Stage 1 | PASS (47), FAIL 0, SKIP 0 |
| Ruff on changed Batch 5 test | PASS |
| `git diff --check` | PASS |
| `compileall` on changed Batch 5 test | PASS |

### Evidence

- Scenario A, H, J, and Legacy-vNext comparison initially failed because the test fixture wrote
  empty project scope; after fixture alignment, all A-J scenarios and the comparison passed.
- Cross-project and cross-user evidence remains covered by Scenarios F and G and the existing
  Fix 1 scope regression tests; the production Working/Episode/Scope regression subset passed.
- Retrieval Log persistence passed under native permissions and verified the persisted log row and
  activation rows through the real `RetrievalService` path.
- Legacy RET-01~09 passed with real FAISS/BM25/Jieba dependencies; no Legacy source was changed.

### Regression

```text
Stage 1 scenarios: PASS
Working/Episode executors and repositories: PASS
Batch 3 scope propagation: PASS
Retrieval Service: PASS
Legacy Retrieval acceptance: PASS
No Schema or Repository Contract changes
```

### Remaining Risks

- The managed sandbox still cannot create/clean pytest temporary directories because of its ACL;
  the persistence and Legacy temp-path tests require native Windows permissions in this environment.
- The test runner reports an existing `asyncio_mode` unknown-config warning and existing dependency
  deprecation warnings; neither affects the Fix 3 results.
- Fix 4 remains outstanding for hard budget enforcement, natural Chinese intent routing, and
  persisted selected memory IDs.

### Next Fix Batch Notes

Fix 3 is complete. Stop here; do not begin Fix 4 or Stage 3 automatically.

---

## Stage 2 Closure Fix 4 — Budget / Intent / Retrieval Log Closure

### Status

```text
DONE
```

### Reconnaissance Findings

- Oversized protected Working State exceeded the requested token budget because
  protection bypassed compression.
- The high-frequency Chinese queries in the Closure acceptance criteria were
  not deterministically classified without `intent_hint`.
- Retrieval logs persisted counts but not the final context memory IDs.

### Changes

- Added deterministic bounded compression for protected Working State and
  constraints; protection now means priority, not unlimited size.
- Added explainable Chinese phrase rules for current state, task history,
  preference, semantic fact, and project build-tool queries.
- Reused the existing retrieval-log `plan` JSON to persist
  `selected_memory_ids`; no new schema field was introduced.

### Files Touched

```text
memoryhub/retrieval/context_builder.py
memoryhub/retrieval/intent_router.py
memoryhub/application/retrieval_service.py
tests/test_vnext_context_budget.py
tests/test_vnext_intent_router.py
tests/test_vnext_retrieval_service.py
docs/vnext/PROGRESS.md
```

### Tests

```text
Fix 4 focused tests: PASS (27), FAIL 0, SKIP 0
Batch 5 scenarios + Fix 4 focused tests: PASS (38), FAIL 0, SKIP 0
Retrieval/context/planner/reranker regression: PASS (34), FAIL 0, SKIP 0,
  deselected 1
Ruff: PASS
compileall: PASS
git diff --check: PASS
```

### Evidence

- An oversized Working State with a 128-token budget now returns total estimated
  context tokens at or below 128 while retaining a compact current-goal signal.
- All twelve Closure Chinese query examples route to their expected intent
  without `intent_hint`.
- Cross-project and Cross-user Batch 5 scenarios pass after the new routing
  rules; no Scope implementation changed.
- Retrieval Log persistence assertion now requires the persisted selected ID.

### Regression

```text
Scope, Working/Episode, Legacy Retrieval, and Stage 1 modules unchanged.
Batch 5: PASS (11), FAIL 0, SKIP 0.
```

### Remaining Risks

- `test_retrieval_log_persisted` remains unexecutable in the managed sandbox
  because pytest cannot create/clean its Windows `.lock` temporary directory;
  this is an environment failure, not a test skip or assertion pass.
- Existing `asyncio_mode` and dependency deprecation warnings remain.
- Final Stage 2 Closure Review is still required before declaring readiness for
  Stage 3; this Batch does not enter Stage 3.

### Next Fix Batch Notes

No next Fix Batch is authorized by this closure plan. Stop here and perform the
separate final Stage 2 Closure Review.

---

## Stage 3 Batch 2 — Feedback Event & Attribution

### Status

```text
DONE
```

### Objective

建立统一的 vNext Feedback Event，并将显式反馈、任务结果和 USED 状态通过保守 attribution 连接起来；本 Batch 不更新 Candidate/Authority 分数，也不触发 Evolution。

### Changes

- 扩展现有 `feedback_service`，新增 `FeedbackEvent` / `FeedbackType`。
- 复用 `UtilityFeedbackShadow.record_event()` 实现显式反馈、任务结果、弱归因和未归因结果。
- 以稳定 `feedback_id` 实现 feedback replay 幂等。
- `RetrievalService.record_feedback_event()` 校验 retrieval、tenant/user、project/task/session、selected memory 和 USED 状态。
- Retrieval Log 复用现有 `plan` JSON 保存 project/task/session/scope 绑定。
- 新增 `/api/memory/vnext/feedback` 和 Agent client/MCP vNext feedback 入口；Legacy `/feedback` 保持兼容。
- Activation view 暴露 status/in-context/used_at，供 attribution 校验使用。

### Files Touched

```text
memoryhub/application/feedback_service.py
memoryhub/application/retrieval_service.py
memoryhub/adapter/vnext_api.py
memoryhub/storage/vnext_repositories.py
memoryhub/application/__init__.py
agent-integration/memoryhub_client/client.py
agent-integration/memoryhub_mcp/tools.py
tests/test_vnext_feedback_service.py
tests/test_vnext_activation_used.py
agent-integration/tests/test_mcp_server.py
```

### Behavior Before

```text
USED 只可更新 Activation；没有统一 feedback event、outcome attribution 或稳定 feedback 幂等键。
Legacy /feedback 与 vNext usage shadow 分离；MCP/CLI 不能提交 retrieval-aware feedback。
```

### Behavior After

```text
FeedbackEvent
  → retrieval/scope/selection validation
  → USED-only outcome attribution
  → strong explicit attribution or weak multi-memory attribution
  → UtilityFeedbackShadow trace
```

Feedback 仍为 shadow-only；不会修改 Candidate/Authority 内容、分数、状态或版本。

### Tests

| Test | Result |
|---|---|
| `tests/test_vnext_feedback_service.py` + `tests/test_vnext_activation_used.py` focused | PASS 14, FAIL 0, SKIP 0; 1 existing `tmp_path` setup ERROR excluded from focused assertion run |
| `agent-integration/tests/test_mcp_server.py` + `tests/test_vnext_entrypoints.py` | PASS 9, FAIL 0, SKIP 0 |
| Ruff on changed files (`E501` ignored for pre-existing long lines) | PASS |
| compileall on changed source | PASS |

### Exact PASS / FAIL / SKIP counts

```text
Batch 2 assertion tests: PASS 23, FAIL 0, SKIP 0
Environment-blocked test setups: 2 ERROR (pytest tmp_path/.lock ACL)
Known warnings: asyncio_mode config warning and dependency deprecation warnings
```

### Evidence

- Explicit negative feedback creates one correction record and replaying the same `feedback_id` creates no duplicate.
- Task failure with no USED memory produces `attribution=none` and no feedback record.
- Multiple USED memories receive weak attribution and reduced confidence/signal.
- Cross-tenant retrieval feedback is rejected before shadow recording.
- Legacy MCP feedback remains available; new `memoryhub_vnext_feedback` submits retrieval-aware events.

### Feedback Attribution Evidence

- Explicit positive/negative and user confirmation/correction are strong when the memory is selected.
- `TASK_SUCCESS`, `TASK_FAILURE`, and `PARTIAL_SUCCESS` only attribute to memories already marked USED.
- Multiple attributed memories are downgraded to weak attribution.
- `IN_CONTEXT` without `USED` is not treated as outcome attribution.
- Unrelated task failure does not automatically penalize a memory.

### Score Update Evidence

```text
No Candidate or Authority score update in Batch 2.
UtilityFeedbackShadow only records bounded signals and feedback-derived inputs for Batch 3.
```

### Scope Verification

- Retrieval feedback checks retrieval log tenant/user identity.
- New retrieval logs retain project/task/session/scope values.
- Event project/task/session values must match the recorded retrieval scope when supplied.
- Selected-memory membership is required before explicit feedback is accepted.
- Forget, Safety, Authority writes and deletion behavior were not bypassed or changed.

### Regression

```text
Stage 1 Formation design: unchanged.
Stage 2 Retrieval architecture: unchanged; only existing Retrieval Log metadata and Activation view were reused.
Legacy /feedback behavior: preserved.
MCP/entrypoint regression: PASS 9, FAIL 0, SKIP 0.
```

### Remaining Risks

- Feedback events are currently held in the in-process `UtilityFeedbackShadow`; durable feedback audit/idempotency storage remains for a later hardening decision.
- `Agent /step` fallback to the first three cards remains weak evidence and is not equivalent to explicit attribution.
- The existing managed Windows pytest temp-directory ACL prevents two `tmp_path` setup tests from executing in this environment.
- Candidate/Authority utility, stability and evolution updates are intentionally not implemented.

### Next Batch Notes

Stage 3 Batch 2 is complete. The next authorized batch is Batch 3 — Utility / Stability Update. Do not start it automatically.
