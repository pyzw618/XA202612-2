# stage3-feedback.md

# Stage 3 — Feedback 闭环与 Memory Evolution

## 1. Stage 目标

本阶段只解决一个核心问题：

> 让 MemoryHub vNext 从“能够正确形成和检索 Memory”推进到“能够知道 Memory 是否真的被 Agent 使用、使用结果是否有效，并据此更新 Memory 的 utility / stability / evolution state”。

Stage 1 已解决：

```text
Event
  ↓
Working
  ↓
Episode
  ↓
Boundary
  ↓
Reflection
  ↓
Candidate
```

Stage 2 已解决：

```text
Query
  ↓
Intent
  ↓
Planner
  ↓
Working / Episode / Authority / Keyword / Vector
  ↓
Fusion
  ↓
Scope
  ↓
Context
```

Stage 3 要补齐：

```text
Memory Retrieval
      ↓
RECALLED
      ↓
SELECTED
      ↓
IN_CONTEXT
      ↓
USED
      ↓
OUTCOME
      ↓
Feedback Attribution
      ↓
Utility / Stability Update
      ↓
Memory Evolution
```

本阶段完成后，MemoryHub 应第一次具备：

> “不是因为一条 Memory 被召回很多次就认为它有价值，而是根据真实使用和任务结果逐步更新它的长期价值。”

---

# 2. Stage 3 前置条件

开始 Stage 3 前，Codex 必须确认：

1. Stage 2 Closure Final Review 已输出 `READY FOR STAGE 3`。
2. Cross-user isolation 已通过。
3. Cross-project isolation 已通过。
4. Agent tenant/project/task/session scope 已完整传播。
5. Stage 1 Formation 回归为 0 failed。
6. Stage 2 核心 Scenario 已真实执行。
7. Retrieval Activation 至少已经支持：
   - RECALLED
   - SELECTED
   - IN_CONTEXT
8. Retrieval Log 可以恢复 selected memory IDs。
9. Context Budget 与 Intent Routing 已稳定。

如果以上条件仍有关键 FAIL：

不得进入 Stage 3。

---

# 3. Stage 3 核心原则

## 3.1 被召回不等于有用

禁止采用：

```text
memory recalled
→ utility++
```

召回只是 Retrieval 行为。

只有：

```text
Memory 被真正使用
+
任务结果具有可解释反馈
```

才可以影响长期价值。

---

## 3.2 IN_CONTEXT 不等于 USED

Memory 进入 Context 并不意味着 Agent 实际依赖了它。

必须区分：

```text
RECALLED
SELECTED
IN_CONTEXT
USED
```

`USED` 必须有明确证据来源。

---

## 3.3 Outcome 必须与 Usage 分离

Memory 被 Agent 使用后：

```text
USED
```

只能说明：

> Agent 使用了这条 Memory。

不能说明：

> 这条 Memory 是正确的。

还需要：

```text
OUTCOME
```

例如：

- SUCCESS
- FAILURE
- PARTIAL_SUCCESS
- USER_CORRECTED
- USER_REJECTED
- UNKNOWN

---

## 3.4 Feedback Attribution 必须保守

多个 Memory 同时进入 Context 时：

```text
Task Success
```

不能简单：

```text
所有 Memory utility +1
```

必须考虑：

- 是否真正 USED
- 使用强度
- 是否被引用
- 是否属于关键决策
- 是否与最终结果相关
- 是否存在反向证据

无法可靠归因时：

```text
不要强更新
```

优先记录：

```text
weak / uncertain feedback
```

---

## 3.5 显式用户反馈优先级最高

例如：

```text
“这个记忆是错的”
“不要再这样做”
“对，就是这个”
“以后继续这样”
```

explicit feedback 的权重应高于隐式任务结果。

但仍必须遵守 scope 和 safety。

---

## 3.6 Evolution 不等于自动删除

Stage 3 可以更新：

- utility
- stability
- activation state
- dormant / active
- superseded hint
- review state

但禁止因为一次失败就直接：

```text
delete memory
```

删除、遗忘、永久 supersede 仍需要保守策略。

---

# 4. Stage 3 非目标

本阶段明确不做：

