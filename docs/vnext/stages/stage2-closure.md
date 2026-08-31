# stage2-closure.md

# Stage 2 Closure — Retrieval 收口与进入 Stage 3 前置修复

## 1. 文档定位

本阶段不是新的功能阶段，也不是 Stage 3 的提前实现。

它的唯一目标是：

> 对 Stage 2 Completion Review 中已经明确暴露的问题进行最小范围收口，使 Stage 2 达到可验证、可回归、可进入 Stage 3 的状态。

本阶段不重新设计 Retrieval Architecture。

当前已经成立的 Stage 2 主体架构继续保持：

```text
Request
  ↓
RetrievalService
  ↓
IntentRouter
  ↓
RetrievalPlanner
  ↓
Channel Executors
   ├─ Working
   ├─ Episode
   ├─ Authority
   ├─ Keyword
   ├─ Metadata
   └─ Vector
  ↓
Fusion
  ↓
Rerank
  ↓
ScopeResolver
  ↓
BudgetManager
  ↓
ContextPayload
  ↓
Activation / Retrieval Log
```

本阶段只修复：

```text
Scope correctness
Regression
Verification
Budget correctness
Intent usability
Observability completeness
```

---

# 2. 当前 Review 结论

Stage 2 Completion Review 当前结论：

```text
NOT READY
```

当前主体架构已经基本完成，但存在以下阻塞项：

1. Working / Episode fallback 存在跨项目 Scope Leak。
2. Agent `/step` 路径存在 Scope 信息丢失。
3. Stage 1 Formation 回归存在失败。
4. Batch 5 真实 Scenario 实际被 skip，没有形成有效 E2E 验证。
5. `rank-bm25` / `faiss-cpu` / `jieba` 等测试依赖未满足。
6. Context Budget 不是严格硬上限。
7. IntentRouter 对常见中文自然语言覆盖不足。
8. Retrieval Log 未记录最终 selected memory IDs。
9. Multi-channel 当前串行执行，但此项暂不作为 Closure 阻塞项。

---

# 3. Closure 原则

## 3.1 只修 Review 已经确认的问题

禁止在 Closure 中：

- 新增新的 Memory Layer。
- 重构整个 Retrieval Framework。
- 重写 Planner。
- 重写 Fusion 算法。
- 提前实现 USED / Feedback / Evolution。
- 切换默认 `vnext.mode`。
- 删除 Legacy Retrieval。
- 扩大 Candidate Promotion 设计。
- 做无关性能优化。

---

## 3.2 正确性优先于性能

当前顺序：

```text
Scope Correctness
  ↓
Regression
  ↓
Scenario Verification
  ↓
Budget Correctness
  ↓
Intent Usability
  ↓
Observability
  ↓
Performance
```

Channel 并行暂不在本阶段处理。

---

## 3.3 SKIP 不等于 PASS

从本阶段开始：

```text
PASS = 真正执行并通过
SKIP ≠ PASS
XFAIL ≠ PASS
NOT RUN ≠ PASS
```

关键 Scenario 如果因为依赖缺失而 skip：

```text
Closure Status = BLOCKED
```

不得声明 DONE。

---

## 3.4 不允许通过放宽测试掩盖问题

禁止：

- 删除测试。
- 将失败测试改成 skip。
- 放宽断言以适配错误行为。
- 用 mock 替代本应真实验证的 E2E。
- 因环境问题直接标记 PASS。

---

# 4. Closure Batch 划分

本阶段拆成 4 个 Fix Batch：

```text
Fix Batch 1
Scope Isolation & Agent Scope Propagation

Fix Batch 2
Stage 1 Formation Regression Recovery

Fix Batch 3
Test Environment & Real Scenario Verification

Fix Batch 4
Budget / Intent / Retrieval Log Closure
```

执行顺序固定。

每个 Batch 完成后：

1. 运行对应测试。
2. 更新 `docs/vnext/PROGRESS.md`。
3. 输出 Evidence。
4. STOP。
5. 不自动执行下一个 Batch。

---

# 5. Fix Batch 1 — Scope Isolation & Agent Scope Propagation

## 5.1 Objective

彻底解决当前 Review 中已经复现的 Scope 问题：

```text
Project B Request
↓
Working / Episode fallback
↓
错误返回 Project A Memory
```

以及：

```text
Agent /step
↓
构造 vNext Request
↓
task / session / project / scene 信息丢失
```

---

## 5.2 Reconnaissance

修改前重点检查：

- `memoryhub/adapter/agent_api.py`
- `memoryhub/adapter/retrieval_executor.py`
- `memoryhub/adapter/vnext_schemas.py`
- `memoryhub/storage/vnext_repositories.py`
- Working State Schema / Model
- Episode Schema / Model
- ScopeResolver
- 相关测试

