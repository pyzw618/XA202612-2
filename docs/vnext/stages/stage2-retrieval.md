# stage2-retrieval.md

# Stage 2 — Retrieval 实化

## 1. Stage 目标

本阶段只解决一个核心问题：

> 将当前 vNext 从“已经定义 Retrieval Runtime 架构”推进到“能够真正依据 Intent、Scope 和 Memory Layer，从 Working / Episode / Authority / Keyword / Vector 等通道检索并构造高质量 Context”。

Stage 1 的目标是解决：

```text
Event
  ↓
Working State
  ↓
Episode
  ↓
Boundary
  ↓
Reflection
  ↓
Candidate
```

Stage 2 在此基础上解决：

```text
Agent Query
    ↓
Intent Resolution
    ↓
Retrieval Planning
    ↓
Multi-channel Retrieval
    ├── Working
    ├── Episode
    ├── Authority
    ├── Keyword
    └── Vector
    ↓
Fusion
    ↓
Rerank
    ↓
Scope Resolution
    ↓
Context Budget
    ↓
ContextPayload
```

本阶段完成后，vNext Retrieval 必须第一次真正体现出：

> “不同问题应该检索不同层次的 Memory，而不是所有问题都退化为 Legacy Vector Search”。

---

# 2. Stage 2 前置条件

开始 Stage 2 前，Codex 必须先确认 Stage 1 的完成状态。

至少检查：

- Working State 已能承载真实任务状态。
- Episode 已能承载有意义的任务过程。
- Candidate Formation 已可运行。
- candidate-only 模式仍然有效。
- Legacy 主链路没有明显回归。
- Stage 1 Scenario Tests 已有可复现结果。

如果 Stage 1 仍存在影响 Retrieval 的阻塞项，应先记录到 `PROGRESS.md`。

不得在 Stage 2 中偷偷修复大范围 Stage 1 问题。

---

# 3. 当前问题假设

在正式修改前，Codex 必须通过代码确认以下判断是否成立。

重点检查：

1. `RetrievalPlanner` 是否已经定义 Working / Episode / Authority / Keyword / Vector 等通道。
2. 当前 `build_channel_executors()` 实际装配了哪些通道。
3. Working / Episode 是否已有 Repository / Service 可直接读取。
4. Long-Term Authority 当前从哪些 Repository 读取。
5. Keyword Retrieval 是否已有 BM25 / text index 等现成能力。
6. Vector Retrieval 当前是否仍主要复用 Legacy Retriever。
7. vNext Request → Legacy Search Request 的转换是否丢失：
   - project
   - task
   - session
   - intent
   - memory layer
8. ScopeResolver 当前具体执行什么过滤。
9. ContextService / ContextBuilder 当前如何做 budget。
10. Activation 当前在哪个阶段记录 RECALLED / SELECTED / IN_CONTEXT。
11. Retrieval Log 当前记录哪些信息。
12. Shadow / Rollout 当前如何调用 Legacy 与 vNext Retrieval。
13. 当前 Evaluation 是否已经有 vNext Retrieval 测试样例。

如果实际代码与上述假设不同，应先说明，再给出最小实现计划。

---

# 4. Stage 2 非目标

以下内容明确不属于本阶段：

- 不重构 Stage 1 Formation 主链路。
- 不重新设计 Candidate Promotion。
- 不实现完整 Memory Evolution。
- 不实现 Agent Outcome → Utility 的最终闭环。
- 不删除 Legacy Retriever。
- 不进行 vNext 全量 Cutover。
- 不大规模改数据库 Schema。
- 不重新实现 Milvus / FAISS。
- 不做无关 Dashboard 重构。
- 不提前执行 Stage 3 / Stage 4。
- 不为了统一接口而大规模重写已经稳定的 Legacy Retrieval。

Stage 2 的目标不是“把所有 Retrieval 代码重写一遍”。

目标是：

> 让 vNext Planner 规划出来的不同 Retrieval Channel 真正有对应执行器，并且把结果正确融合成 Context。

---

# 5. Stage 2 核心原则

## 5.1 Retrieval Intent 是一等概念

系统不应把所有 Query 都解释成：

