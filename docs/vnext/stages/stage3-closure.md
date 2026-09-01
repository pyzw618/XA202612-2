# Stage 3 Closure — Feedback Correctness 收口与进入 Stage 4 前置修复

## 1. 文档定位

本阶段不是新的功能阶段，也不是 Stage 4 的提前实现。

它的唯一目标是：

> 对 Stage 3 Final Review 中已经明确暴露的问题进行最小范围收口，使 Feedback 闭环达到“归因正确、使用证据可信、幂等可靠、Evolution 语义正确、Scenario 真实覆盖”的状态。

当前已经成立的 Stage 3 主体链路继续保持：

```text
Retrieval
  ↓
RECALLED
  ↓
SELECTED
  ↓
IN_CONTEXT
  ↓
USED
  ↓
Feedback
  ↓
Attribution
  ↓
Utility / Stability
  ↓
Evolution
```

本阶段不重新设计 Feedback Architecture。

只修复：

```text
Attribution correctness
Usage evidence correctness
Durable idempotency
Evolution correctness
Scenario completeness
Regression completeness
```

---

## 2. 当前 Review 结论

Stage 3 Final Review 当前结论：

```text
NOT READY
```

当前主链路已经接通，但存在以下明确问题。

### P1

1. `TASK_FAILURE` 会对非 Memory 原因失败错误执行负反馈。
2. Evolution 使用反馈信号而不是更新后的真实 utility / stability 判断状态。
3. Feedback 幂等仅存在于进程内，服务重启后重复反馈会再次计分。

### P2

4. `USED` 没有强制校验 `IN_CONTEXT`。
5. Agent `/step` 在未提供 `used_memory_ids` 时自动把前 3 条 Memory 标为 USED。
6. `usage_source` / `confidence` / `retrieval_id` 等 Usage Evidence 没有完整保存。
7. Explicit Correction Scenario 没有真正覆盖 conflict evidence 与 replacement/new Candidate。
8. Single Used Success Scenario 没有真正使用 `TASK_SUCCESS`。
9. Repeated Positive Scenario 没有真正覆盖跨 Episode 多次成功。
10. Illegal USED Scenario 没有覆盖 selected-but-not-in-context。
11. Evolution lineage/audit 异常存在静默吞掉风险。
12. SUPERSEDED replacement evidence 尚未真实验证。
13. Stage 2 Closure 缺少独立的 `READY FOR STAGE 3` 最终结论记录。
14. 部分 Safety / Forget regression 受 Windows `tmp_path` ACL 影响，未完整形成真实测试证据。
15. Stage 2 regression 存在 `recall=0.8333` 的历史失败，需要确认是否由 Stage 3 引入。

---

## 3. Closure 原则

### 3.1 只修 Review 已确认的问题

禁止在 Closure 中：

- 重写 Feedback Framework。
- 重写 Retrieval。
- 重写 Formation。
- 引入 RL / bandit / Learning-to-Rank。
- 引入 LLM Attribution。
- 重做 Dashboard。
- 切换默认 vNext rollout。
- 做 Stage 4 Benchmark/Cutover。
- 顺手进行性能重构。

### 3.2 正确性优先

执行顺序固定：

```text
Attribution Correctness
  ↓
Usage Evidence
  ↓
Durable Idempotency
  ↓
Evolution Correctness
  ↓
Scenario Verification
  ↓
Regression
```

### 3.3 宁可不更新，也不要错更新

对于无法可靠归因的反馈：

```text
unknown / weak attribution
```

优先：

```text
no score update
```

而不是猜测性更新。

### 3.4 SKIP 不等于 PASS

关键 Scenario：

```text
PASS = 真正执行并通过
SKIP ≠ PASS
XFAIL ≠ PASS
NOT RUN ≠ PASS
ERROR ≠ PASS
```

### 3.5 不允许通过测试降级掩盖问题

禁止：

- 删除失败测试。
- 把失败测试改成 skip。
- 放宽断言适配错误行为。
- 用 mock-only 替代本应真实验证的链路。
- 因平台 ACL 问题直接标记 PASS。

---

## 4. Closure Batch 划分

本阶段拆成 4 个 Fix Batch：

```text
Fix Batch 1
Attribution Correctness

Fix Batch 2
Durable Feedback & Usage Evidence

Fix Batch 3
Evolution Correctness & Replacement Evidence

Fix Batch 4
Scenario / Regression / Final Closure Verification
```

执行顺序固定。

每个 Batch 完成后：