回答：

1. WorkingState 当前是否存储 `project_id`。
2. Episode 当前是否存储 `project_id`。
3. `task_id` 与 `project_id` 当前关系是否稳定。
4. 无 task_id 时 `list_recent()` 如何 fallback。
5. Agent `/step` 当前丢失哪些 scope 字段。
6. ScopeResolver 能否在结果阶段补救结构化 Working / Episode project leak。
7. 是否需要最小 Schema Migration。
8. 是否存在不用改 Schema 就能可靠恢复 project scope 的现有关系。

---

## 5.3 Scope 目标

至少保证以下隔离：

```text
tenant
user
project
task
session
```

优先级：

```text
task exact match
  ↓
session scoped
  ↓
project scoped
  ↓
user scoped
```

禁止无约束地使用：

```text
same user + recent
```

作为 project-scoped query 的 fallback。

---

## 5.4 Storage Strategy

如果当前 Working / Episode 无法可靠恢复 `project_id`：

允许进行**最小 Schema 扩展**。

但必须遵循：

1. 只增加 Closure 必需字段。
2. 不重新设计整个数据模型。
3. Migration 必须兼容已有数据。
4. Repository API 必须同步。
5. InMemory Repository 必须同步。
6. 测试必须覆盖 migration 后路径。

如果可以通过现有 task/session 关系可靠恢复 project：

优先复用，不新增字段。

---

## 5.5 Agent Scope Propagation

Agent `/step` → vNext Request 必须完整保留可用字段。

至少确认：

- tenant_id
- user_id
- project_id
- task_id
- session_id
- scene
- task_type

如果 vNext Request 没有对应字段：

优先使用当前已有最接近 Contract。

不要创建大量重复字段。

---

## 5.6 Acceptance Criteria

### Cross Project

Given：

```text
User A

Project A
  Working: task-a

Project B
  Working: task-b
```

When：

```text
Project B 请求 CURRENT_STATE
```

Then：

```text
只能返回 Project B 范围 Memory
```

不得返回 task-a。

### Cross User

Given：

```text
User A
User B
```

存在冲突 Working / Episode。

Then：

严格隔离。

### Agent Step

Given：

Agent `/step` 具有：

```text
project_id
task_id
session_id
```

Then：

这些字段必须传入 vNext Retrieval。

---

## 5.7 Required Tests

至少：

- Working cross-project isolation
- Episode cross-project isolation
- Working cross-user isolation
- Episode cross-user isolation
- Agent `/step` scope propagation
- no-task fallback behavior
- project fallback behavior

---

## 5.8 Must Not Change

本 Batch 不：

- 修改 Fusion。
- 修改 Budget。
- 修改 IntentRouter。
- 修改 Stage 1 Formation。
- 实现 Feedback。

---

# 6. Fix Batch 2 — Stage 1 Formation Regression Recovery

## 6.1 Objective

恢复 Stage 1 Formation 全量回归。

当前已知问题重点：

```text
CandidateService.stage()
```

向 Repository 传入：

```text
confidence
utility
stability
```

但某些 InMemory Candidate Repository 接口未同步。

---

## 6.2 Reconnaissance

检查：

- `memoryhub/application/candidate_service.py`
- `memoryhub/application/formation_shadow.py`
- Candidate Repository Protocol / Interface
- Real Candidate Repository
- InMemory Candidate Repository
- Formation Evaluation
- Formation Shadow Tests

回答：

1. 正式 Repository 当前 `create()` Contract。
2. InMemory Repository 当前 `create()` Contract。
3. Candidate Domain 字段。
4. 哪一侧是最新 Contract。
5. Stage 2 是否引入过接口变化。
6. 是否还有其他 Test Double 接口漂移。

---

## 6.3 修复原则

必须统一：

```text
Domain Contract
Real Repository
InMemory Repository
Test Double
Service Caller
```

禁止：

```text
try:
    repo.create(new_args)
except TypeError:
    repo.create(old_args)
```

这类兼容补丁。

应恢复明确、统一的接口。

---

## 6.4 Acceptance Criteria

重新执行 Stage 1 Formation 测试。

目标：

```text
0 failed
```

允许合理 skip，但必须说明原因。

如果核心 Formation Scenario 被 skip：

不得视为通过。

---

## 6.5 Required Regression

至少重新运行：

- Formation Shadow
- Formation Eval
- Stage 1 Scenario
- Candidate Service
- Candidate Repository
- candidate-only behavior

---