```text
semantic search
```

至少需要区分现有 Domain Contract 中已经定义的 Intent，例如：

- CURRENT_STATE
- TASK_HISTORY
- PREFERENCE
- SEMANTIC_FACT
- PROCEDURE
- EXPERIENCE
- MIXED

不同 Intent 应有不同优先通道。

例如：

```text
CURRENT_STATE
→ Working 优先
→ Episode 辅助

TASK_HISTORY
→ Episode 优先
→ Working / Authority 辅助

PREFERENCE
→ Preference Authority 优先

SEMANTIC_FACT
→ Semantic Authority + Vector

PROCEDURE
→ Procedural Authority + Episode

EXPERIENCE
→ Episode + Procedural + Vector

MIXED
→ 多通道综合
```

---

## 5.2 Retrieval Layer 必须真实存在

Planner 输出：

```text
working
episode
authority
keyword
vector
```

时，不能最终全部路由到同一个 Legacy Vector Retriever。

Stage 2 完成后至少要有逻辑上独立的：

```text
Working Executor
Episode Executor
Authority Executor
Keyword Executor
Vector Executor
```

这些 Executor 可以复用现有 Repository / Legacy Retriever / BM25 / Vector Store。

不要求所有 Executor 都重新建设底层能力。

---

## 5.3 Scope 必须贯穿 Retrieval 全链路

至少要考虑：

- tenant
- user
- project
- task
- session
- global

Scope 不应只在 Query 最后做一次简单过滤。

目标是：

```text
Request Scope
    ↓
Planner
    ↓
Channel Query
    ↓
Repository / Search
    ↓
Scope Resolver
    ↓
Final Context
```

禁止出现：

```text
project_id 已存在
↓
转换 Legacy Search Request 时变成 ""
```

这类信息丢失。

---

## 5.4 Working / Episode 优先走结构化查询

Working State 与 Episode 本身就是结构化 Memory。

不应为了统一接口，强制全部先转 embedding 再检索。

例如：

```text
CURRENT_STATE
```

优先应该是：

```text
tenant + user + project + task
→ Working Repository
```

而不是：

```text
query embedding
→ vector search
→ 猜哪个 Working State 最相似
```

---

## 5.5 Authority 负责可信长期事实

Authority Retrieval 必须优先保证：

- active / valid
- scope 正确
- 未删除
- 未 superseded
- 当前版本有效

而不是只按照语义相似度选。

对于 Preference / Semantic / Procedural，应优先使用 Authority 的结构化字段和状态信息。

---

## 5.6 Fusion 不能破坏通道语义

多通道结果融合时，不应简单把所有 score 放进同一个数组然后排序。

至少需要保留：

- source channel
- memory type
- scope
- authority status
- recency
- relevance
- confidence
- retrieval reason

最终 Fusion 可以统一排序，但必须知道候选来自哪里。

---

## 5.7 Context Budget 必须按价值分配

Context 构造不是：

```text
TopK → 全塞
```

需要考虑：

- Working State 高优先级
- 当前任务强相关 Episode
- 高可信 Authority
- Query-specific Evidence
- token budget
- 去重
- 冲突
- scope

目标是：

> 用尽可能少的 Memory Token，保留最有用的任务信息。

---

# 6. Stage 2 Batch 划分

Stage 2 拆成 5 个 Batch。

```text
Batch 1 — Working / Episode Executors
Batch 2 — Authority / Keyword / Vector Executors
Batch 3 — Intent + Scope Propagation
Batch 4 — Fusion / Rerank / Context Budget
Batch 5 — Retrieval Scenario Tests & Legacy Comparison
```

每个 Codex 会话原则上只执行一个 Batch。

每完成一个 Batch：

1. 运行相关测试。
2. 输出修改证据。
3. 更新 `docs/vnext/PROGRESS.md`。
4. STOP。
5. 不自动开始下一个 Batch。

---

# 7. Batch 1 — Working / Episode Executors

## 7.1 Objective

让 vNext Retrieval 第一次真正能够直接读取：

```text
Working State
Task Episode
```

而不是把这两类 Intent 退化为 Legacy Vector Search。

