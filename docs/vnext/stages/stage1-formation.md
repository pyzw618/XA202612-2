# stage1-formation.md

# Stage 1 — Formation 实化

## 1. Stage 目标

本阶段只解决一个核心问题：

> 将当前 vNext 从“具备 Formation 架构与领域模型”推进到“能够基于真实 Agent 事件形成有意义的 Working State、Episode 和 Candidate”。

本阶段目标主链路：

```text
Raw Agent Event
      ↓
Event Normalization
      ↓
Working State Reducer
      ↓
Meaningful Working State
      ↓
Episode Accumulation
      ↓
Meaningful Episode
      ↓
Boundary Detection
      ↓
Structured Reflection
      ↓
Candidate
```

本阶段结束后仍保持：

```text
formation_mode = candidate-only
```

不进行 Long-Term Authority 全量接管。

---

# 2. 当前问题假设

在正式修改前，Codex 必须通过代码确认以下判断是否成立：

1. vNext Formation 是否仍默认使用 deterministic / mock reflection。
2. 当前配置中的真实 LLM Client 是否已注入 ReflectionService。
3. CanonicalWriteService 对 Working State 的更新是否主要依赖 Event Payload 已经存在的状态字段。
4. OpenCode / MCP / Agent Event 是否通常只包含 tool trace、tool result、text 等原始事件。
5. EpisodeEvent 当前是否只保存较浅信息，例如 event_id / phase。
6. BoundaryDetector 是否已存在但尚未成为 Formation 的主要触发条件。
7. Formation 是否仍近似按 Event 粒度触发。
8. Candidate 当前是否可以由 ReflectionResult 正常创建。
9. candidate-only 模式是否能保证 Stage 1 期间不直接写 Long-Term Authority。

如果代码实际情况与以上假设不同，Codex 应在执行前说明，并调整最小实现方案。

---

# 3. Stage 1 非目标

以下内容明确不属于本阶段：

- 不实现完整 Working / Episode / Authority 多路 Retrieval。
- 不重写现有 Retrieval Planner。
- 不实现 Activation USED 闭环。
- 不实现完整 Utility Feedback。
- 不重构 Rollout Controller。
- 不进行 vNext Authority 全量切换。
- 不删除 Legacy Formation。
- 不大规模修改 Safety。
- 不大规模修改 Lifecycle。
- 不重做数据库架构。
- 不为“代码更优雅”进行无关重构。
- 不提前执行 Stage 2 / Stage 3 / Stage 4。

---

# 4. Stage 1 核心原则

## 4.1 Event 不等于 Memory

单个工具事件不能直接被视为长期记忆。例如 read_file、write_file、git status、run test、command failed、command success，都优先作为任务状态和 Episode Evidence。

## 4.2 deterministic reducer 优先

对于可确定的信息，优先通过规则归约：

```text
Tool Event
  ↓
Normalized Event
  ↓
State Reducer
  ↓
Working Patch
```

只有复杂语义判断才使用 LLM。

## 4.3 Reflection 必须使用真实配置的 LLM

Stage 1 完成后，正常 vNext Formation 路径不能继续默认依赖 deterministic reflection。测试中允许使用 deterministic / fake model。

生产/正常运行路径应通过现有配置系统获取 LLM Client。

## 4.4 Formation 必须逐渐从 Event Trigger 转向 Boundary Trigger

目标：

```text
多个 Event 累积
  ↓
Working / Episode 更新
  ↓
meaningful boundary
  ↓
Reflection
```

Boundary 触发逻辑必须可测试、可解释。

---

# 5. Batch 划分

Stage 1 拆成 5 个 Batch。

每个 Codex 会话原则上只执行一个 Batch。每完成一个 Batch 必须：

1. 运行对应测试。
2. 输出修改证据。
3. 更新 `docs/vnext/PROGRESS.md`。
4. 停止。
5. 不自动开始下一个 Batch。

---

# 6. Batch 1 — Structured Reflection 接入

## 6.1 Objective

让 vNext Formation 正常运行时使用真实配置的 Structured Reflection，而不是默认 deterministic reflection。

目标链路：

```text
Application Config
  ↓
Existing LLM Client
  ↓
StructuredReflectionModel
  ↓
ReflectionService
  ↓
FormationWorker
  ↓
ReflectionResult
  ↓
Candidate
```