1. 运行对应测试。
2. 更新 `docs/vnext/PROGRESS.md`。
3. 输出 PASS / FAIL / SKIP / ERROR。
4. 输出 Evidence。
5. STOP。
6. 不自动执行下一个 Batch。

---

# Fix Batch 1 — Attribution Correctness

## 5. Objective

修复当前最严重的反馈归因问题：

```text
TASK_FAILURE
+
USED memory
↓
无条件 negative feedback
```

必须改成 outcome-aware attribution。

---

## 6. Reconnaissance

修改前重点检查：

- `memoryhub/application/feedback_service.py`
- Feedback Event / Feedback Type
- outcome 字段
- Attribution logic
- UtilityFeedbackShadow
- Stage 3 Scenario tests
- Agent / MCP feedback entrypoints

回答：

1. `TASK_FAILURE` 当前在哪转成 utility signal。
2. `outcome` 当前有哪些取值。
3. 是否已有 failure reason / cause / confidence。
4. 是否已有 AttributionResult。
5. Multiple Used Memories 当前如何分配 signal。
6. `TASK_SUCCESS` 是否真实存在独立归因逻辑。
7. Explicit Positive/Negative 与 Task Outcome 是否共用同一条逻辑。

---

## 7. Attribution Rules

### Rule A — Explicit Positive

```text
explicit user confirmation
→ strong positive
```

### Rule B — Explicit Negative / Correction

```text
explicit correction
→ strong negative
```

### Rule C — Task Success + Single Used Memory

如果：

```text
1 条 Memory = USED
+
Task Success
+
无明显其他强原因
```

可：

```text
strong / medium positive attribution
```

### Rule D — Task Success + Multiple Used Memories

多个 Memory：

```text
default = weak attribution
```

只有明确 attribution evidence 时才允许 stronger update。

### Rule E — Task Failure caused by Memory

例如：

```text
错误 Procedure
→ Agent 执行
→ 任务失败
```

才允许：

```text
strong negative
```

### Rule F — Task Failure unrelated to Memory

例如：

```text
TIMEOUT
NETWORK_ERROR
RATE_LIMIT
EXTERNAL_SERVICE_FAILURE
PERMISSION_DENIED
INFRA_FAILURE
```

默认：

```text
neutral
```

不得惩罚 Memory。

### Rule G — Unknown Failure

无法判断：

```text
weak / no update
```

禁止默认 negative。

---

## 8. Outcome Classification

优先复用现有字段。

如果需要新增分类，最小范围支持：

```text
MEMORY_CAUSED
EXTERNAL_FAILURE
UNKNOWN
```

或等价结构。

不要创建复杂 Failure Ontology。

---

## 9. Acceptance Criteria

1. `TASK_FAILURE + TIMEOUT` 不降低 utility / stability。
2. `TASK_FAILURE + NETWORK_ERROR` 不降低 utility / stability。
3. 明确 memory-caused failure 可以降低分数。
4. UNKNOWN failure 默认不做强 negative。
5. Single Used Success 使用真实 `TASK_SUCCESS` 测试。
6. Multiple Used Memories 保守归因。
7. IN_CONTEXT but not USED 不参与 Task Outcome 强归因。
8. Explicit Positive/Negative 原逻辑不回归。

---

# Fix Batch 2 — Durable Feedback & Usage Evidence

## 10. Objective

解决两个核心问题：

```text
Feedback idempotency
```

和：

```text
USED evidence trustworthiness
```

---

## 11. Part A — Durable Feedback Idempotency

### 11.1 当前问题

当前幂等基于：

```text
in-memory set
```

只能保证单进程。

服务重启后：

```text
feedback_id 重放
→ 再次更新 score
```

### 11.2 Target Design

优先复用已有：

```text
IdempotencyRecord
```

或当前项目已有持久化幂等基础设施。

目标：

```text
feedback_id
  ↓
persistent idempotency check
  ↓
already processed?
├─ yes → return previous result / no-op
└─ no
    ↓
  feedback processing
    ↓
  score update
    ↓
  evolution
    ↓
  audit
    ↓
  persist idempotency
```

### 11.3 Transaction Boundary

优先保证：

```text
score update
+
evolution
+
idempotency mark
```

不会出现明显：

```text
score updated
但 idempotency 未记录
```

导致重试重复计分。

如果当前数据库事务架构无法一次完成：

必须说明并采用最小可恢复策略。

### 11.4 Acceptance Criteria