---

## 7.2 Target Flow

### CURRENT_STATE

```text
Query
  ↓
Intent = CURRENT_STATE
  ↓
Planner
  ↓
Working Executor
  ↓
Scope-aware Working Repository
  ↓
Working Result
```

### TASK_HISTORY

```text
Query
  ↓
Intent = TASK_HISTORY
  ↓
Planner
  ↓
Episode Executor
  ↓
Episode Repository
  ↓
Relevant Episode Results
```

---

## 7.3 Working Executor

优先支持：

- 当前 task 的 Working State
- 当前 project 最近 Working State
- 当前 session Working State
- current_goal
- current_step
- blockers
- completed / pending
- active entities

不要把历史上所有 Working State 无限制返回。

---

## 7.4 Episode Executor

Episode Retrieval 至少考虑：

- tenant
- user
- project
- task
- session
- recency
- task status
- query relevance

如果 Episode 已经存在 summary / title / goal / key events，应优先利用这些字段。

---

## 7.5 Acceptance Criteria

### CURRENT_STATE

Given：

同一用户有多个项目和任务状态。

When：

查询“我现在做到哪里了”。

Then：

- 优先返回当前 Scope 对应 Working State。
- 不返回其他用户状态。
- 不优先返回历史长期记忆。
- 结果能恢复 current goal / current step / blockers / pending。

### TASK_HISTORY

Given：

当前项目存在多个 Episode。

When：

查询“这个问题之前怎么处理过”。

Then：

- Episode Executor 被真实调用。
- 返回与当前 Scope 相关的历史任务。
- 不只是 Legacy Vector Retriever 的结果。

---

## 7.6 Must Not Change

本 Batch 不：

- 实现 Authority Executor。
- 调整复杂 Fusion。
- 实现 Feedback。
- 修改 Formation。

---

# 8. Batch 2 — Authority / Keyword / Vector Executors

## 8.1 Objective

补齐长期 Memory 与通用搜索通道。

目标至少具备：

```text
Authority Executor
Keyword Executor
Vector Executor
```

---

## 8.2 Authority Executor

Authority Executor 负责：

- Preference
- Semantic
- Procedural
- Episodic Authority

优先复用：

- AuthorityRepository
- Preference Repository
- Knowledge Repository
- 现有有效性 / 生命周期逻辑

过滤必须考虑：

- active
- current version
- not deleted
- not archived（视实际规则）
- not superseded
- scope valid

---

## 8.3 Preference Retrieval

Preference 不应只依赖 embedding。

例如：

```text
“我平时 Java 项目用 Maven 还是 Gradle？”
```

应优先：

```text
Preference Authority
→ project/user scope
→ active preference
```

---

## 8.4 Semantic Retrieval

Semantic Fact 可以结合：

```text
metadata
keyword
vector
```

例如：

```text
“这个项目用什么数据库？”
```

---

## 8.5 Procedural Retrieval

Procedure 应优先返回：

- 可复用步骤
- 成功经验
- 使用条件
- scope
- confidence / utility

而不是只返回相似 Episode 原文。

---

## 8.6 Keyword Executor

优先复用当前：

- BM25
- Text Index
- Keyword Retriever

不重写搜索引擎。

Keyword Channel 应适合：

- 类名
- 文件名
- 命令
- 配置项
- 精确术语
- Error Code

---

## 8.7 Vector Executor

允许复用 Legacy Vector Retriever。

但必须明确：

```text
Vector Executor
≠ 整个 vNext Retrieval
```

Vector 是一个通道，不是最终架构。

---

## 8.8 Acceptance Criteria

1. Planner 选择 Authority 时，真实 Authority Executor 被调用。
2. Preference Query 可以优先获取 Preference Authority。
3. Semantic Query 可以利用长期 Semantic Memory。
4. Keyword Query 可以命中精确术语。
5. Vector Query 仍然工作。
6. 不同 Channel 的 source 信息被保留。
7. Legacy Retriever 仍然可以独立运行。

---

# 9. Batch 3 — Intent + Scope Propagation

## 9.1 Objective

确保：

```text
Intent
Scope
```