- 不进行 vNext 全量 Cutover。
- 不修改默认 rollout 到 vnext。
- 不重写 Retrieval Architecture。
- 不重新设计 Formation。
- 不引入复杂 Reinforcement Learning。
- 不实现 Learning-to-Rank。
- 不大规模改 Milvus / FAISS。
- 不做生产性能压测。
- 不做最终比赛 Benchmark。
- 不做大规模 Dashboard 重构。
- 不允许 Feedback 绕过 Safety / Scope。
- 不允许一次负反馈直接删除 Authority Memory。

这些属于 Stage 4 或后续优化。

---

# 5. Stage 3 Batch 划分

Stage 3 拆成 5 个 Batch：

```text
Batch 1
Activation Completion — USED

Batch 2
Feedback Event & Attribution

Batch 3
Utility / Stability Update

Batch 4
Memory Evolution & Safeguards

Batch 5
Feedback Scenario Tests & Stage 3 Validation
```

每个 Codex 会话原则上只执行一个 Batch。

每个 Batch 完成后：

1. 运行测试。
2. 更新 `docs/vnext/PROGRESS.md`。
3. 输出真实 PASS / FAIL / SKIP。
4. 输出 Evidence。
5. STOP。
6. 不自动开始下一 Batch。

---

# 6. Batch 1 — Activation Completion: USED

## 6.1 Objective

补齐：

```text
RECALLED
→ SELECTED
→ IN_CONTEXT
→ USED
```

让系统可以明确知道：

> 哪些 Memory 最终被 Agent 真正使用。

---

## 6.2 Reconnaissance

重点检查：

- ActivationRepository
- ActivationStatus
- RetrievalService
- ContextService
- agent_api
- MCP / Agent Integration
- feedback_service
- UtilityFeedbackShadow
- Retrieval Log
- 当前 selected memory IDs 传递路径

回答：

1. Activation 当前在哪些位置创建。
2. RECALLED / SELECTED / IN_CONTEXT 分别何时写入。
3. Agent Runtime 是否能拿到 memory IDs。
4. Agent Response 是否能反向携带 used memory IDs。
5. 当前有没有 usage feedback API / event。
6. 是否已有 `USED` 枚举但未真正接入。
7. 是否已有同义能力可以复用。

---

## 6.3 USED Evidence

USED 至少支持一种强证据和一种弱证据。

### Strong Evidence

例如：

```text
Agent 显式回传：
used_memory_ids = [...]
```

或：

```text
tool / action metadata
明确记录 memory attribution
```

### Weak Evidence

例如：

```text
memory 被放入高优先 context
+
agent 输出明显引用其内容
```

但 Stage 3 第一版应优先显式机制。

不要一开始依赖复杂语义判定。

---

## 6.4 Target Flow

```text
Retrieval
  ↓
selected memory IDs
  ↓
ContextPayload
  ↓
Agent
  ↓
usage feedback
  ↓
ActivationRepository
  ↓
status = USED
```

必须保留：

- retrieval_id
- memory_id
- tenant/user/project/task/session
- used_at
- usage source
- confidence

---

## 6.5 Idempotency

同一个：

```text
retrieval_id + memory_id + usage event
```

重复上报时：

不得重复累计 usage。

---

## 6.6 Acceptance Criteria

1. USED 状态真实可写。
2. USED 必须关联 retrieval_id。
3. USED 必须关联 memory_id。
4. Scope 必须一致。
5. 重复 usage feedback 幂等。
6. 未进入 IN_CONTEXT 的 memory 默认不能被直接标记 USED，除非 explicit override 有明确规则。
7. Retrieval Log / Activation 能恢复使用链路。
8. Legacy Retrieval 不受影响。

---

# 7. Batch 2 — Feedback Event & Attribution

## 7.1 Objective

建立统一 Feedback Contract：

```text
Memory Usage
  ↓
Task Outcome
  ↓
Feedback Attribution
```

---

## 7.2 Feedback Types

建议至少支持：

```text
EXPLICIT_POSITIVE
EXPLICIT_NEGATIVE
TASK_SUCCESS
TASK_FAILURE
PARTIAL_SUCCESS
USER_CORRECTION
USER_CONFIRMATION
UNKNOWN
```