1. 同一 feedback_id 同进程重复提交只更新一次。
2. Service 重建后再次提交仍只更新一次。
3. 进程重启模拟测试 PASS。
4. 多线程/并发重复提交至少有基本保护。
5. 已处理 feedback 可返回已有结果或 no-op。
6. 不建立新的纯内存幂等集合作为最终方案。

---

## 12. Part B — IN_CONTEXT → USED 强校验

### 12.1 Objective

正常状态必须满足：

```text
SELECTED
  ↓
IN_CONTEXT
  ↓
USED
```

禁止：

```text
SELECTED
↓
USED
```

直接跳级。

### 12.2 Enforcement Layer

不能只在 API 层校验。

至少在：

```text
Service / Repository boundary
```

有最终防线。

`mark_used()` 或等价入口必须验证：

```text
included_in_context == true
```

除非存在显式 trusted override，且有审计。

### 12.3 Agent `/step` Auto USED

当前：

```text
未提供 used_memory_ids
→ 自动前 3 条标记 USED
```

必须移除或降级。

目标：

```text
no usage evidence
→ 保持 IN_CONTEXT
```

而不是猜测 USED。

---

## 13. Part C — Usage Evidence Persistence

### 13.1 Minimum Fields

必须可以恢复：

- retrieval_id
- memory_id
- usage_source
- confidence
- used_at
- tenant_id
- user_id
- project_id
- task_id
- session_id
- attribution_method

如果当前 `AgentUsageTrace` 可扩展：

优先复用。

### 13.2 Acceptance Criteria

1. `usage_source` 真实持久化。
2. `confidence` 真实持久化。
3. `retrieval_id` 真实持久化。
4. selected-but-not-context 无法正常标记 USED。
5. no `used_memory_ids` 不再自动 Top-3 USED。
6. explicit used_memory_ids 正常工作。
7. Cross-tenant / cross-user / cross-project usage update 被拒绝。
8. duplicate usage feedback 幂等。

---

# Fix Batch 3 — Evolution Correctness & Replacement Evidence

## 14. Objective

修复 Evolution 状态判断错误，并补齐 Explicit Correction → Conflict / Replacement 流程。

---

## 15. Part A — Evolution Reads Current State

### 15.1 当前问题

当前类似：

```text
feedback utility_signal
```

被直接用于：

```text
Dormant / Review 判断
```

而不是使用更新后的：

```text
current.utility
current.stability
```

### 15.2 Target Order

严格顺序：

```text
Feedback
  ↓
Attribution
  ↓
Score Update
  ↓
Persist Current Score
  ↓
Evolution reads CURRENT memory state
  ↓
State Transition
```

禁止：

```text
Feedback Signal
↓
直接判断 Evolution
```

### 15.3 状态语义

优先复用现有：

```text
ACTIVE
DORMANT
REVIEW
SUPERSEDED
ARCHIVED
DELETED
```

如果 `REVIEW` 不在 EvolutionStatus：

使用现有最接近状态或 review flag。

禁止为 Closure 重构整个状态机。

### 15.4 Acceptance Criteria

例如：

```text
old utility = 0.90
old stability = 0.25
negative feedback
updated = 0.75 / 0.10
```

Evolution 必须根据：

```text
0.75 / 0.10
```

判断。

不能根据负向 signal 自身直接判 DORMANT。

---

## 16. Part B — Lineage / Audit Reliability

当前如果 lineage 写入异常被静默吞掉：

必须至少：

- 明确记录 error
- trace 可见
- 不伪装成完整成功

优先保持主业务可用，但不能 silent failure。

---

## 17. Part C — Explicit Correction / Replacement

### 17.1 Target Flow

当用户明确纠正：

```text
Old Memory:
项目数据库 = MySQL

User:
“不对，现在是 PostgreSQL”
```

目标：

```text
Explicit Correction
  ↓
Old Memory negative feedback
  ↓
Conflict Evidence
  ↓
Old Memory REVIEW / replacement pending
  ↓
New Fact
  ↓
正常 Formation / Candidate 流程
```

禁止直接：

```text
overwrite old memory
```

也禁止：

```text
hard delete old memory
```

### 17.2 SUPERSEDED

必须有：

```text
replacement evidence
```

或等价：

```text
replacement_memory_id
lineage
conflict resolution
```

才能：

```text
SUPERSEDED
```

### 17.3 Acceptance Criteria