从 API Request 一直传到每个 Retrieval Channel，不在中间丢失。

---

## 9.2 Required Scope

至少确认以下字段的真实传播：

- tenant_id
- user_id
- project_id
- task_id
- session_id
- memory scope
- retrieval intent

如果现有 Contract 字段略有差异，以实际 Domain Contract 为准。

---

## 9.3 Scope Precedence

建议保持清晰优先级：

```text
task
  ↓
session
  ↓
project
  ↓
user
  ↓
global
```

具体是否完全采用此顺序，应结合现有 ScopeResolver。

不要重新创造与当前 Scope Contract 冲突的体系。

---

## 9.4 Scope Leak

必须重点测试：

```text
User A
≠
User B
```

```text
Project A
≠
Project B
```

以及：

```text
Project preference
≠
Global preference
```

---

## 9.5 Legacy Adapter

如果 vNext 某个 Channel 复用 Legacy Retriever：

必须保证转换过程中尽可能保留：

- tenant
- user
- project
- level
- type
- query

禁止无理由硬编码：

```text
project_id = ""
```

或：

```text
level = "long"
```

导致 vNext Intent / Scope 失效。

---

## 9.6 Intent Resolution

检查 IntentRouter 当前规则。

优先做到：

```text
可解释
稳定
可测试
```

而不是立刻引入复杂 LLM Intent Router。

如果当前规则路由已经足够，应先保持 deterministic。

---

## 9.7 Acceptance Criteria

1. Request Scope 全链路可追踪。
2. Project Scope 不丢失。
3. Task Scope 不丢失。
4. User 隔离正确。
5. Intent 可以影响 Channel Planning。
6. CURRENT_STATE 与 TASK_HISTORY 走不同通道。
7. PREFERENCE 与 SEMANTIC_FACT 能产生不同 Planning。
8. Scope Leak 测试通过。

---

# 10. Batch 4 — Fusion / Rerank / Context Budget

## 10.1 Objective

让多个真实 Channel 的结果能够：

```text
去重
→ 融合
→ 排序
→ Scope 校验
→ Budget
→ ContextPayload
```

---

## 10.2 Retrieval Candidate Metadata

最终 Candidate 至少保留等价信息：

- memory_id / source_id
- channel
- memory_type
- layer
- scope
- relevance score
- authority confidence
- recency
- retrieval reason
- provenance

如果当前数据结构已有对应字段，直接复用。

---

## 10.3 Dedup

同一条 Authority Memory 可能同时来自：

```text
Authority
Keyword
Vector
```

最终 Context 不应出现三遍。

需要按稳定 ID / authority ID / content identity 做去重。

---

## 10.4 Fusion

Fusion 至少考虑：

```text
query relevance
channel priority
intent fit
authority quality
scope fit
recency
```

不要一开始设计过于复杂的学习排序器。

优先保证规则清晰、可测试。

---

## 10.5 Rerank

如果已有 Reranker：

优先复用。

Stage 2 不要求重写 Reranker。

重点是确保：

```text
Reranker 输入的是多通道有效候选
```

而不是只给 Legacy Vector Hits 换顺序。

---

## 10.6 Context Budget

Context Builder 应至少做到：

1. Working State 保留关键当前状态。
2. Episode 只保留相关历史。
3. Authority 保留高价值事实。
4. 重复内容不重复占 Token。
5. 超预算时有明确裁剪顺序。

建议优先级根据 Intent 动态变化。

例如：

### CURRENT_STATE

```text
Working > Episode > Authority > Vector
```

### PREFERENCE

```text
Preference Authority > Working > Episode > Vector
```

### EXPERIENCE

```text
Episode > Procedural > Vector > Working
```

---

## 10.7 Activation

Stage 2 至少确认：

```text
RECALLED
SELECTED
IN_CONTEXT
```

三个状态可以真实反映 Retrieval Pipeline。

`USED` 留到 Stage 3。

---

## 10.8 Acceptance Criteria