## 6.2 Reconnaissance

修改前重点检查：

- `memoryhub/app.py`
- `memoryhub/config.py`
- `memoryhub/llm/`
- `memoryhub/application/`
- ReflectionService
- StructuredReflectionModel
- FormationWorker
- CandidateService
- 当前测试

回答：

1. 当前 ReflectionService 如何创建。
2. 默认 Reflection Model 是什么。
3. 现有真实 LLM Client 在系统其他模块如何装配。
4. 是否已有 Structured Output 能力。
5. ReflectionResult 的字段约束是什么。
6. LLM 失败时当前行为是什么。
7. 哪些测试依赖 deterministic model。

## 6.3 Required Behavior

正常运行路径：

```text
configured llm
→ structured reflection
→ validated ReflectionResult
```

测试路径仍允许：

```text
fake / deterministic reflection model
```

Reflection 输出至少需要稳定表达“是否值得形成 Candidate、Claim、Memory Type、Scope Hint、Evidence Summary、Confidence、Utility、Stability、Reason/Rationale”等等价信息。

如果当前 Domain Contract 字段不同，以实际 Contract 为准，不为满足本文档重复创建 DTO。

## 6.4 Failure Behavior

LLM 出现 timeout、invalid JSON、schema validation failure、empty response、temporary provider failure 时，不得产生未验证 Candidate。

优先：

```text
Reflection Failed
→ 可观测记录
→ 当前 Formation 安全失败
```

不要因为 LLM 失败自动生成高置信度 Candidate。

## 6.5 Acceptance Criteria

Given：同一组合法 Event / Episode Context。

When：使用真实配置的 Reflection 路径。

Then：

1. ReflectionService 使用配置中的 LLM。
2. 输出经过结构验证。
3. 合法输出可以形成 Candidate。
4. 非法输出不会形成 Candidate。
5. 测试仍可以注入 deterministic / fake model。
6. candidate-only 行为保持不变。
7. Legacy Formation 不受影响。

## 6.6 Must Not Change

本 Batch 不修改 Working Reducer 主逻辑、Episode enrichment、Boundary 策略、Retrieval、Feedback、Rollout。

---

# 7. Batch 2 — Event → Working State Reducer

## 7.1 Objective

让真实 Agent Tool Trace 可以稳定更新 Working State，而不是依赖 Event Payload 预先提供完整 working 字段。

目标：

```text
Raw Event
  ↓
Normalized Event
  ↓
State Reducer
  ↓
Working Patch
  ↓
Working State
```

## 7.2 Reducer First

优先覆盖高频、确定性事件，至少考虑：

- file read
- file write / patch
- command execution
- test execution
- tool success
- tool failure
- task start
- task complete
- explicit user instruction
- blocker / error

不要一次设计一个“万能 Reducer”，优先解决真实 Agent Runtime 中最常见事件。

## 7.3 Working State 目标

根据现有 Domain Contract，至少应能表达等价信息：current goal、current step、completed steps、pending steps、blockers、active entities、recent findings、recent failures、next action。

如果当前 WorkingSnapshot / WorkingPatch 字段不同，复用现有字段，不随意创建第二套模型。

## 7.4 Behavioral Example

Given：

```text
1. 用户要求修复 SSE 重连问题
2. read application.yaml
3. read SSE handler
4. run test → failed
5. modify timeout config
6. run test → passed
```

Then Working State 应能够表达类似：

```text
current_goal:
修复 SSE 重连问题

completed:
- 检查配置
- 检查 SSE handler
- 修改 timeout
- 重新运行测试

recent_failures:
- 修改前测试失败

current_result:
- 修改后测试通过

pending:
- 进一步验证重连场景
```

不要求生成完全相同的自然语言，但必须保留相同任务语义。

## 7.5 Acceptance Criteria

1. 常见 Tool Event 可以生成 Working Patch。
2. Working State 会随事件流演化。
3. Tool Failure 不会错误标记为 Completed。
4. Tool Success 可以更新 Completed / Findings。
5. Working State 不退化为原始 Event 列表。
6. 同一事件重复写入不会导致明显重复状态。
7. Existing Working State Contract 保持兼容。

## 7.6 Must Not Change