## 6.6 Additional Check

检查是否存在类似漂移：

```text
Real Repository
≠
InMemory Repository
```

如果同类问题在相邻 Repository 已存在：

允许在本 Batch 内同步修复。

但不得扩展到无关模块。

---

# 7. Fix Batch 3 — Test Environment & Real Scenario Verification

## 7.1 Objective

消除 Stage 2 Review 中“测试文件存在但没有真正运行”的假通过问题。

必须确保：

```text
Batch 5 Scenario
```

真实执行。

---

## 7.2 Environment Dependencies

当前重点确认：

- `rank-bm25`
- `faiss-cpu`
- `jieba`

是否属于：

```text
runtime dependency
optional runtime dependency
test dependency
dev dependency
```

不要直接盲目加入 production requirements。

优先根据实际用途放入：

```text
requirements-dev.txt
```

或项目现有 dependency group。

---

## 7.3 Dependency Policy

如果某 Backend 本身就是 optional：

允许保持 optional。

但测试应该区分：

```text
Unit fallback test
Real backend integration test
```

关键 Stage 2 Scenario 不应因为一个可替代 Channel 的 optional dependency 缺失而全部 module-level skip。

---

## 7.4 Scenario Test Structure

检查：

```text
test_vnext_batch5_retrieval_scenarios.py
```

是否存在：

```text
module-level skip
```

导致：

```text
BM25 unavailable
→ 整个 Stage 2 Scenario 全部不执行
```

如果存在，应调整测试组织。

例如拆分：

```text
core retrieval scenarios
keyword-specific scenarios
vector-specific scenarios
```

让 Working / Episode / Authority / Scope 等 Scenario 不依赖 BM25 才能执行。

---

## 7.5 Required Real Scenarios

必须真实执行：

- Scenario A — Current State
- Scenario B — Task History
- Scenario C — Preference
- Scenario D — Semantic Fact
- Scenario E — Exact Keyword
- Scenario F — Cross Project
- Scenario G — Cross User
- Scenario H — Mixed Intent
- Scenario I — Duplicate Projection
- Scenario J — Context Budget
- Legacy vs vNext Comparison

---

## 7.6 Legacy Regression

重新执行 Legacy Retrieval 测试。

区分：

```text
code regression
environment missing dependency
platform issue
```

不得混在一起。

---

## 7.7 Windows pytest ACL

Retrieval Log 测试当前存在：

```text
pytest temp .lock ACL
```

问题。

本 Batch 需要：

1. 确认是否是环境问题。
2. 尝试使用项目可控 temp dir。
3. 不修改业务逻辑规避 ACL。
4. 确保 Retrieval Log 持久化测试真实运行。

---

## 7.8 Acceptance Criteria

必须至少达到：

```text
Batch 5 core scenarios:
0 skipped due to missing optional dependency
```

如果 Keyword-specific Backend 未安装：

只允许 Keyword-specific test 单独标记环境阻塞。

不能让其他 Scenario 全部 skip。

---

## 7.9 Evidence

输出：

```text
Scenario A: PASS
Scenario B: PASS
...
```

不得只输出：

```text
11 tests collected
```

或：

```text
11 skipped
```

---

# 8. Fix Batch 4 — Budget / Intent / Retrieval Log Closure

本 Batch 只处理三个剩余收口项：

```text
Hard Context Budget
IntentRouter 高频中文
Retrieval Log selected IDs
```

---

# 9. Part A — Hard Context Budget

## 9.1 Objective

确保：

```text
request token budget
```

是实际硬上限。

当前问题：

```text
Working State
hard protected
↓
可能直接突破 budget
```

---

## 9.2 核心原则

```text
hard protected
≠
unlimited tokens
```

正确语义：

```text
hard protected
=
优先保留语义
```

如果内容过长：

```text
structured compression
↓
保留关键字段
↓
满足 budget
```

---

## 9.3 Working Compression Priority

优先保留：

- current_goal
- current_step
- blockers
- pending_steps
- critical constraints
- recent important result

低优先级内容可先裁剪：

- 大量 completed history
- 重复 findings
- 长 tool output
- 非关键 metadata

---

## 9.4 Acceptance Criteria

Given：

```text
budget = 128 tokens
超长 Working State
```

Then：

最终：

```text
actual context <= allowed tolerance
```

建议 tolerance：

```text
<= budget + tokenizer estimation tolerance
```

不得出现明显大幅超限。

---

# 10. Part B — IntentRouter 高频中文覆盖

## 10.1 Objective

让以下高频中文 query 不再依赖 `intent_hint`：