1. 多通道结果能进入同一 Fusion。
2. 同一 Memory 不重复进入 Context。
3. Intent 会影响 Channel Weight / Priority。
4. Scope 不合法的 Candidate 在最终 Context 前被过滤。
5. Context Token Budget 生效。
6. Activation 至少可以记录到 IN_CONTEXT。
7. Retrieval Log 可以看出：
   - intent
   - channels
   - selected memories
   - latency
   - final context

---

# 11. Batch 5 — Retrieval Scenario Tests & Legacy Comparison

## 11.1 Objective

用真实 Query Scenario 验证：

> vNext Retrieval 是否真的开始区别于 Legacy Retrieval。

禁止只通过 Unit Test 宣布 Stage 2 完成。

---

# 12. 必测 Scenario

## Scenario A — Current State

Memory：

```text
Working State:
当前正在修复 SSE reconnect bug
已经定位 timeout 配置
下一步验证断网重连
```

Query：

```text
“我现在做到哪里了？”
```

Expected：

```text
Intent = CURRENT_STATE
Working Channel 被优先调用
```

结果应准确恢复当前任务。

---

## Scenario B — Task History

存在：

```text
多个历史 Episode
```

Query：

```text
“之前这个 SSE 重连问题是怎么处理的？”
```

Expected：

```text
TASK_HISTORY / EXPERIENCE
Episode Channel 优先
```

---

## Scenario C — Preference

Authority：

```text
用户在 Java 项目中偏好 Maven
```

Query：

```text
“我一般用 Maven 还是 Gradle？”
```

Expected：

```text
Preference Authority
```

优先于普通 Vector Hit。

---

## Scenario D — Semantic Fact

Authority：

```text
当前项目数据库是 PostgreSQL
```

Query：

```text
“这个项目数据库用什么？”
```

Expected：

Semantic Authority 被检索。

---

## Scenario E — Exact Keyword

Memory 包含：

```text
spring.mvc.async.request-timeout
```

Query 包含完全相同配置项。

Expected：

Keyword Channel 应具有明显价值。

---

## Scenario F — Cross Project Isolation

Project A：

```text
使用 Maven
```

Project B：

```text
使用 Gradle
```

Query 在 Project B：

```text
“这个项目用什么构建工具？”
```

不得泄露 Project A 的 project-scoped Memory。

---

## Scenario G — Cross User Isolation

User A 和 User B 有冲突 Preference。

必须严格隔离。

---

## Scenario H — Mixed Intent

Query：

```text
“现在这个任务做到哪了？之前类似问题是怎么解决的？”
```

Expected：

```text
MIXED
→ Working + Episode
```

而不是只调用 Vector。

---

## Scenario I — Duplicate Projection

同一 Authority Memory 同时被：

```text
Authority
Keyword
Vector
```

命中。

最终 Context 只能出现一次主要表达。

---

## Scenario J — Context Budget

构造大量相关 Memory。

Expected：

- 不超过 Budget。
- 当前任务核心状态不被低价值历史挤掉。
- 裁剪行为可解释。

---

# 13. Legacy vs vNext 对照

Stage 2 不要求 vNext 已经全面优于 Legacy。

但必须第一次形成真实对照。

至少记录：

| Case | Legacy | vNext | Expected Winner |
|---|---|---|---|
| Current State | ? | ? | vNext |
| Task History | ? | ? | vNext |
| Preference | ? | ? | vNext / Equal |
| Semantic Fact | ? | ? | Equal / vNext |
| Exact Keyword | ? | ? | Depends |
| Scope Isolation | ? | ? | vNext |
| Mixed Intent | ? | ? | vNext |

重点不是强行证明 vNext 赢。

重点是：

> 证明 vNext 的分层检索机制已经真实工作。

---

# 14. Stage 2 测试层级

必须至少包含：

## Unit

- Intent Router
- Scope Resolver
- Working Executor
- Episode Executor
- Authority Executor
- Fusion / Dedup

## Component

- Query → Planner → Working
- Query → Planner → Episode
- Query → Planner → Authority
- Multi-channel → Fusion
- Fusion → Context

## Scenario

至少覆盖第 12 节的核心 Scenario。

## Regression

- Legacy Retrieval 可继续运行。
- Stage 1 Formation 不回归。
- candidate-only 不回归。
- Safety / Forget 语义不被绕过。