如果现有 Contract 已有类似枚举：

优先复用。

---

## 7.3 Feedback Event

每条 Feedback 至少包含：

- feedback_id
- tenant_id
- user_id
- project_id
- task_id
- session_id
- retrieval_id
- memory_ids
- feedback_type
- outcome
- source
- confidence
- timestamp

如果现有 Schema 字段不同：

复用已有 Contract，不重复造模型。

---

## 7.4 Attribution Rules

### Rule A — Explicit Feedback

用户明确指出某条 Memory：

```text
最高可信度
```

### Rule B — Single Used Memory

如果：

```text
一个关键决策
只使用一个 Memory
结果明确成功/失败
```

可以较强归因。

### Rule C — Multiple Used Memories

如果：

```text
多个 Memory 同时 USED
```

默认只能做：

```text
weak attribution
```

除非有显式引用。

### Rule D — IN_CONTEXT but not USED

不得参与强反馈。

---

## 7.5 Negative Feedback

负反馈必须区分：

```text
Memory wrong
```

和：

```text
Memory correct but task failed for other reason
```

因此：

```text
TASK_FAILURE
```

不能直接等于：

```text
memory utility--
```

必须经过 Attribution。

---

## 7.6 Acceptance Criteria

1. Feedback Contract 可持久化或可审计。
2. Explicit Positive 可准确归因。
3. Explicit Negative 可准确归因。
4. Task Success 不会自动强化所有 IN_CONTEXT memory。
5. Task Failure 不会自动惩罚所有 USED memory。
6. 多 Memory 场景有保守策略。
7. Feedback 保留 scope。
8. 重复 feedback 幂等。

---

# 8. Batch 3 — Utility / Stability Update

## 8.1 Objective

把 Attribution 结果真正作用于 Memory：

```text
utility
stability
```

第一版必须保守。

---

## 8.2 Utility 语义

Utility 表示：

> 这条 Memory 对后续任务是否有实际帮助。

Utility 不等于：

- recall frequency
- recency
- confidence

---

## 8.3 Stability 语义

Stability 表示：

> 这条 Memory 在时间和多次使用中是否保持可靠。

例如：

```text
同一 Preference
跨多个 Episode 被确认
→ stability 上升
```

而：

```text
用户明确纠正
→ stability 显著下降
```

---

## 8.4 Update Model

第一版优先采用：

```text
deterministic bounded update
```

不要引入复杂学习算法。

例如概念上：

```text
new_score
=
clamp(
  old_score + weighted_feedback,
  min,
  max
)
```

具体权重应集中定义，禁止散落在多个 Service。

---

## 8.5 Feedback Weight Priority

建议：

```text
Explicit Correction
> Explicit Confirmation
> Strong Outcome Attribution
> Weak Outcome Attribution
> Recall / Context Presence
```

Recall 本身不应直接增加 utility。

---

## 8.6 Candidate vs Authority

需要明确：

```text
Candidate
```

和：

```text
Authority Memory
```

是否使用同一 Feedback Updater。

优先原则：

- Candidate feedback → Candidate confidence / utility / stability
- Authority feedback → Authority metadata / evolution signal

不要把两者混为同一表写入。

---

## 8.7 Shadow First

如果当前 UtilityFeedbackShadow 已存在：

优先先让更新进入：

```text
shadow observation
```

并同时计算：

```text
old score
proposed score
delta
reason
```

确认稳定后再切真实写入。

Stage 3 可以包含“shadow → controlled write”的最小切换机制，但不做全量 rollout。

---

## 8.8 Acceptance Criteria

1. Positive attributed feedback 可以提高 utility。
2. Negative attributed feedback 可以降低 utility。
3. Explicit correction 权重大于 implicit failure。
4. score 有上下界。
5. 同一 feedback 重放不重复更新。
6. update 有 audit / trace。
7. Candidate 与 Authority 更新路径清晰。
8. IN_CONTEXT but not USED 不直接更新 utility。
9. Recall frequency 不直接提高 utility。

---

# 9. Batch 4 — Memory Evolution & Safeguards

## 9.1 Objective

根据长期反馈，把 Memory 从“只有分数”推进到真正的 Evolution State。