```text
我现在做到哪里了
我现在进展到哪了
当前做到哪一步了

之前这个问题是怎么处理的
之前遇到过类似问题吗
上次是怎么解决的

我一般用 Maven 还是 Gradle
我平时更喜欢用什么
我之前偏好什么

这个项目数据库用什么
项目现在用的是什么数据库
这个项目的技术栈是什么
```

---

## 10.2 Implementation Principle

继续保持：

```text
deterministic first
```

不要为了 Closure 引入 LLM Intent Router。

优先：

- phrase rules
- keyword groups
- normalized Chinese patterns
- small scoring rules

规则必须可解释、可测试。

---

## 10.3 Acceptance Criteria

至少：

```text
CURRENT_STATE
TASK_HISTORY
PREFERENCE
SEMANTIC_FACT
```

四类中文自然问法稳定识别。

同时不能明显破坏 MIXED Intent。

---

# 11. Part C — Retrieval Log selected memory IDs

## 11.1 Objective

让 Retrieval Log 不只记录：

```text
candidate count
selected count
```

还可以回答：

```text
最终哪些 memory 被选中了？
```

---

## 11.2 Minimum Fields

建议至少记录：

- selected memory IDs
- selected channels
- selected memory types

如果现有 Log Schema 已有扩展字段：

优先复用 JSON / metadata 字段。

不要为此做大规模 DB Migration。

---

## 11.3 Acceptance Criteria

给定一次 Retrieval：

可以从 Retrieval Log 恢复：

```text
query
intent
channels
candidate_count
selected_count
selected_memory_ids
latency
```

---

# 12. Closure Definition of Done

Stage 2 Closure 只有满足以下条件才可以声明 DONE。

## Scope

- [ ] Working Cross-project isolation 通过。
- [ ] Episode Cross-project isolation 通过。
- [ ] Cross-user isolation 通过。
- [ ] Agent `/step` Scope Propagation 通过。
- [ ] 无 task_id fallback 不产生 project leak。

## Regression

- [ ] Stage 1 Formation 回归 0 failed。
- [ ] Candidate Repository Contract 已统一。
- [ ] Real / InMemory Repository 不存在当前已知接口漂移。

## Scenario

- [ ] Batch 5 Current State Scenario 真实 PASS。
- [ ] Task History Scenario 真实 PASS。
- [ ] Preference Scenario 真实 PASS。
- [ ] Semantic Fact Scenario 真实 PASS。
- [ ] Exact Keyword Scenario 真实执行。
- [ ] Cross Project Scenario 真实 PASS。
- [ ] Cross User Scenario 真实 PASS。
- [ ] Mixed Intent Scenario 真实 PASS。
- [ ] Duplicate Projection Scenario 真实 PASS。
- [ ] Context Budget Scenario 真实 PASS。
- [ ] Legacy vs vNext Comparison 真实执行。
- [ ] 关键 Scenario 不存在 module-level dependency skip。

## Budget

- [ ] Hard Context Budget 不再被超长 Working State 大幅突破。

## Intent

- [ ] CURRENT_STATE 中文自然 Query 不依赖 hint。
- [ ] TASK_HISTORY 中文自然 Query 不依赖 hint。
- [ ] PREFERENCE 中文自然 Query 不依赖 hint。
- [ ] SEMANTIC_FACT 中文自然 Query 不依赖 hint。

## Observability

- [ ] Retrieval Log 可记录 selected memory IDs。
- [ ] Retrieval Log persistence test 真实执行。

## Regression

- [ ] Legacy Retrieval 关键路径完成可解释回归。
- [ ] Stage 2 targeted tests 无新增失败。

---

# 13. 不属于 Closure DoD 的事项

以下问题即使存在，也不阻塞进入 Stage 3：

```text
Channel 串行执行
```

```text
默认 vnext.mode = legacy
```

```text
完整性能优化
```

```text
LLM Intent Router
```

```text
高级 Learning-to-Rank
```

这些后续处理。

---

# 14. Codex 新会话启动提示词

```text
你正在执行 MemoryHub vNext Stage 2 Closure。

开始前必须完整阅读：

1. docs/vnext/VNEXT_PLAN.md
2. docs/vnext/stages/stage2-retrieval.md
3. docs/vnext/stages/stage2-closure.md
4. docs/vnext/PROGRESS.md
5. Stage 2 Completion Review

先不要修改任何代码。

首先针对当前 Fix Batch 执行 Codebase Reconnaissance。

要求：

- 验证 Review 中指出的问题是否仍然存在
- 找到真实调用链
- 找到真实失败测试
- 找到最小修改范围
- 判断是否需要 Schema / Repository Contract 变化
- 明确当前 Batch 不会修改哪些模块
- 给出最小执行计划

如果 Review 结论与当前代码不一致：
以当前代码和真实测试为准，并说明差异。

完成分析后停止。

不要自动修改代码。
```