1. Explicit Correction 会生成可追溯 conflict evidence。
2. 新事实进入 Formation / Candidate 正常流程。
3. Old Memory 不直接 hard delete。
4. SUPERSEDED 需要 replacement evidence。
5. replacement lineage 可追踪。
6. DORMANT → ACTIVE 仍保持可恢复。
7. Forget 后不可通过 correction / feedback 复活。

---

# Fix Batch 4 — Scenario / Regression / Final Closure Verification

## 18. Objective

把 Stage 3 Review 中未真实覆盖或语义不完整的 Scenario 全部补齐，并形成可进入 Stage 4 的证据。

---

## 19. 必须重做的 Scenario

### Scenario B — Explicit Correction

必须真实验证：

- old memory REVIEW / equivalent
- conflict evidence
- replacement evidence
- new Candidate / Formation

### Scenario C — Single Used Success

必须真正提交：

```text
TASK_SUCCESS
```

而不是 Explicit Positive。

Expected：

```text
single USED memory
→ positive attribution
→ utility small increase
```

### Scenario E — Unrelated Failure

必须真实：

```text
TASK_FAILURE
outcome = TIMEOUT / NETWORK_ERROR
```

Expected：

```text
no negative score update
```

### Scenario G — Repeated Positive Use

必须跨：

```text
Episode 1
Episode 2
Episode 3
```

真实多次：

```text
USED
+
TASK_SUCCESS
```

Expected：

```text
stability gradually increases
```

### Scenario K — Restart Idempotency

必须：

```text
feedback_id = f1
→ process
→ recreate service / simulate restart
→ submit f1 again
```

Expected：

```text
score unchanged after second submit
```

### Scenario L — Illegal USED

必须覆盖：

```text
SELECTED
included_in_context = false
```

然后：

```text
mark USED
```

Expected：

```text
reject / untrusted
```

---

## 20. Stage 2 Closure 前置证据补齐

在 Stage 3 Closure 最终 Review 前：

必须独立执行一次：

```text
Stage 2 Closure Final Review
```

并获得：

```text
READY FOR STAGE 3
```

如果仍为：

```text
NOT READY
```

Stage 3 Closure 不允许宣布完成。

---

## 21. Stage 2 Recall 0.8333 处理原则

当前历史失败：

```text
test_recall_is_perfect_for_expected_memories
actual = 0.8333
```

必须判断。

### Case A — Stage 3 引入

如果：

```text
Stage 2 Closure 时 PASS
Stage 3 后 FAIL
```

则：

```text
Stage 3 regression
→ 必须修
```

### Case B — Stage 2 已存在

如果 Stage 3 前已失败：

记录为既有风险，不在 Closure 擅自扩大范围。

必须提供证据。

---

## 22. Windows tmp_path ACL

Safety / Forget 测试如因 Windows ACL：

```text
setup error
```

必须：

1. 使用项目可控 temp directory。
2. 或明确配置 pytest temp root。
3. 不修改业务代码绕过 ACL。
4. 重新执行真实测试。

最终 Closure Review 不接受大量：

```text
ERROR
```

作为“环境原因所以算通过”。

---

## 23. Closure Definition of Done

Stage 3 Closure 只有全部关键条件满足才可声明 DONE。

### Attribution

- [ ] TASK_FAILURE + TIMEOUT 不惩罚 Memory。
- [ ] TASK_FAILURE + NETWORK_ERROR 不惩罚 Memory。
- [ ] Memory-caused failure 可以 negative attribution。
- [ ] Unknown failure 不默认强 negative。
- [ ] Single Used TASK_SUCCESS 真实通过。
- [ ] Multiple Used Memories 保守归因。
- [ ] IN_CONTEXT but not USED 不参与强反馈。

### Idempotency

- [ ] feedback 幂等持久化。
- [ ] service recreate / restart 后 replay 不重复更新。
- [ ] duplicate feedback 并发路径有基本保护。
- [ ] 不依赖纯内存 set 作为最终幂等。

### Usage Evidence

- [ ] SELECTED-but-not-context 无法正常 USED。
- [ ] `mark_used()` 有底层 IN_CONTEXT 防线。
- [ ] Agent 不再默认 Top-3 auto USED。
- [ ] usage_source 持久化。
- [ ] confidence 持久化。
- [ ] retrieval_id 持久化。
- [ ] usage scope 可追溯。

### Evolution

- [ ] Evolution 使用更新后的 current utility / stability。
- [ ] ACTIVE / DORMANT / REVIEW 语义正确。
- [ ] DORMANT → ACTIVE 仍通过。
- [ ] SUPERSEDED 需要 replacement evidence。
- [ ] lineage/audit 异常不静默吞掉。
- [ ] Negative feedback 不直接 hard delete。
- [ ] Forget 后不可复活。

