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
vNext Stage: Stage 1 — Formation 实化
Status: IN PROGRESS

Formation Mode:
candidate-only

Current Target:
Event
→ Working State
→ Episode
→ Boundary
→ Structured Reflection
→ Candidate
```

---

# 3. Stage 状态总览

| Stage | 名称 | 状态 | 备注 |
|---|---|---|---|
| Stage 1 | Formation 实化 | IN PROGRESS | Batch 1 已完成；不进入下一 Batch |
| Stage 2 | Retrieval 实化 | NOT STARTED | Stage 1 完成后开始 |
| Stage 3 | Feedback 闭环 | NOT STARTED | 暂不执行 |
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
| Batch 5 | Stage 1 Scenario Tests | NOT STARTED | - |

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
- [ ] Legacy 主链路无明显回归。
- [ ] 至少 6 类 Scenario Test 通过。

---

# 8. Stage 1 Scenario 结果

## Scenario A — 正常 Coding Task

```text
Status: NOT RUN

Result:
TODO
```

## Scenario B — 失败后恢复

```text
Status: NOT RUN

Result:
TODO
```

## Scenario C — 低价值事件

```text
Status: NOT RUN

Result:
TODO
```

## Scenario D — Explicit Remember

```text
Status: NOT RUN

Result:
TODO
```

## Scenario E — candidate-only

```text
Status: NOT RUN

Result:
TODO
```

## Scenario F — LLM Invalid Output

```text
Status: NOT RUN

Result:
TODO
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
Start Stage 1 / Batch 4

Task:
Boundary-driven Formation

Before coding:
Read VNEXT_PLAN.md
Read stage1-formation.md
Read PROGRESS.md

Then perform Codebase Reconnaissance only. Do not start Batch 5.
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