目标：

```text
ACTIVE
DORMANT
SUPERSEDED
ARCHIVED
...
```

必须优先复用现有 EvolutionService / EvolutionStatus。

---

## 9.2 Evolution Trigger

允许的 Trigger 示例：

### ACTIVE → DORMANT

长期：

```text
低 utility
+
低 usage
+
无近期确认
```

### DORMANT → ACTIVE

新的：

```text
强 positive feedback
```

### ACTIVE → REVIEW

如果：

```text
显式 negative
+
存在冲突
```

### SUPERSEDED

必须有：

```text
新 Memory
明确替代旧 Memory
```

不能仅凭 score 较低就 supersede。

---

## 9.3 Deletion Boundary

Stage 3 禁止：

```text
negative feedback
→ hard delete
```

删除仍必须遵守：

- forget API
- safety rules
- explicit user deletion
- lifecycle policy

---

## 9.4 Conflict

如果新 Feedback 与当前 Authority 冲突：

优先：

```text
record conflict
↓
review / supersede candidate
```

而不是原地覆盖。

---

## 9.5 Safety

Feedback 不允许：

- 绕过 tenant/user scope
- 修改其他用户 Memory
- 复活已显式 forget 的 Memory
- 恢复已删除敏感信息
- 绕过 quarantine

---

## 9.6 Acceptance Criteria

1. EvolutionService 真正接收 feedback-derived signal。
2. ACTIVE → DORMANT 有明确规则。
3. DORMANT → ACTIVE 可恢复。
4. SUPERSEDED 需要 replacement evidence。
5. Negative feedback 不会直接 delete。
6. Forget 后 Memory 不会被 feedback 自动恢复。
7. Cross-user/cross-project evolution isolation 通过。
8. 所有 Evolution 有 audit trail。

---

# 10. Batch 5 — Feedback Scenario Tests & Stage 3 Validation

## 10.1 Objective

用真实连续 Scenario 验证：

```text
Retrieval
→ Context
→ Usage
→ Outcome
→ Feedback
→ Update
→ Evolution
```

禁止仅靠 Unit Test 宣布 Stage 3 完成。

---

# 11. 必测 Scenario

## Scenario A — Positive Explicit Feedback

Memory：

```text
用户偏好 Maven
```

Agent 使用该 Memory。

用户明确：

```text
“对，以后这个项目都用 Maven。”
```

Expected：

- memory = USED
- explicit positive feedback
- utility ↑
- stability ↑

---

## Scenario B — Explicit Correction

Memory：

```text
项目数据库 = MySQL
```

用户：

```text
“不对，这个项目现在已经换成 PostgreSQL。”
```

Expected：

- old memory 被标记冲突/待 supersede
- old stability ↓
- 不直接 hard delete
- new fact 进入正常 formation/candidate 流程

---

## Scenario C — Task Success with One Used Memory

只有一个关键 Memory 被 USED。

Task 成功。

Expected：

- strong positive attribution
- utility 小幅增加

---

## Scenario D — Task Success with Multiple Context Memories

10 条 Memory IN_CONTEXT。

只有 2 条 USED。

Expected：

- 未 USED 的 8 条不应因为成功被强化
- 2 条 USED 根据 attribution confidence 更新

---

## Scenario E — Task Failure unrelated to Memory

Memory 正确。

Task 因网络超时失败。

Expected：

- 不惩罚正确 Memory

---

## Scenario F — Negative Memory-caused Failure

Agent 明确依赖错误 Procedure。

导致执行失败。

Expected：

- USED
- strong negative attribution
- utility ↓
- stability ↓
- 可能进入 REVIEW / DORMANT

---

## Scenario G — Repeated Positive Use

同一 Memory：

```text
跨多个 Episode
多次 USED
多次成功
```

Expected：

- stability 逐步提升
- 单次重复 feedback 不重复计分

---

## Scenario H — Dormant Reactivation

Memory 已 DORMANT。

后续：

```text
用户明确确认
+
任务成功使用
```

Expected：

```text
DORMANT → ACTIVE
```

---

## Scenario I — Forget Protection

Memory 已被显式 forget。

后续出现旧 feedback replay。

Expected：