### Scenario

- [ ] B Explicit Correction 完整 PASS。
- [ ] C Single Used Success 真实 TASK_SUCCESS PASS。
- [ ] E Unrelated Failure PASS。
- [ ] G 跨 Episode repeated positive PASS。
- [ ] K restart idempotency PASS。
- [ ] L selected-but-not-context PASS。
- [ ] A-L 核心 Scenario 无关键 SKIP。

### Regression

- [ ] Stage 1 regression 无新增失败。
- [ ] Stage 2 regression 无 Stage 3 新增失败。
- [ ] Stage 2 Closure Final Review = READY FOR STAGE 3。
- [ ] Stage 3 targeted tests 无关键失败。
- [ ] Scope isolation PASS。
- [ ] Legacy Retrieval 无新增关键回归。
- [ ] Forget / Safety 关键测试真实执行。

---

## 24. 不属于 Closure DoD 的事项

以下问题不阻塞进入 Stage 4：

- live Milvus / FAISS 全量生产压测
- Channel 并行
- LLM Attribution
- Learning-to-Rank
- RL / bandit
- Dashboard 重构
- 最终比赛 Benchmark
- vNext 默认 cutover

这些进入 Stage 4。

---

## 25. 修改预算

单个 Fix Batch 原则上：

```text
≤ 8 个核心源码文件
```

如果必须扩大：

1. 先说明原因。
2. 判断是否是已有 Contract 缺口。
3. 优先拆 Batch。
4. 禁止顺手重构无关模块。

---

## 26. Codex 新会话启动提示词

```text
你正在执行 MemoryHub vNext Stage 3 Closure。

开始前必须完整阅读：

1. docs/vnext/VNEXT_PLAN.md
2. docs/vnext/stages/stage3-feedback.md
3. docs/vnext/stages/stage3-closure.md
4. docs/vnext/PROGRESS.md
5. Stage 3 Final Review
6. Stage 2 Closure Review / Final Review

先不要修改代码。

首先针对当前 Fix Batch 执行 Codebase Reconnaissance。

要求：

- 验证 Review 指出的问题是否仍存在
- 找到真实调用链
- 找到真实失败测试
- 确认已有可复用组件
- 判断是否需要 Repository / Schema / Contract 变化
- 给出最小修改范围
- 明确当前 Batch 不修改哪些模块
- 给出测试计划

如果 Review 与当前代码不一致：
以当前代码和真实测试为准，并说明差异。

完成分析后 STOP。

不要自动修改代码。
```

---

## 27. Codex Fix Batch 执行提示词

```text
按照刚才确认的计划执行当前 Stage 3 Closure Fix Batch。

执行约束：

1. 只修当前 Fix Batch。
2. 不提前执行后续 Fix Batch。
3. 不进入 Stage 4。
4. 不重写 Feedback Framework。
5. 不重写 Retrieval / Formation。
6. 不通过 skip / xfail 掩盖问题。
7. 不放宽断言适配错误行为。
8. 优先修真实逻辑，再修测试。
9. Feedback 无法可靠归因时优先 no-op，而不是猜测更新。
10. TASK_FAILURE 不等于 memory negative。
11. IN_CONTEXT 不等于 USED。
12. 不允许 Top-N context 自动猜测 USED。
13. Feedback 幂等必须跨 service restart。
14. Evolution 必须读取更新后的 current state。
15. Negative feedback 不允许直接 hard delete。
16. Scope / Forget / Safety 不允许被绕过。
17. 单个 Fix Batch 原则上修改不超过 8 个核心源码文件。
18. SKIP 不计 PASS。

完成后必须输出：

- Changes
- Files Touched
- Behavior Before
- Behavior After
- Tests
- Exact PASS / FAIL / SKIP / ERROR counts
- Attribution Evidence
- Idempotency Evidence
- Usage Evidence
- Evolution Evidence
- Scope / Safety Verification
- Regression
- Remaining Risks
- Next Fix Batch Notes

然后更新：

docs/vnext/PROGRESS.md

最后 STOP。

不要自动进入下一个 Fix Batch。
```

---

## 28. PROGRESS.md 更新要求

新增：

```text
## Stage 3 Closure

Status:
IN PROGRESS
```

维护：