---

# 15. Stage 2 可观测性要求

每次 vNext Retrieval 至少应能够回答：

```text
这个 Query 被识别成什么 Intent？
```

```text
Planner 选择了哪些 Channel？
```

```text
每个 Channel 返回多少 Candidate？
```

```text
哪些 Candidate 被 Fusion 淘汰？
```

```text
哪些被 SELECTED？
```

```text
哪些进入 IN_CONTEXT？
```

```text
最终 Context 使用多少 Budget？
```

无需为了 Stage 2 重做 Dashboard。

优先保证日志 / trace / retrieval log 可以回答这些问题。

---

# 16. Stage 2 性能边界

Stage 2 的第一目标是正确性，不是极限优化。

但不得引入明显不可接受的串行链路。

特别检查：

```text
Working
Episode
Authority
Keyword
Vector
```

是否可以在满足依赖关系的情况下并行执行。

如果当前框架支持并行，应优先并行独立 Channel。

但不要为了并行大规模重构 Repository。

至少记录：

- total retrieval latency
- per-channel latency
- fusion latency
- rerank latency
- context build latency

---

# 17. Stage 2 Definition of Done

Stage 2 只有全部满足关键条件才视为完成。

- [ ] Working Executor 已真实接入。
- [ ] Episode Executor 已真实接入。
- [ ] Authority Executor 已真实接入。
- [ ] Keyword Executor 已真实接入或明确复用现有 Keyword 能力。
- [ ] Vector Executor 已明确作为独立 Channel 工作。
- [ ] CURRENT_STATE 不再主要退化到 Legacy Vector Search。
- [ ] TASK_HISTORY 可以真实检索 Episode。
- [ ] PREFERENCE 可以优先检索 Preference Authority。
- [ ] Intent 会影响 Planner Channel 选择。
- [ ] tenant / user / project / task / session Scope 不在关键转换中丢失。
- [ ] Cross-user isolation 测试通过。
- [ ] Cross-project isolation 测试通过。
- [ ] Multi-channel Fusion 可以工作。
- [ ] 同一 Memory 多通道命中时可以去重。
- [ ] Context Budget 生效。
- [ ] Activation 至少记录 RECALLED / SELECTED / IN_CONTEXT。
- [ ] Retrieval Log 能解释 Query → Channel → Context。
- [ ] Legacy Retrieval 主链路无明显回归。
- [ ] Stage 1 Formation 无明显回归。
- [ ] 至少完成核心 Retrieval Scenario Test。
- [ ] 有 Legacy vs vNext 的第一轮真实对照结果。

未全部满足关键 DoD 条目时，不得在 `PROGRESS.md` 中声明 Stage 2 DONE。

---

# 18. 修改预算

单个 Batch 原则上：

```text
≤ 8 个核心源码文件
```

测试文件不计入核心源码文件预算。

如果必须超过：

1. 先说明修改扩散原因。
2. 判断是否暴露出架构问题。
3. 优先调整 Batch 边界。
4. 不直接继续扩散。

---

# 19. Codex 每个新会话启动提示词

```text
你正在执行 MemoryHub vNext Stage 2 — Retrieval 实化。

开始前必须完整阅读：

1. docs/vnext/VNEXT_PLAN.md
2. docs/vnext/stages/stage2-retrieval.md
3. docs/vnext/PROGRESS.md

同时检查 Stage 1 当前完成状态。

先不要修改任何代码。

首先执行 Codebase Reconnaissance：

- 确认当前 Batch 的真实实现状态
- 找出完整 Retrieval 调用链
- 确认 Planner 当前输出
- 确认实际 Channel Executor 装配
- 确认 Working / Episode / Authority Repository
- 确认 Legacy Retriever 复用点
- 检查 Scope 在 Request → Planner → Executor → Result 中是否丢失
- 检查当前测试
- 对照 Stage 文档说明哪些判断成立、哪些不成立
- 给出本 Batch 最小修改计划
- 明确本 Batch不会修改哪些模块

完成分析后停止。

不要自动修改代码。
```

---

# 20. Codex Batch 执行提示词