- 不恢复 Memory
- 不重新激活
- 记录拒绝原因

---

## Scenario J — Cross Scope Feedback Isolation

Project A Memory 与 Project B Memory 内容相同。

Project A Task Feedback：

只能更新 Project A 范围 Memory。

---

## Scenario K — Duplicate Feedback Idempotency

同一个 feedback_id 重放两次。

Expected：

```text
score only changes once
```

---

## Scenario L — USED without IN_CONTEXT

非法 usage feedback：

```text
memory never selected/in-context
→ report USED
```

Expected：

默认拒绝或降级为 untrusted feedback。

---

# 12. Stage 3 测试层级

## Unit

- Activation USED
- Feedback attribution
- Utility updater
- Stability updater
- Evolution rules
- Idempotency

## Component

- Retrieval → USED
- USED → Feedback
- Feedback → Score Update
- Score → Evolution

## Scenario

A-L。

## Regression

必须重新验证：

- Stage 1 Formation
- Stage 2 Retrieval
- Scope isolation
- Forget
- Safety
- Legacy Retrieval

---

# 13. Stage 3 Observability

每一次 feedback 应能够回答：

```text
哪条 Memory？
哪个 Retrieval？
是否 USED？
什么 Outcome？
为什么归因给它？
utility/stability 从多少变成多少？
是否触发 Evolution？
```

建议至少记录：

- feedback_id
- retrieval_id
- memory_id
- usage status
- feedback type
- attribution confidence
- old utility
- new utility
- old stability
- new stability
- old evolution state
- new evolution state
- reason
- timestamp

不要求 Stage 3 重做 Dashboard。

---

# 14. Stage 3 Safety / Scope DoD

Feedback 与 Evolution 必须继续遵守：

```text
tenant
user
project
task
session
```

禁止：

```text
tenant A feedback
→ update tenant B memory
```

禁止：

```text
project A feedback
→ update project B project-scoped memory
```

必须增加专门测试。

---

# 15. Stage 3 Definition of Done

Stage 3 只有满足以下条件才可以声明 DONE。

## Activation

- [ ] RECALLED / SELECTED / IN_CONTEXT / USED 四态真实工作。
- [ ] USED 与 retrieval_id / memory_id 绑定。
- [ ] USED feedback 幂等。
- [ ] 非法 USED 有明确处理。

## Feedback

- [ ] Explicit Positive 可记录。
- [ ] Explicit Negative 可记录。
- [ ] Task Success 可记录。
- [ ] Task Failure 可记录。
- [ ] Feedback Attribution 存在。
- [ ] 多 Memory 场景采用保守 attribution。
- [ ] IN_CONTEXT but not USED 不参与强 feedback。

## Utility / Stability

- [ ] Positive attributed feedback 可提升 utility。
- [ ] Negative attributed feedback 可降低 utility。
- [ ] Stability 可根据跨 Episode 确认变化。
- [ ] score 有上下界。
- [ ] duplicate feedback 不重复更新。
- [ ] Recall frequency 不直接提高 utility。

## Evolution

- [ ] ACTIVE / DORMANT 真实可演化。
- [ ] DORMANT 可恢复为 ACTIVE。
- [ ] SUPERSEDED 需要 replacement evidence。
- [ ] Negative feedback 不直接 hard delete。
- [ ] Forget 后不可被 feedback 恢复。
- [ ] Evolution 有 audit trail。

## Scope / Safety

- [ ] Cross-user feedback isolation PASS。
- [ ] Cross-project feedback isolation PASS。
- [ ] Cross-tenant feedback isolation PASS。
- [ ] Forget protection PASS。
- [ ] Safety / quarantine 不被绕过。

## Scenario

- [ ] Scenario A-L 关键路径真实执行。
- [ ] 核心 Scenario 无 module-level skip。
- [ ] Stage 1 regression 无新增失败。
- [ ] Stage 2 regression 无新增失败。
- [ ] Legacy Retrieval 无新增关键回归。

---

# 16. 不属于 Stage 3 DoD 的事项

以下问题不阻塞 Stage 3 完成：

- Channel 并行性能优化
- live Milvus / FAISS 全量压测
- 最终 Benchmark 排名
- vNext 全量 cutover
- Learning-to-Rank
- RL / bandit
- LLM attribution model
- Dashboard 重做