---

# 15. Codex Fix Batch 执行提示词

```text
按照刚才确认的计划执行当前 Stage 2 Closure Fix Batch。

执行约束：

1. 只修当前 Fix Batch。
2. 不提前执行后续 Fix Batch。
3. 不进入 Stage 3。
4. 不新增新的 Retrieval Architecture。
5. 不删除 Legacy Retrieval。
6. 不用 skip / xfail 掩盖失败。
7. 不放宽测试断言适配错误行为。
8. 优先修真实逻辑，再修测试。
9. 单个 Fix Batch 原则上修改不超过 8 个核心源码文件。
10. 测试文件可按需要调整，但禁止让真实 E2E 退化成 mock-only。
11. 所有 Scope 行为必须有 Cross-project / Cross-user 证据。
12. SKIP 不得计入 PASS。
13. 如果发现问题比 Review 描述更大，停止扩散并记录。

完成后必须输出：

- Changes
- Files Touched
- Behavior Before
- Behavior After
- Tests
- Exact PASS / FAIL / SKIP counts
- Evidence
- Regression
- Remaining Risks
- Next Fix Batch Notes

然后更新：

docs/vnext/PROGRESS.md

最后 STOP。

不要自动进入下一个 Fix Batch。
```

---

# 16. PROGRESS.md 更新要求

建议新增：

```text
## Stage 2 Closure

Status:
IN PROGRESS
```

并维护：

| Fix Batch | 名称 | 状态 |
|---|---|---|
| Fix 1 | Scope Isolation & Agent Scope Propagation | NOT STARTED |
| Fix 2 | Stage 1 Formation Regression Recovery | NOT STARTED |
| Fix 3 | Test Environment & Real Scenario Verification | NOT STARTED |
| Fix 4 | Budget / Intent / Retrieval Log Closure | NOT STARTED |

状态只允许：

```text
NOT STARTED
IN PROGRESS
BLOCKED
DONE
```

每个 Batch 的记录必须包含：

- Reconnaissance Findings
- Changes
- Tests
- PASS / FAIL / SKIP 数量
- Evidence
- Remaining Risks
- Next Batch Notes

---

# 17. Final Closure Review

所有 Fix Batch 完成后：

必须新开 Codex 会话执行 Review。

禁止由最后一个 Fix Batch 会话自行宣布 READY。

使用：

```text
对 MemoryHub vNext Stage 2 Closure 做最终独立 Review。

先阅读：

- docs/vnext/VNEXT_PLAN.md
- docs/vnext/stages/stage2-retrieval.md
- docs/vnext/stages/stage2-closure.md
- docs/vnext/PROGRESS.md
- 上一次 Stage 2 Completion Review

不要修改代码。

不要相信 PROGRESS.md 中的 DONE 状态。

基于真实代码与真实测试重新验证：

1. Cross-project isolation
2. Cross-user isolation
3. Agent scope propagation
4. Stage 1 Formation regression
5. Batch 5 real scenarios
6. Legacy retrieval regression
7. hard context budget
8. Chinese intent routing
9. Retrieval Log selected IDs
10. Retrieval Log persistence

必须明确区分：

PASS
FAIL
SKIP
NOT RUN

SKIP 不算 PASS。

最终输出：

# Stage 2 Closure Review

## 1. Final Verdict

READY FOR STAGE 3
或
NOT READY

## 2. Closure DoD

逐条：
PASS / FAIL / PARTIAL

## 3. Test Evidence

明确：
passed / failed / skipped / deselected

## 4. Scope Verification

Cross-user
Cross-project
Agent scope propagation

## 5. Stage 1 Regression

## 6. Stage 2 Scenario Results

A-J 分别列出结果。

## 7. Legacy vs vNext

## 8. Budget Verification

## 9. Intent Verification

## 10. Retrieval Log Verification

## 11. Remaining Risks

## 12. Final Recommendation

不要修改任何代码。
```

---

# 18. 进入 Stage 3 的硬条件

只有 Final Closure Review 输出：

```text
READY FOR STAGE 3
```

才允许开始：

```text
Stage 3 — Feedback 闭环
```

否则继续留在 Closure。

原因：

```text
错误 Retrieval
  ↓
错误 Memory 进入 Context
  ↓
Stage 3 USED / Feedback
  ↓
错误 Utility 被强化
```

因此：

> Retrieval correctness 与 isolation 必须先于 Memory Feedback / Evolution 完成。