Reconnaissance 确认后使用：

```text
按照刚才确认的计划执行当前 Stage 2 Batch。

执行约束：

1. 只处理当前 Batch。
2. 不提前实现后续 Batch。
3. 不修改 Stage 1 Formation 主设计，除非是明确的兼容性修复。
4. 优先复用现有 Repository / Retriever / BM25 / Vector / Authority 组件。
5. 不建立平行 Retrieval Framework。
6. 不为了接口统一做大规模无关重构。
7. 单个 Batch 原则上修改不超过 8 个核心源码文件。
8. 每完成一个逻辑单元立即运行相关测试。
9. Intent 和 Scope 不允许在适配过程中静默丢失。
10. Working / Episode 优先使用结构化 Retrieval。
11. Vector 只能作为 Channel，不允许重新成为整个 vNext Retrieval 的唯一实现。
12. 如果实际代码与 Stage 文档冲突，记录差异并采用最小兼容方案。
13. 如果需要新的架构决策，不要擅自扩大修改范围。
14. 执行完当前Batch后，确认无误就提交当前的git

完成后必须输出：

- Changes
- Files Touched
- Behavior Before
- Behavior After
- Tests
- Evidence
- Scope Verification
- Retrieval Channel Verification
- Remaining Risks
- Regression
- Next Batch Notes

然后更新：

docs/vnext/PROGRESS.md

最后 STOP。

不要自动执行下一个 Batch。
```

---

# 21. Stage 2 最终 Review 提示词

所有 Batch 完成后，新开一个 Codex 会话执行 Review：

```text
对 MemoryHub vNext Stage 2 做完成度 Review。

先阅读：

- docs/vnext/VNEXT_PLAN.md
- docs/vnext/stages/stage2-retrieval.md
- docs/vnext/PROGRESS.md

不要先相信 PROGRESS.md 中的 DONE 结论。

基于真实代码、调用链和测试逐条验证 Stage 2 Definition of Done。

重点检查：

1. Planner 输出的 Channel 是否真的存在执行器。
2. CURRENT_STATE 是否真实读取 Working State。
3. TASK_HISTORY 是否真实读取 Episode。
4. PREFERENCE 是否真实读取 Authority。
5. Keyword 与 Vector 是否为独立通道。
6. Scope 是否在 Request → Executor → Context 全链路保持。
7. 是否仍存在最终退化成单一 Legacy Vector Retriever 的情况。
8. Fusion 是否对多通道真实结果生效。
9. Duplicate Memory 是否被去重。
10. Context Budget 是否真实生效。
11. Activation 是否至少到 IN_CONTEXT。
12. Cross-user / Cross-project isolation 是否有真实测试。
13. Legacy Retrieval 是否回归。
14. Stage 1 Formation 是否回归。

最终输出：

Stage 2 Completion Review

1. Definition of Done
   - 每条 PASS / FAIL / PARTIAL
   - 对应代码证据
   - 对应测试证据

2. Real Retrieval Architecture
   Query
   → Intent
   → Planner
   → Channels
   → Fusion
   → Scope
   → Context

3. Scenario Results

4. Legacy vs vNext Comparison

5. Regression

6. Remaining Risks

7. Files Touched

8. Final Verdict
   - READY FOR STAGE 3
   或
   - NOT READY

不要修改代码。
```

---

# 22. Stage 2 完成后的目标状态

Stage 2 完成后，vNext 应达到：

```text
              Query
                ↓
          Intent Router
                ↓
             Planner
                ↓
    ┌───────────┼───────────────┐
    ↓           ↓       ↓       ↓       ↓
 Working     Episode  Authority Keyword Vector
    │           │       │       │       │
    └───────────┴───────┴───────┴───────┘
                ↓
              Fusion
                ↓
              Rerank
                ↓
          Scope Resolution
                ↓
          Context Budget
                ↓
         ContextPayload
                ↓
              Agent
```

此时才进入 Stage 3：

```text
Context
  ↓
Agent Usage
  ↓
USED
  ↓
Outcome Feedback
  ↓
Utility / Stability
  ↓
Memory Evolution
```