本 Batch 不调整 Candidate Promotion，不实现完整 Episode Summary，不修改 Retrieval，不修改 Authority。

---

# 8. Batch 3 — Episode Enrichment

## 8.1 Objective

让 Episode 真正保存“任务经历”，而不是只保存 event_id / phase 等浅层信息。

目标：

```text
Event Stream
  ↓
Episode Event
  ↓
Meaningful Episode History
```

Episode 后续必须能成为 Reflection 和 Retrieval 的高质量上下文。

## 8.2 Episode 应保留的信息

根据现有 Schema，尽量复用已有字段，至少保留等价信息：Event Type、Tool Name、Target、Action、Result、Success/Failure、Error Summary、Important Output Summary、State Transition、Timestamp、Source Event ID。

不建议把完整巨大 Tool Output 无限制塞入 Episode。长输出应保留：

```text
summary + reference
```

## 8.3 Episode Boundary

Episode 应具有 start、checkpoint、completion、failure、session boundary 等语义。

本 Batch 重点 enrich Episode 内容，真正的 Reflection Trigger 在 Batch 4 完成。

## 8.4 Acceptance Criteria

Given：一段真实任务 Tool Trace。

Then：

1. Episode 可以恢复任务主要过程。
2. 可以看出关键成功与失败。
3. 可以看出重要修改对象。
4. Episode 不只剩 event_id / phase。
5. Reflection 输入可以使用 Episode 的高信息密度摘要。
6. 不无限存储巨大原始 Tool Output。

---

# 9. Batch 4 — Boundary-driven Formation

## 9.1 Objective

让 Reflection 不再默认无条件按每个 Event 触发，而是由 meaningful boundary 驱动。

目标：

```text
Event
 ↓
Working Update
 ↓
Episode Update
 ↓
BoundaryDetector
 ├─ no boundary → stop
 └─ boundary
       ↓
   Reflection
       ↓
   Candidate
```

## 9.2 Boundary 类型

优先复用已有 BoundaryDetector。至少考虑：

- TASK_START
- TASK_COMPLETE
- TASK_FAILURE
- EXPLICIT_REMEMBER
- SIGNIFICANT_STATE_CHANGE
- EPISODE_CHECKPOINT
- SESSION_BOUNDARY

不要一次实现非常复杂的智能 Boundary Predictor，优先保证确定性边界正确。

## 9.3 Reflection Trigger 原则

以下事件通常不应单独触发 Reflection：单次 read_file、git status、普通 search、无语义变化的重复 command、中间性 tool output。

以下情况应优先触发：用户显式 remember、任务完成、任务失败、重要状态转折、长 Episode checkpoint、session 即将结束。

## 9.4 Acceptance Criteria

1. 普通低价值 Event 不会每条都调用 Reflection。
2. meaningful boundary 可以触发 Reflection。
3. 用户显式 remember 可以触发。
4. Task Complete 可以触发。
5. Task Failure 可以触发。
6. Boundary 行为有测试覆盖。
7. Reflection 仍然基于已有 Working / Episode Context。
8. candidate-only 保持有效。

---

# 10. Batch 5 — Stage 1 Scenario Tests

## 10.1 Objective

建立一组真实连续事件 Scenario，验证 Stage 1 主链路。禁止只依赖 Unit Test 判断 Stage 1 完成。

## 10.2 必测 Scenario

### Scenario A — 正常 Coding Task

```text
用户目标
→ 读文件
→ 修改文件
→ 运行测试
→ 测试通过
→ Task Complete
```

验证 Working 正确演化、Episode 有意义、Completion Boundary、Reflection、Candidate。

### Scenario B — 失败后恢复

```text
Command Failed
→ 分析错误
→ 修改配置
→ Command Success
```

验证 Failure 不被标记成完成，Working 能体现失败与恢复，Episode 保留关键转折。

### Scenario C — 低价值事件

```text
read file
→ git status
→ search
→ read another file
```

验证不应每个 Event 都形成 Candidate，也不应频繁调用 Reflection。

### Scenario D — Explicit Remember

```text
用户明确要求记住：
“这个项目以后使用 Maven”
```

验证可以立即形成强 Boundary，可以进入 Reflection / Candidate，Scope 不应无条件扩成 global。