这些进入 Stage 4 或以后。

---

# 17. 修改预算

单个 Batch 原则上：

```text
≤ 8 个核心源码文件
```

如果必须扩大：

1. 先解释原因。
2. 判断是不是现有架构接口缺口。
3. 优先拆 Batch。
4. 不直接扩散修改。

---

# 18. Codex 新会话启动提示词

```text
你正在执行 MemoryHub vNext Stage 3 — Feedback 闭环。

开始前必须完整阅读：

1. docs/vnext/VNEXT_PLAN.md
2. docs/vnext/stages/stage3-feedback.md
3. docs/vnext/PROGRESS.md

只针对当前 Batch 执行 Codebase Reconnaissance。

重点确认：

- 当前 Activation 状态
- feedback_service
- UtilityFeedbackShadow
- evolution_service
- Retrieval Log
- Agent / MCP usage feedback 入口
- Candidate / Authority score 字段
- scope / idempotency / audit
- 当前相关测试

输出：

1. 当前真实调用链
2. 已存在可复用组件
3. 当前缺口
4. 最小修改范围
5. 当前 Batch 不会修改哪些模块
6. 测试计划

完成分析后 STOP。

不要自动修改代码。
```

---

# 19. Codex Batch 执行提示词

```text
按照刚才确认的计划执行当前 Stage 3 Batch。

执行约束：

1. 只处理当前 Batch。
2. 不提前执行后续 Batch。
3. 不进入 Stage 4。
4. 不修改 Stage 1 Formation 主设计。
5. 不修改 Stage 2 Retrieval 主架构。
6. 优先复用 Activation / Feedback / Evolution 现有组件。
7. 不建立平行 Feedback Framework。
8. 不把 recall 直接等同 utility。
9. 不把 IN_CONTEXT 直接等同 USED。
10. 不把 TASK_FAILURE 直接等同 memory negative。
11. 不允许一次 negative feedback 直接 hard delete。
12. 不允许 feedback 绕过 scope / forget / safety。
13. 同一 feedback 必须幂等。
14. 单个 Batch 原则上修改不超过 8 个核心源码文件。
15. SKIP 不计 PASS。
16. 不通过降低断言或 mock-only 掩盖问题。
17. 完成当前Batch后，确认无误提交git

完成后必须输出：

- Changes
- Files Touched
- Behavior Before
- Behavior After
- Tests
- Exact PASS / FAIL / SKIP counts
- Evidence
- Feedback Attribution Evidence
- Score Update Evidence
- Scope Verification
- Regression
- Remaining Risks
- Next Batch Notes

然后更新：

docs/vnext/PROGRESS.md

最后 STOP。

不要自动进入下一个 Batch。
```

---

# 20. PROGRESS.md Stage 3 建议结构

```text
## Stage 3 — Feedback 闭环

Status:
IN PROGRESS
```

维护：

| Batch | 名称 | 状态 |
|---|---|---|
| Batch 1 | Activation Completion — USED | NOT STARTED |
| Batch 2 | Feedback Event & Attribution | NOT STARTED |
| Batch 3 | Utility / Stability Update | NOT STARTED |
| Batch 4 | Memory Evolution & Safeguards | NOT STARTED |
| Batch 5 | Feedback Scenario Tests | NOT STARTED |

每个 Batch 必须记录：

- Reconnaissance Findings
- Changes
- Files Touched
- Tests
- PASS / FAIL / SKIP
- Evidence
- Regression
- Remaining Risks
- Next Batch Notes

---

# 21. Stage 3 完成后的目标状态

Stage 3 完成后，vNext 应达到：

```text
          Formation
             ↓
          Authority
             ↓
          Retrieval
             ↓
          Context
             ↓
            Agent
             ↓
          Usage Signal
             ↓
            USED
             ↓
           Outcome
             ↓
        Attribution
             ↓
   Utility / Stability
             ↓
          Evolution
             ↓
        Better Memory
```

此时才进入 Stage 4：

```text
Evaluation
→ Legacy vs vNext
→ Shadow
→ Canary
→ Cutover
```