| Fix Batch | 名称 | 状态 |
|---|---|---|
| Fix 1 | Attribution Correctness | NOT STARTED |
| Fix 2 | Durable Feedback & Usage Evidence | NOT STARTED |
| Fix 3 | Evolution Correctness & Replacement Evidence | NOT STARTED |
| Fix 4 | Scenario / Regression / Final Verification | NOT STARTED |

状态：

```text
NOT STARTED
IN PROGRESS
BLOCKED
DONE
```

每个 Batch 记录：

- Reconnaissance Findings
- Changes
- Files Touched
- Tests
- PASS / FAIL / SKIP / ERROR
- Evidence
- Regression
- Remaining Risks
- Next Batch Notes

---

## 29. Stage 3 Closure Final Review

所有 Fix Batch 完成后：

必须新开独立 Codex 会话执行只读 Review。

禁止最后一个 Fix Batch 会话自行宣布：

```text
READY FOR STAGE 4
```

---

## 30. Final Review 必查项

必须重新验证：

1. `TASK_FAILURE + TIMEOUT` 是否 neutral。
2. `TASK_FAILURE + memory-caused` 是否 negative。
3. Single Used `TASK_SUCCESS` 是否 positive。
4. Multiple Used 是否保守归因。
5. feedback restart idempotency。
6. SELECTED-but-not-context 是否无法 USED。
7. Agent 是否还存在 Top-3 auto USED。
8. usage_source/confidence/retrieval_id 是否可追溯。
9. Evolution 是否读取 current utility/stability。
10. Explicit Correction 是否有 conflict/replacement evidence。
11. SUPERSEDED 是否需要 replacement evidence。
12. Forget 后是否不可复活。
13. Stage 2 Closure 是否已有 READY FOR STAGE 3。
14. Stage 1 / Stage 2 regression。
15. Safety / Forget 测试是否真实执行。
16. Scenario A-L 是否真实覆盖。

---

## 31. Final Review Prompt

```text
对 MemoryHub vNext Stage 3 Closure 做最终独立 Review。

先阅读：

- docs/vnext/VNEXT_PLAN.md
- docs/vnext/stages/stage3-feedback.md
- docs/vnext/stages/stage3-closure.md
- docs/vnext/PROGRESS.md
- Stage 3 Final Review
- Stage 2 Closure Final Review

不要修改任何代码。

不要相信 PROGRESS.md 中的 DONE。

基于真实代码、调用链和测试重新验证：

1. Attribution correctness
2. TASK_FAILURE outcome-awareness
3. Single Used TASK_SUCCESS
4. Multiple-memory attribution
5. Durable feedback idempotency
6. Restart replay protection
7. IN_CONTEXT → USED enforcement
8. Auto Top-N USED removal
9. Usage evidence persistence
10. Evolution current-state correctness
11. Explicit correction conflict/replacement
12. SUPERSEDED replacement evidence
13. Forget protection
14. Cross-tenant/user/project isolation
15. Stage 1 regression
16. Stage 2 regression
17. Safety / Forget regression
18. Scenario A-L
19. Stage 2 Closure READY FOR STAGE 3 evidence

必须明确区分：

PASS
FAIL
PARTIAL
SKIP
NOT RUN
ERROR

SKIP / NOT RUN / ERROR 不算 PASS。

最终输出：

# Stage 3 Closure Final Review

## 1. Final Verdict

READY FOR STAGE 4
或
NOT READY

## 2. Closure DoD
逐条 PASS / FAIL / PARTIAL

## 3. Real Feedback Architecture

## 4. Attribution Verification

## 5. Durable Idempotency Verification

## 6. Usage Evidence Verification

## 7. Evolution Verification

## 8. Conflict / Replacement Verification

## 9. Scope / Safety / Forget Verification

## 10. Scenario A-L Results

## 11. Stage 1 / Stage 2 Regression

## 12. Test Evidence
精确：
passed / failed / skipped / errors / deselected

## 13. Remaining Risks

## 14. Final Recommendation

不要修改代码。
```

---

## 32. 进入 Stage 4 的硬条件

只有 Final Review 输出：

```text
READY FOR STAGE 4
```

才允许进入：

```text
Stage 4 — Evaluation & Cutover
```

否则继续留在 Stage 3 Closure。

原因：

```text
错误 Feedback
  ↓
错误 Utility / Stability
  ↓
错误 Evolution
  ↓
Stage 4 Shadow / Canary
  ↓
错误 Memory 被规模化放大
```

因此：

> Feedback correctness、durable idempotency 和 evolution semantics 必须在 Cutover 前完成。
