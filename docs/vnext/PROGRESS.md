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
| Batch 2 | Event → Working State Reducer | NOT STARTED | - |
| Batch 3 | Episode Enrichment | NOT STARTED | - |
| Batch 4 | Boundary-driven Formation | NOT STARTED | - |
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
CanonicalWriteService.write() → _orchestrate_working() → WorkingService.

Current important fields:
current_goal, current_step, pending_steps, completed_steps, constraints,
active_entities.

Current limitations:
Updates primarily project state fields already present in event payloads; real
tool-trace reduction belongs to Batch 2.
```

## 5.3 Episode

```text
Current episode write path:
CanonicalWriteService.write() → _orchestrate_episode() → EpisodeService.

Current stored semantics:
Episode snapshot plus append-only event records and boundary checkpoint state.

Current limitations:
Canonical event payload currently stores mainly event_id and phase; meaningful
tool action/result enrichment belongs to Batch 3.
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
- [ ] 常见 Agent Tool Trace 能驱动 Working State。
- [ ] Working State 能表达当前任务状态。
- [ ] Episode 能表达主要任务过程。
- [ ] Episode 包含关键成功/失败/修改/结果。
- [ ] meaningful boundary 可以触发 Formation。
- [ ] 低价值 Event 不逐条触发 Reflection。
- [ ] Explicit Remember 可以触发 Formation。
- [ ] Task Complete / Failure 有明确 Formation 行为。
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
Start Stage 1 / Batch 2

Task:
Event → Working State Reducer

Before coding:
Read VNEXT_PLAN.md
Read stage1-formation.md
Read PROGRESS.md

Then perform Codebase Reconnaissance only. Do not start Batch 3.
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