### Scenario E — candidate-only

验证 Candidate created，但 Long-Term Authority 未被 vNext 自动写入。

### Scenario F — LLM Invalid Output

验证 Reflection schema validation 失败、不产生脏 Candidate、存在可观测记录。

---

# 11. Stage 1 测试层级

必须至少包含：

## Unit

- Reducer
- Boundary
- Reflection validation

## Component

- Event → Working
- Event → Episode
- Boundary → Reflection
- Reflection → Candidate

## Scenario

真实连续 Agent Event。

## Regression

- Legacy 主路径不回归
- Safety 不回归
- candidate-only 不回归

---

# 12. Stage 1 Definition of Done

Stage 1 只有全部满足以下条件才视为完成：

- [ ] 正常 vNext Reflection 使用配置中的真实 LLM。
- [ ] Reflection 输出经过结构化验证。
- [ ] 常见 Agent Tool Trace 能驱动 Working State。
- [ ] Working State 能表达当前任务状态，而不是 Event Log。
- [ ] Episode 能表达主要任务过程。
- [ ] Episode 包含关键成功/失败/修改/结果信息。
- [ ] Formation 可以由 meaningful boundary 触发。
- [ ] 普通低价值 Event 不再逐条触发 Reflection。
- [ ] Explicit Remember 可以触发 Formation。
- [ ] Task Complete / Failure 有明确 Formation 行为。
- [ ] 合法 Reflection 可以形成 Candidate。
- [ ] 非法 Reflection 不产生 Candidate。
- [ ] candidate-only 模式仍然有效。
- [ ] Legacy 主链路无明显回归。
- [ ] 至少 6 类 Scenario Test 通过。

未全部满足时，不得在 PROGRESS.md 中声明 Stage 1 DONE。

---

# 13. Codex 每个新会话的启动提示词

```text
你正在执行 MemoryHub vNext Stage 1。

开始前必须完整阅读：

1. docs/vnext/VNEXT_PLAN.md
2. docs/vnext/stages/stage1-formation.md
3. docs/vnext/PROGRESS.md

先不要修改任何代码。

首先执行 Codebase Reconnaissance：

- 确认当前 Batch 的真实实现状态
- 找到实际调用链
- 确认相关文件
- 确认现有可复用组件
- 确认当前测试
- 对照 Stage 文档判断描述是否与代码一致
- 给出最小修改计划
- 明确本 Batch 不会修改哪些模块

完成分析后停止，不要自动修改代码。
```

---

# 14. Codex Batch 执行提示词

在 Reconnaissance 结果确认无明显偏差后使用：

```text
按照刚才确认的计划执行当前 Batch。

执行约束：

1. 只处理当前 Batch。
2. 不提前实现后续 Batch。
3. 优先复用已有抽象。
4. 不建立平行体系。
5. 不进行无关重构。
6. 单个 Batch 原则上修改不超过 8 个核心源码文件。
7. 每完成一个逻辑单元立即运行相关测试。
8. 以 VNEXT_PLAN.md 的架构原则为最高约束。
9. 如果实际代码与 Stage 文档冲突，优先保证现有系统兼容，并记录差异。
10. 如果需要新的架构决策，不要擅自扩大修改范围。

完成后必须：

- 运行本 Batch 相关测试
- 输出 Changes
- 输出 Tests
- 输出 Evidence
- 输出 Remaining Risks
- 输出 Files Touched
- 说明 Behavior Before / After
- 更新 docs/vnext/PROGRESS.md
- STOP

不要自动执行下一个 Batch。
```

---

# 15. Stage 1 最终审查输出格式

Stage 1 全部 Batch 完成后，Codex 应输出：

```text
Stage 1 Completion Review

1. Definition of Done
   - 条目 1: PASS / FAIL
   - 条目 2: PASS / FAIL
   ...

2. Main Flow
   Event
   → Working
   → Episode
   → Boundary
   → Reflection
   → Candidate

3. Scenario Results
   - A:
   - B:
   ...

4. Regression
   - Legacy:
   - Safety:
   - candidate-only:

5. Remaining Risks

6. Files Touched

7. Recommendation
   - Ready for Stage 2
   或
   - Not Ready
```

只有所有关键 DoD 条目通过后，才进入 Stage 2。
