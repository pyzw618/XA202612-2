# MemoryHub vNext：A/B/C/D 一体化改进方案

> 本文整合《记忆创新设计方案.md》和《MemoryHub vNext：BCD 系统详细设计方案.md》，形成可用于系统重构、比赛答辩和实验验证的统一版本。

## 0. 方案定位与结论

两份原方案不是相互独立的两套设计，而是上下游关系：

```text
A：Memory Cognitive Architecture
   解决“什么值得记、如何形成和演化”
        ↓
C：Memory Infrastructure
   解决“如何可靠保存、索引、同步和删除”
        ↓
B：Retrieval & Context System
   解决“当前应该找什么、如何进入上下文”
        ↓
D：Evaluation & Observability
   解决“是否有效、为何有效或失败、如何持续优化”
```

两份方案合并后的最终定位是：

> **MemoryHub 是一个面向桌面 OS Agent 的任务状态驱动记忆系统。它通过 Working State、Task Episode、Memory Candidate 和 Long-Term Memory 管理记忆形成，通过 Authority Store 和可重建索引保证可靠性，通过意图路由和上下文编排保证正确使用，并通过评测与反馈实现持续演化。**

最终闭环为：

```text
Observe → Maintain → Checkpoint → Reflect → Consolidate
    → Persist/Index → Retrieve/Activate → Context Build
    → Agent Action → Evaluate/Trace → Evolve
```

本版本的重点不是继续增加概念，而是把两份方案收敛为：

1. 一套统一术语；
2. 一条唯一写入链路和唯一检索链路；
3. 一组稳定的数据契约；
4. 一套可分阶段交付的工程计划；
5. 一套能证明创新有效的指标和实验。

---
## 1. 对两份原方案的分析

### 1.1 第一份方案的贡献：建立 A 层认知架构

《记忆创新设计方案.md》解决了 MemoryHub 最核心的语义问题：

- 将记忆层级与记忆类型拆为两个正交维度；
- 将短期记忆从“最近消息”改为当前任务的 Working State；
- 将中期记忆从 Summary 改为可恢复的 Task Episode；
- 用 Checkpoint 而不是 TTL 驱动 Working → Episode；
- 用 Reflection、Candidate 和 Evidence-driven Consolidation 驱动 Episode → Long-Term；
- 将 Preference、Semantic、Procedural、Episodic Experience 作为长期记忆类型；
- 引入 Scope、Conflict Evolution、Activation、Forget 和 Memory Policy；
- 将 Retrieval 从无差别搜索升级为 Memory Routing。

它的核心创新链路可以概括为：

```text
Working State → Task Episode → Candidate → Persistent Memory
```

这是系统的“记忆认知内核”，应作为整合方案的 A 层保留。

### 1.2 第二份方案的贡献：补齐 B/C/D 工程闭环

《MemoryHub vNext：BCD 系统详细设计方案.md》主要补充了：

- B：统一 Retrieval Request、Intent Router、Multi-channel Recall、Reranker、Context Budget 和 Canonical Retrieval Pipeline；
- C：Authority Store、Projection、Outbox、Projection Version、Evidence、Lineage、Forget、Idempotency、Repair；
- D：Formation、Retrieval、Infrastructure、End-to-End 四层评测，以及 Formation Trace、Evolution Trace、Retrieval Trace 和 Dashboard。

它把 A 层的认知设计变成了一个可存储、可检索、可观测的系统。

### 1.3 合并后必须修正的几个问题

原方案整体方向正确，但直接合并会产生以下问题。本版本统一修正：

| 问题 | 风险 | 本版本的统一规则 |
|---|---|---|
| Layer、Type、Status、Activation 混用 | 同一个 `level` 字段承担多个含义 | 四者分离，分别表达生命周期、语义类型、状态和使用状态 |
| Retrieval Intent 定义有 5 类和 7 类两种版本 | Router、Benchmark 和 API 无法对齐 | 统一为 7 类：`CURRENT_STATE`、`TASK_HISTORY`、`PREFERENCE`、`SEMANTIC_FACT`、`PROCEDURE`、`EXPERIENCE`、`MIXED` |
| Candidate 的 `CONFIRMED` 与正式长期记忆关系不够明确 | 未确认内容可能被误检索 | Candidate 是独立 staging area；只有通过固化策略后才生成 Long-Term Memory |
| Memory 状态与演化关系混在一起 | `REVISED`、`SUPERSEDED` 既像状态又像动作 | 动作使用 `REINFORCE/REVISE/SUPERSEDE/COEXIST/REVIEW`，状态使用 `ACTIVE/DORMANT/SUPERSEDED/ARCHIVED/DELETED`；`SUPERSEDE` 是动作，`SUPERSEDED` 是旧版本结果状态 |
| B/C/D 顺序与实际运行顺序不完全一致 | 读者难以理解请求从哪里经过 | 认知流程按 A → C → B → Agent → D 展开，运行架构按事件流和查询流分别说明 |
| 只有组件设计，缺少统一数据契约 | 模块之间容易各自实现 | 增加 Event、Candidate、Memory、Evidence、Retrieval Request 等核心契约 |
| 有大量高级能力，但缺少验收门槛 | 容易陷入“大而全”的重构 | 采用 P0/P1/P2 分级，每阶段有可验证的完成标准 |
| Forget 只描述删除对象，未明确删除边界 | 敏感信息可能残留在索引、缓存或派生对象中 | Forget 以 Authority Tombstone 为起点，异步清除 Projection，并用残留检索率验收 |
| 论文依据与项目创新边界容易混淆 | 答辩时可能夸大已有工作 | 论文只表述为借鉴/组合依据，项目创新聚焦 OS 任务状态、证据固化、作用域演化和可审计闭环 |

---
## 2. 统一概念模型

### 2.1 四个正交维度

MemoryHub 不再用一个 `level` 字段表达全部语义，而采用四个维度：

#### 维度一：Lifecycle Layer

| Layer | 含义 | 核心问题 |
|---|---|---|
| `WORKING` | 当前任务工作状态 | Agent 现在正在做什么？ |
| `EPISODE` | 可恢复的任务过程 | 这个任务进行到哪里？ |
| `LONG_TERM` | 跨任务可复用记忆 | 过去学到了什么？ |

Candidate 不属于第四层，而是 `LONG_TERM` 写入前的 staging area。

#### 维度二：Memory Type

长期记忆按照“学到了什么”分类：

| Type | 回答的问题 | 典型内容 |
|---|---|---|
| `PREFERENCE` | 用户喜欢什么？ | 语言、格式、交互偏好 |
| `SEMANTIC` | 什么是事实？ | 项目、实体、环境、配置事实 |
| `PROCEDURAL` | 应该怎么做？ | 条件、步骤、验证方式 |
| `EPISODIC` | 过去发生过什么？ | 问题、环境、动作、结果、教训 |

Working 和 Episode 主要使用自己的结构化状态，不强行套用长期类型。

#### 维度三：Formation Status

它描述一条信息处于形成链路的哪一步：

```text
RAW_EVENT
  → WORKING_STATE
  → EPISODE_CHECKPOINT
  → CANDIDATE
  → CONSOLIDATED_MEMORY
```

Candidate 状态为：

```text
ACCUMULATING | CONFIRMED | REJECTED | REVIEW
```

`CONFIRMED` 只表示候选已经通过固化判定；正式 Memory 仍需创建独立记录并保留 lineage。

#### 维度四：Evolution Status 与 Activation

长期记忆的演化状态：

```text
ACTIVE → DORMANT → ARCHIVED
ACTIVE → SUPERSEDED
ACTIVE → DELETED
```

其中 `REINFORCE`、`REVISE`、`SUPERSEDE`、`COEXIST`、`REVIEW` 是演化动作，不是长期状态。

Activation 表示“本次任务是否将长期记忆带入 Working Context”，不改变其 `Layer`：

```text
Long-Term Memory
      ↓ retrieve
Memory Activation
      ↓ context build
Working Context
```

### 2.2 Scope 层级

```text
TASK > PROJECT > APPLICATION > DOMAIN > GLOBAL
```

`SESSION` 作为 Working/Episode 的会话范围使用，不与长期全局规则混淆。

Scope 的原则是“局部覆盖，不全局删除”：

```text
Global:  默认 Markdown
Project-A: 正式成果使用 DOCX
```

处理 Project-A 时，二者可以共存，Project-A 规则优先；离开 Project-A 后，Global 规则仍然有效。

### 2.3 两个必须分开的状态机

#### 状态机 A：信息形成

```text
Raw Event
   ↓ policy gate
Working State
   ↓ checkpoint
Task Episode
   ↓ reflection
Memory Candidate
   ├── REJECTED
   ├── REVIEW
   └── CONSOLIDATED
          ↓
     Long-Term Memory
```

#### 状态机 B：长期记忆演化

```text
ACTIVE
  ├── REINFORCE → ACTIVE
  ├── REVISE    → 新版本 ACTIVE，旧版本 ARCHIVED
  ├── SUPERSEDE → 新版本 ACTIVE，旧版本 SUPERSEDED
  ├── COEXIST   → 同 Scope 或不同 Scope 的并存关系
  ├── DORMANT   → 长期未使用
  └── DELETE    → Tombstone + Projection 清理
```

---
## 3. 总体架构与运行闭环

### 3.1 分层总架构

```text
                         OS Agent
                            │
                  observe / action / result
                            ▼
                    Memory Event Gateway
                            │
                      Policy + Idempotency
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
      A. Formation Path               B. Query Path
             │                             │
      Working State                 Retrieval Request
             │                             │
      Task Episode                  Intent Router
             │                             │
      Reflection                    Retrieval Planner
             │                             │
      Candidate                     Multi-channel Recall
             │                             │
      Consolidation                  Rerank + Conflict Resolve
             │                             │
      Long-Term Memory              Budget + Context Builder
             │                             │
             └──────────────┬──────────────┘
                            ▼
                  C. Authority + Projection
             Authority Store / Evidence / Lineage
                   Outbox / Vector / BM25 / Cache
                            │
                            ▼
                         Agent Context
                            │
                            ▼
                       Agent Decision
                            │
                            ▼
                  D. Evaluation + Observability
                            │
                            ▼
                   Feedback → A / B / C
```

### 3.2 两条 Canonical Path

#### Canonical Write Path

所有事件必须经过同一条写入链路：

```text
Event
  → Normalize
  → Policy Gate
  → Idempotency Check
  → Working Update
  → Checkpoint
  → Episode Update
  → Reflection
  → Candidate Accumulation
  → Consolidation
  → Authority Commit
  → Projection Outbox
```

`/event`、MCP、Agent SDK、后台任务都只能作为入口适配器，不得各自直接写 Long-Term Memory。

#### Canonical Retrieval Path

所有查询也必须统一：

```text
Retrieval Request
  → Query Understanding
  → Intent Router
  → Retrieval Planner
  → Multi-channel Recall
  → Fusion
  → Rerank
  → Scope/Conflict Resolution
  → Context Budgeting
  → Context Builder
  → Activation + Trace
```

`/search`、`/context`、MCP 和 Agent SDK 只能复用这一服务。

---
## 4. A：Memory Formation 设计

### 4.1 Event Gateway：先治理，再进入记忆管道

事件进入系统后先经过四步：

```text
Receive → Normalize → Policy Gate → Deduplicate
```

#### Memory Policy

Policy 与 Preference 分离，最少支持：

```text
ALLOW  ：允许进入记忆流程
MASK   ：脱敏后进入流程
DROP   ：不保存正文，也不进入后续抽取
REVIEW ：进入人工或高风险复核队列
```

Policy 需要覆盖：密码、Token、身份证明、支付信息、私密文件内容和用户显式要求忘记的信息。

#### Idempotency

每个事件至少具备：

```json
{
  "event_id": "E-20260822-001",
  "source_type": "chat|tool|file|system",
  "source_hash": "...",
  "idempotency_key": "...",
  "occurred_at": "...",
  "user_id": "...",
  "task_id": "...",
  "payload": {}
}
```

重复事件不得重复增加 Frequency、Evidence 或 Promotion Score。

#### 入口治理的执行顺序与失败处理

四步入口流程不能只是逻辑上的组件排列，还需要固定执行顺序。推荐先做格式校验和身份绑定，再执行策略判断，最后生成幂等键。这样可以避免敏感正文先进入日志、队列或去重缓存后才被 Policy 拦截。

```text
1. Envelope Validation
   校验 user_id、source_type、occurred_at、payload schema
2. Identity & Scope Binding
   将窗口、文件、应用和当前任务映射到 task/project/application scope
3. Policy Classification
   识别敏感字段、保留级别、允许用途和过期策略
4. Payload Transformation
   对 MASK 数据做字段级替换，对 DROP 数据仅保留无正文的拒绝记录
5. Idempotency Derivation
   根据来源 ID、规范化内容和任务边界生成 idempotency_key
6. Event Commit
   原子写入事件、策略结果和幂等记录
```

Policy 结果还应包含 `reason_code`、`policy_version`、`retention_class` 和 `allowed_purposes`。同一段信息可能允许用于当前任务，却不允许进入长期固化，因此 `ALLOW` 不能只有一个布尔值，而应区分 `working_allowed`、`episode_allowed` 与 `long_term_allowed`。

异常处理遵循“宁可延迟形成，不可绕过治理”：Policy 服务不可用时，高风险来源默认进入隔离队列；无法识别用户或任务归属的事件不得推断成 Global Scope；幂等检查超时时可以接收事件，但必须标记 `DEDUP_PENDING`，在 Reflection 前完成二次去重。

### 4.2 Working Memory：当前任务的工作状态

Working Memory 不保存“最近 N 条对话”，而维护可继续执行的状态：

```json
{
  "task_id": "T-001",
  "session_id": "S-001",
  "current_goal": "整理目标 PDF 中的 Agent Memory 内容",
  "current_subgoal": "定位目标 PDF",
  "current_phase": "information_search",
  "current_plan": [],
  "active_entities": [],
  "active_constraints": [],
  "completed_steps": [],
  "pending_steps": [],
  "unresolved_questions": [],
  "temporary_facts": [],
  "current_tool_state": {},
  "retrieved_memory_refs": [],
  "recent_event_refs": [],
  "updated_at": "..."
}
```

Working State 的在线更新可以保存在 Hot Storage；只有 Checkpoint、Session Suspend、阶段切换和任务结束时才做完整持久化。

#### Working State 的更新语义

Working Memory 不是由模型每轮重新生成一份完整 JSON，而是采用“事件驱动的字段级更新”。每个更新都应说明更新来源、覆盖规则和版本前提：

```json
{
  "task_id": "T-001",
  "base_version": 17,
  "patch": [
    {"op": "replace", "path": "/current_subgoal", "value": "提取论文证据"},
    {"op": "add", "path": "/completed_steps/-", "value": "定位目标 PDF"},
    {"op": "remove", "path": "/pending_steps/0"}
  ],
  "event_refs": ["E-023"],
  "reason": "tool_result_confirmed"
}
```

字段的可信度应区别处理：用户明确给出的目标和约束只能由后续用户指令或显式冲突处理覆盖；工具结果可以更新文件路径、执行状态等可验证事实；模型推断出的临时事实必须带 `tentative=true`，不能直接升级为稳定约束。

为防止多应用事件并发覆盖，Working State 使用乐观锁或 Compare-And-Swap。若 `base_version` 过期，系统应基于字段级语义合并：集合字段去重合并，阶段字段按合法状态迁移，互斥约束进入冲突队列，不能简单采用最后写入覆盖。

Working State 的压缩也应是结构化压缩：优先删除已完成步骤的过程细节，保留目标、硬约束、未完成步骤、失败原因和关键产物引用。这样即使上下文压力触发压缩，也不会把“下一步做什么”压缩掉。

### 4.3 Task Boundary Detector：以事件驱动 Checkpoint

触发器包括：

| 触发器 | 判定示例 | 动作 |
|---|---|---|
| Context Pressure | 上下文利用率超过阈值 | 保存可恢复 Snapshot |
| Phase Change | 检索进入整理、整理进入生成 | 生成阶段 Checkpoint |
| Session Interrupt | 用户关闭或暂停任务 | 持久化恢复点 |
| Task Complete/Failed | 任务成功、失败或终止 | 生成 Final Episode |
| Explicit Checkpoint | 用户或 Agent 明确保存进度 | 立即创建 Checkpoint |

TTL 只能作为清理和保留策略，不能作为 Working → Episode 的唯一条件。

#### 边界判定策略与优先级

Task Boundary Detector 同时接收规则信号和模型判定信号。规则信号负责高确定性边界，例如任务完成、应用退出、用户显式暂停、上下文占用率越线；模型信号负责识别“研究转写作”“编辑转验证”等语义阶段切换。模型只能提出边界建议，最终由确定性策略确认，避免模型在每轮对话后都生成 Episode。

可采用以下判定分数：

```text
BoundaryScore =
  0.30*ExplicitSignal
+ 0.20*PhaseChange
+ 0.15*ContextPressure
+ 0.15*GoalShift
+ 0.10*ApplicationTransition
+ 0.10*IdleOrInterrupt
```

其中任务 `COMPLETED/FAILED` 和用户显式 Checkpoint 属于硬触发，不受阈值限制；上下文压力只触发恢复型 Checkpoint，不自动终结 Episode；短暂切换窗口不等于任务切换，需要结合 `task_id`、目标连续性和活跃实体判断。

连续触发应设置去抖窗口，并区分三类输出：

| 输出 | 何时使用 | 对 Episode 的影响 |
|---|---|---|
| `LIGHT_CHECKPOINT` | 上下文压力、周期性保护 | 只保存 Working Snapshot |
| `PHASE_CHECKPOINT` | 子目标或执行阶段变化 | 追加里程碑和阶段摘要 |
| `FINAL_CHECKPOINT` | 完成、失败、明确终止 | 关闭当前 Episode 并触发 Reflection |

这样既能保证任务可恢复，又不会生成大量没有语义价值的 Episode 碎片。

### 4.4 Task Episode：可恢复的任务状态机

Episode 采用“Snapshot + Append-only Events”结构：

```text
TaskEpisode
├── episode_id
├── task_id / user_id / session_id
├── goal / task_type / status
├── current_phase
├── milestones
├── completed_steps / pending_steps
├── important_observations
├── important_decisions
├── constraints / entities
├── artifacts / tool_results
├── unresolved_questions / failures
├── episode_summary
├── snapshot_version
├── evidence_refs
└── event_refs
```

Episode 状态：

```text
ACTIVE | SUSPENDED | COMPLETED | FAILED | ARCHIVED
```

Episode 的目标不是记录完整轨迹，而是让系统在跨会话后恢复“任务状态、约束、进度和下一步”。

#### Episode 的写入、恢复与关闭

Episode 采用 Append + Snapshot，不是把每次事件都重写到一行大 JSON 中。Append Event 负责保存可审计变化，Snapshot 负责快速恢复；两者通过 `snapshot_version` 和 `last_event_seq` 对齐。

```text
EpisodeEvent: GOAL_SET / STEP_STARTED / STEP_COMPLETED / DECISION_MADE
              CONSTRAINT_ADDED / ARTIFACT_CREATED / ERROR_OBSERVED
              PHASE_CHANGED / TASK_SUSPENDED / TASK_RESUMED / TASK_CLOSED
```

恢复任务时，系统先读取最近 Snapshot，再重放其后的事件，最后验证外部资源是否仍然存在。例如，记录中的文件可能已经被移动，工具会话可能已经失效，因此恢复结果要分成 `restored_state`、`stale_resources`、`required_revalidation` 三部分，而不是盲目把旧状态注入上下文。

Episode 关闭时至少生成四类摘要：目标与结果、关键决策、失败与修复、可迁移经验。前两类用于任务追溯，后两类才是 Reflection 的主要输入。原始事件由保留策略管理，不能把完整屏幕文本或工具输出永久复制到 Episode Summary。

对于并行子任务，可用 `parent_episode_id` 和 `branch_id` 建立分支。合并时只汇总已验证产物和未解决冲突，避免把两个分支的中间状态互相覆盖。

### 4.5 Reflection：从 Episode 提取候选，而非直接落库

Reflection Engine 输入 Episode，输出 0 到 N 个 Candidate：

```text
Episode
  → extract claims
  → normalize key
  → classify type
  → infer scope
  → attach evidence
  → compare related memory
  → create/update candidate
```

Candidate 最少包含：

```json
{
  "candidate_id": "C-001",
  "memory_type": "PREFERENCE",
  "claim": "用户正式报告偏好 DOCX",
  "normalized_key": "output.format.formal_report",
  "scope": "PROJECT:A",
  "confidence": 0.82,
  "utility": 0.70,
  "stability": 0.60,
  "frequency": 2,
  "task_impact": 0.80,
  "explicitness": 0.90,
  "evidence_refs": ["EV-001", "EV-002"],
  "supporting_episode_ids": ["EP-001"],
  "conflicting_memory_ids": [],
  "status": "ACCUMULATING"
}
```

Candidate 默认不进入 Retrieval；只有显式授权或 Fast Path 才可被临时使用，并必须标记为候选。

#### Reflection 与 Candidate 合并规则

Reflection 不应只做自由文本摘要，而要输出结构化主张，并回答五个问题：主张是什么、属于哪种类型、适用范围是什么、由哪些证据支持、与既有记忆是什么关系。抽取流程应先识别最小原子主张，再生成规范化键，防止一句话中多个事实被绑成不可演化的大段文本。

不同类型使用不同规范化方式：Preference 使用 `preference_dimension + value`，Semantic 使用 `subject-predicate-object`，Procedural 使用 `trigger + goal`，Episodic 使用 `problem_signature + environment`。规范化键相同不等于语义相同，系统还需比较条件、时间有效性和 Scope。

当新主张到来时，Candidate Store 依次执行：

```text
Exact-key Match
  → Semantic Near-duplicate Match
  → Scope Compatibility Check
  → Evidence Independence Check
  → Merge / Fork / Conflict / New Candidate
```

- `Merge`：语义、条件与 Scope 一致，只追加独立 Evidence；
- `Fork`：主张相似但适用条件不同，建立两个 Candidate；
- `Conflict`：同一条件下结论互斥，增加 ConflictPenalty 并等待更多证据；
- `New`：没有可合并对象，创建新 Candidate。

Evidence Independence 尤其重要：同一次对话被摘要、工具日志和 Episode Summary 重复引用，仍然只能算一个证据簇。可通过 `origin_event_id` 或 `causal_group_id` 聚合，避免 Frequency 被派生副本虚增。

Reflection 还应输出 `abstain_reason`。证据不清楚、Scope 无法判断、含有敏感内容或主张不可复用时，应允许输出 0 个 Candidate，这比强行“每个 Episode 都学到一点”更符合低幻觉目标。

### 4.6 Evidence-driven Consolidation：长期固化策略

长期记忆固化综合以下因素：

```text
Utility、Stability、Frequency、Confidence、TaskImpact、Explicitness、ConflictPenalty
```

第一版可使用可配置的线性评分：

```text
PromotionScore =
  0.20*Utility
+ 0.20*Stability
+ 0.10*Frequency
+ 0.15*Confidence
+ 0.15*TaskImpact
+ 0.20*Explicitness
- 0.20*ConflictPenalty
```

工程要求：

- 权重放配置，不写死在业务代码；
- Frequency 必须基于去重后的独立证据；
- Evidence 必须跨 Episode 关联，不能只依赖一次抽取；
- Score 只能辅助决策，不能绕过 Policy、Scope 和显式删除请求；
- 每次固化必须产生 Lineage，记录原因和证据。

#### Fast Path

对于明确、稳定、高价值且低风险的表达，可以跳过等待多次证据：

```text
明确指令 → Policy → Candidate → Fast Promotion → Long-Term
```

Fast Path 仍然必须保留 Evidence、Lineage 和来源可信度，不得成为无审计的直写通道。

#### 固化决策区间与可解释结果

Promotion Score 不是单一阈值的“过/不过”，而应划分决策区间：

```text
score >= T_promote 且无硬冲突       → CONFIRMED
T_review <= score < T_promote       → REVIEW 或继续 ACCUMULATING
score < T_review                    → 保留观察或 REJECTED
命中 Policy/Consent 硬约束          → BLOCKED，不计算 Fast Path
```

阈值可按类型分别配置。明确 Preference 可以更依赖 Explicitness；Semantic 事实更依赖来源可信度和可验证性；Procedural 需要成功执行证据；Episodic Experience 需要足够的任务影响和复用价值。不能用同一套权重处理所有长期记忆。

每次决策应生成可解释记录：

```json
{
  "decision": "ACCUMULATING",
  "score": 0.67,
  "threshold": 0.75,
  "positive_factors": ["explicit_user_statement", "high_task_impact"],
  "negative_factors": ["single_evidence_cluster", "scope_uncertain"],
  "next_evidence_needed": "同一项目下再次确认或用户显式授权"
}
```

Fast Path 只适用于用户明确表达长期意图、系统可以可靠确定 Scope、内容低风险且没有冲突的场景。诸如“记住这个密码”“这次先用 PDF”“也许我以后喜欢……”即使显式出现“记住”或偏好词，也必须分别被 Policy、临时 Scope 和不确定性规则拦截。

### 4.7 Long-Term Memory 的四种类型

#### Preference

```text
normalized_key + value + scope + confidence + valid_time
```

记录用户偏好，不记录安全规则。

#### Semantic

```text
subject + predicate + object + scope + validity
```

记录项目、环境、实体和配置等事实。

#### Procedural

```text
trigger + precondition + steps + verification + outcome
```

记录可复用的操作方法。它可以从多个成功 Episode 中抽象得到。

#### Episodic Experience

```text
problem + context + actions + outcome + lesson
```

记录有复用价值的历史案例，但不把所有任务日志长期保存。

Procedural 的形成路径：

```text
多个相似 Episodic Experience
  → Pattern Mining
  → 成功/失败对比
  → Procedure Candidate
  → Evidence Validation
  → Procedural Memory
```

#### 四类记忆的形成与更新差异

| 类型 | 主要证据 | 固化条件 | 典型更新 | 不应写入的内容 |
|---|---|---|---|---|
| Preference | 用户明确表达、稳定重复选择 | 意图和 Scope 明确 | REVISE、COEXIST | 一次性任务指令、安全策略 |
| Semantic | 工具结果、文件元数据、用户确认 | 来源可验证且有效期明确 | REVISE、SUPERSEDE | 未验证推断、纯观点 |
| Procedural | 多次成功 Episode、验证结果 | 步骤可复现且有成功证据 | REINFORCE、REVISE | 只成功一次的偶然操作 |
| Episodic | 高影响任务、失败修复、稀有案例 | 对未来任务具有检索价值 | ARCHIVE、抽象为 Procedure | 普通聊天和完整流水账 |

Preference 需要保存“偏好的对象、值、条件和强度”，例如“在课程报告中偏好 DOCX”，而不是只保存“喜欢 DOCX”。Semantic 必须带 `valid_from/valid_to` 或 `observed_at`，避免把旧的软件版本、路径和配置当作永恒事实。

Procedural Memory 应把步骤与验证条件绑定。只有“执行了什么”而没有“如何确认成功”的内容不能成为可靠流程；失败案例可以作为负向 Evidence，帮助完善前置条件和回滚步骤。Episodic Experience 则要保留问题情境与结果差异，使系统知道某个经验何时适用，而不是看到关键词相似就照搬动作。

四类记忆之间允许有来源关系，但不能互相替代。例如某次任务成功形成 Episodic，再由多个 Episodic 抽象出 Procedural；Procedure 的新版本仍需保留其来源 Episode 和验证记录。该跨类型演化通过 Lineage 表达，不通过修改 `memory_type` 原地变换。

### 4.8 Conflict Evolution：冲突是演化，不是简单覆盖

新候选与已有记忆比较后，使用以下动作：

| 动作 | 适用情况 |
|---|---|
| `REINFORCE` | 语义相同且证据支持原记忆 |
| `REVISE` | 同一 Scope 下内容有细化或修正 |
| `SUPERSEDE` | 新证据明确替代旧规则 |
| `COEXIST` | Scope 不同或条件不同，可并存 |
| `REVIEW` | 证据不足或无法确定关系 |

版本链必须可追溯：

```text
M1 --REVISE--> M2 --SUPERSEDE--> M3
```

读取时默认只装配当前有效版本；审计和研究场景支持 as-of 查询。

#### 冲突检测的判定顺序

冲突不应只用向量相似度判断。推荐依次比较 `normalized_key`、Scope、适用条件、有效时间和结论互斥性：

```text
同 Key + 同 Scope + 条件相同 + 结论一致     → REINFORCE
同 Key + 同 Scope + 条件相同 + 结论细化     → REVISE
同 Key + 同 Scope + 条件相同 + 结论互斥     → SUPERSEDE 或 REVIEW
同 Key + Scope 不同                         → COEXIST
同 Key + 条件不同                           → COEXIST，并保留 condition
时间区间不重叠                              → 版本序列，不视为同时冲突
```

`SUPERSEDE` 需要更强证据：用户明确纠正、权威工具结果或新版本配置可直接替代；仅凭模型抽取到一次相反表述，应进入 `REVIEW`。更新应在一个 Authority 事务中创建新版本、关闭旧版本、写 Lineage 和 Outbox，避免检索短暂返回两个“当前版本”。

检索层只负责按已确认关系解析冲突，不能偷偷修改长期记忆。若查询时发现未建模的冲突，应返回条件化结果并记录 `conflict_detected=true`，再异步触发 Evolution 流程。

### 4.9 Forget：遗忘是全链路治理动作

Forget 不是单条 SQL 删除，而是：

```text
Forget Request
  → Authority Tombstone
  → Candidate/Evidence 关系处理
  → Cache 清除
  → Vector/BM25 Projection 清除
  → Derived Context 清除
  → Forget Audit
  → Residual Retrieval Verification
```

审计只记录请求、范围、时间和结果，不在审计中重新保存被删除的敏感正文。

#### Forget 的范围、传播和验证

Forget Request 至少支持四种定位方式：按 `memory_id` 删除单条记忆，按 Entity/Key 删除某类知识，按 Scope 删除项目或应用记忆，按时间或来源撤回某批事件。请求进入执行前必须做身份校验、租户隔离和影响预览，避免一个模糊关键词误删整个用户空间。

删除过程采用“先阻断读取、后清理副本”的两阶段语义：

```text
Phase 1：Authority 写 Tombstone，检索立即过滤
Phase 2：异步清理 Candidate、Evidence 引用、Vector、BM25、Cache、离线特征
Phase 3：以原查询、改写查询和 ID 查询执行残留验证
Phase 4：完成审计；失败对象进入重试或人工处理
```

Evidence 被多个合法记忆共享时，不能因删除一条记忆而破坏其他记录，可删除关联边或对正文做不可逆遮蔽；如果用户要求删除源事件本身，则依赖它的记忆需要重新评估置信度，必要时降级、归档或一并删除。

备份和不可立即擦除的介质必须在 Policy 中说明延迟窗口和密钥销毁策略。对外返回的 `verification_status` 应区分 `READ_BLOCKED`、`PROJECTIONS_CLEARED`、`BACKUP_EXPIRY_PENDING` 和 `VERIFIED`，不能在异步副本尚未处理时直接宣称彻底删除。

---
## 5. B：Retrieval & Context 设计

### 5.1 统一 Retrieval Request

```json
{
  "user_id": "U-001",
  "task_id": "T-001",
  "session_id": "S-001",
  "query": "报告应该输出什么格式？",
  "current_goal": "完成项目报告",
  "current_subgoal": "确定交付格式",
  "current_phase": "result_generation",
  "active_entities": ["Project-A", "report"],
  "active_constraints": [],
  "application": "document_editor",
  "project": "Project-A",
  "domain": "reporting",
  "token_budget": 2000,
  "retrieval_mode": "default"
}
```

检索输入不再只有 Query，而是：

```text
Query + Task State + Scope + Current Context
```

#### 请求规范化与查询理解

Retrieval Service 接到请求后先补全上下文，而不是立即把 `query` 送入向量库。规范化阶段需要完成语言识别、时间表达解析、实体链接、指代消解和 Scope 绑定。例如“继续昨天那个报告”中的“昨天”“那个报告”必须结合当前用户、最近 Episode 和应用窗口解析。

查询理解输出可采用：

```json
{
  "normalized_query": "继续 Project-A 报告的结果生成阶段",
  "entities": [{"type": "project", "id": "Project-A"}],
  "temporal_filter": {"relative": "previous_day"},
  "required_facts": ["current_progress", "pending_steps", "output_constraints"],
  "scope_hints": ["TASK:T-001", "PROJECT:A"],
  "ambiguities": []
}
```

若 `task_id` 缺失，系统可以基于活动窗口、最近事件和目标相似度提出候选任务，但低置信度时不得把多个项目混检为一个任务。请求还要进行权限过滤：用户、设备、项目和应用是检索前置条件，不应等候选召回后再做数据隔离。

对空 Query 也要支持状态型检索。任务恢复、主动提醒和下一步建议可能只提供 Goal/Phase，此时由 `CURRENT_STATE` 或 `TASK_HISTORY` Intent 驱动，而不是构造一个虚假的自然语言问题。

### 5.2 Intent Router：统一七类意图

```text
CURRENT_STATE   当前做到哪一步
TASK_HISTORY    这个任务过去发生了什么
PREFERENCE      用户通常喜欢什么
SEMANTIC_FACT   某个事实是什么
PROCEDURE       遇到某类问题应该怎么做
EXPERIENCE      过去是否有类似案例
MIXED           需要多路组合
```

Router 输出 `RetrievalPlan`：

```text
intents
target_layers
target_types
preferred_scopes
filters
candidate_limit
strategy
```

#### Router 的判定、降级与多意图处理

Router 采用“规则优先、模型补充”的混合设计。带有明确 task/session 标识的恢复请求可由规则判为 `CURRENT_STATE`；“如何做”“之前是否遇到”等语义由轻量分类器或 LLM 判断。输出必须包含每个 Intent 的置信度和理由，不能只给一个标签。

```json
{
  "intents": [
    {"name": "PROCEDURE", "confidence": 0.72},
    {"name": "EXPERIENCE", "confidence": 0.61}
  ],
  "route_reason": ["how-to expression", "debugging context"],
  "fallback": "MIXED"
}
```

多意图不是简单扩大 `top_k`。Planner 应为各分支设置目标层、类型、通道与预算，再在融合阶段合并。例如故障排查同时检索当前 Working、同任务失败 Episode、相关 Procedure 和相似 Experience，但不会无差别召回 Preference。

当最高置信度低于阈值时，使用 `MIXED` 的保守计划，并限制长尾通道预算；当 Router 服务失败时，降级为 Lexical + Semantic + 当前任务过滤，同时记录 `router_fallback=true`。这样路由器提升效果但不成为系统单点故障。

### 5.3 Multi-channel Recall

不同记忆类型采用不同召回通道：

```text
Semantic Retriever
Lexical/BM25 Retriever
Metadata Retriever
Entity Retriever
Task Retriever
Scope Retriever
```

示例：

- Preference 优先使用 `normalized_key + scope + lexical`；
- Semantic 优先使用实体、属性和结构化字段；
- Procedural 优先使用 trigger、precondition 和步骤语义；
- Episodic 优先使用问题、环境、实体和结果相似度；
- Working 不需要重型向量检索，主要依赖 task、phase、recency 和 entity。

#### 分类型索引与候选融合

每个 Retriever 返回统一 Candidate Envelope：

```text
memory_id / layer / type / scope / version
channel / raw_score / normalized_score
matched_fields / match_explanation / projection_version
```

不同通道的原始分数不可直接相加。Vector 相似度、BM25 分数和结构化匹配分数需要先按通道做归一化，再使用 Reciprocal Rank Fusion 或学习融合产生候选池。第一版可采用 RRF，数据积累后再训练融合权重，避免一开始就依赖难以解释的复杂模型。

候选融合的正确顺序为：

```text
Parallel Recall
  → Per-channel Authorization Filter
  → Version/Tombstone Filter
  → Score Normalization
  → ID Deduplication
  → Near-duplicate Grouping
  → Fusion
  → Rerank
```

同一记忆从多个通道命中时保留通道贡献，但只占一个候选位置；同一版本链只保留当前有效版本。Projection Version 过期的候选要回源 Authority 校验，不能用旧索引正文直接构造 Context。

通道超时采用部分结果策略。Preference 的结构化通道失败时不能用无 Scope 的向量结果冒充等价替代；系统应降低结果置信度，并在 Trace 中明确缺失了哪些通道。

### 5.4 Unified Relevance Score

所有候选进入同一个可解释 Reranker：

```text
Relevance(m,q) =
  w_s*Semantic
+ w_l*Lexical
+ w_t*TaskAffinity
+ w_p*ScopePriority
+ w_r*Recency
+ w_c*Confidence
+ w_u*HistoricalUtility
+ w_e*EntityMatch
- w_x*ConflictOrStaleness
```

短期记忆不会因为层级名称自动获得固定高分；它只是通常在 Recency、TaskAffinity 和 Current Phase 上得分更高。

#### 评分特征的定义与校准

Reranker 的每个特征都要有稳定定义：Semantic 衡量查询与内容语义，Lexical 衡量关键词和规范化键，TaskAffinity 衡量 task/entity/phase 重合，ScopePriority 体现局部作用域优先级，HistoricalUtility 来自真实使用反馈，ConflictOrStaleness 则惩罚过期版本、低可信来源和未解决冲突。

评分前先执行硬过滤，评分后再做业务约束。权限、Tombstone、类型不兼容、有效期失效属于硬过滤，不能指望负权重把它们排到后面；多样性、同源去重和每类数量上限属于排序后约束。

为了让分数可比较，需要按 Intent 校准。例如 Procedure 查询中 TaskAffinity 不应压过 Trigger/Precondition 匹配，Preference 查询中 ScopePriority 应具有更高权重。推荐维护按 Intent 的权重配置：

```text
weights_version: retrieval-v3
intent: PROCEDURE
semantic: 0.22
lexical: 0.08
trigger_match: 0.18
precondition_match: 0.18
scope_priority: 0.10
historical_utility: 0.14
verification_success: 0.10
```

每次 Trace 保存特征快照和 `weights_version`，便于离线复现。权重调整先在固定 Benchmark 和历史 Trace 上回放，验证 NDCG、Scope Accuracy、Conflict Leakage 和延迟没有回退后再灰度发布。

### 5.5 Scope-aware Conflict Resolution

检索结果装配前必须先做冲突处理：

```text
TASK > PROJECT > APPLICATION > DOMAIN > GLOBAL
```

同一 Scope 下：

1. 优先当前有效版本；
2. 过滤已 `SUPERSEDED` 或 `DELETED` 的记录；
3. 对无法判断的冲突标记 `REVIEW`；
4. 可并存的不同条件记忆同时保留条件。

最终 Context 需要能表达“当前项目规则覆盖默认规则”，而不是只返回一串互相矛盾的文本。

#### Scope 解析结果的数据形态

Conflict Resolver 的输出不是简单删除低优先级项，而是生成“有效主张组”：

```json
{
  "normalized_key": "output.format.formal_report",
  "effective_memory_id": "M-PROJECT-A",
  "effective_scope": "PROJECT:A",
  "shadowed_memory_ids": ["M-GLOBAL"],
  "conditions": ["formal_report"],
  "resolution": "LOCAL_OVERRIDE",
  "explanation": "项目规则覆盖全局默认规则"
}
```

若不同 Scope 没有包含关系，例如 Project-A 与 Project-B，则只选择与当前请求绑定的 Scope；若请求没有项目信息，不得擅自选取最近使用的项目规则作为全局结果。条件互补的记忆可以同时进入 Context，但必须保留条件标签。

Scope 匹配应区分“完全匹配、祖先匹配、无关 Scope”。`PROJECT:A` 查询可以回退到 Application/Domain/Global，但不能回退到另一个 Project。Task Scope 只在同一个 task_id 中生效，任务结束后不会自动提升成 Project 规则。

### 5.6 Context Budget Manager

预算由 Intent、任务状态和总 Token 上限共同决定。例如：

```text
Current Working State       500 tokens
Relevant Episode            500 tokens
Preference/Semantic         300 tokens
Procedure/Experience        500 tokens
Provenance/metadata         200 tokens
```

该分配不是固定模板：

- 恢复任务时提高 Episode 预算；
- 个性化写作时提高 Preference 预算；
- 故障排查时提高 Procedure 和 Experience 预算；
- 预算不足时优先保留当前状态、约束、有效版本和高价值证据。

#### 预算分配与超限裁剪

Budget Manager 先预留系统指令和用户输入空间，再将可用预算分给记忆。每一类设置 `min_reserve`、`target_budget` 与 `max_budget`：最小配额保证关键 Working/Constraint 不被挤掉，目标配额用于正常分配，最大配额防止某个长 Episode 独占上下文。

```text
available = model_limit - system_prompt - user_input - generation_reserve
base_allocate(min_reserve)
remaining_allocate(intent_weight × candidate_utility)
unused_budget_redistribute()
```

裁剪单位应是语义块，而不是字符串尾部截断。Working State 按字段优先级裁剪；Episode 保留目标、决策、失败和待办；Procedure 保留触发条件、关键步骤和验证；Experience 保留问题、关键动作与教训。若一条内容压缩后仍超限，则回退为引用和一句摘要。

系统还应记录 `original_tokens`、`selected_tokens`、`compressed_tokens`、`dropped_reason`，以便判断问题来自召回不足还是预算挤压。Token Efficiency 不以越少越好，而以单位 Token 对任务成功的贡献衡量。

### 5.7 Context Builder：从记录拼接器升级为编排器

标准输出结构：

```text
[CURRENT WORKING STATE]
Goal / Current Step / Constraints / Pending

[RELEVANT EPISODE]
Previous Progress / Decisions / Failures / Open Questions

[USER AND PROJECT MEMORY]
Preference / Semantic Fact / Scope / Confidence

[RELEVANT PROCEDURE]
Trigger / Preconditions / Steps / Verification

[RELATED EXPERIENCE]
Problem / Context / Outcome / Lesson

[PROVENANCE]
Memory IDs / Evidence IDs / Version / Source
```

Context Builder 必须执行：

```text
Deduplication
  → Conflict Resolution
  → Priority Selection
  → Compression
  → Context Assembly
```

#### 上下文装配的质量约束

Context Builder 需要保证四个不变量：当前状态完整、约束不丢失、冲突已解释、来源可追溯。装配前把候选转为类型化 Context Item，而不是把数据库正文直接拼接到 Prompt：

```json
{
  "section": "RELEVANT_PROCEDURE",
  "content": "...",
  "scope": "DOMAIN:document_processing",
  "confidence": 0.88,
  "source_memory_ids": ["M-031"],
  "reason_selected": "trigger_and_precondition_match",
  "token_cost": 146
}
```

压缩必须是忠实压缩。对硬约束、数值、路径、否定词和步骤顺序设置保护标签；摘要模型不得把“不要覆盖原文件”压缩成“覆盖原文件”。关键结构化字段可以直接模板化渲染，减少二次生成错误。

Context Builder 的输出同时包含机器可读 `context_items` 与提供给 Agent 的文本 `rendered_context`。前者用于 Trace、评测和引用，后者用于推理。若没有可靠记忆，应返回空章节或明确 `no_reliable_memory`，而不是为了填满预算加入低分内容。

### 5.8 Activation 与 Retrieval Trace

每次成功或失败检索都记录：

```text
query_id
memory_id
task_id
intent
rank
initial_score
reranked_score
included_in_context
activated_at
agent_used
```

Activation 既是运行数据，也是后续 Utility Feedback 的基础。

#### 从“被检索”到“真正有用”的反馈链

Activation 至少区分四个状态：`RECALLED`（进入候选池）、`SELECTED`（通过排序）、`IN_CONTEXT`（实际装配）、`USED`（Agent 决策引用或行为受其影响）。只有 `IN_CONTEXT` 不能证明记忆有用，必须结合 Agent Usage Trace、任务结果和用户纠正判断 Utility。

正向信号包括：Agent 明确引用记忆、使用 Procedure 后验证成功、记忆帮助减少工具调用、用户确认结果符合偏好。负向信号包括：用户纠正、记忆导致失败、被 Context 选中但与任务无关、旧事实造成错误。负向信号不能直接删除记忆，而是触发降权、冲突检测或重新验证。

为避免“高排位更常被用、越用越高排位”的反馈回路，应保留小比例探索流量，并对位置偏差做校正。在线 Utility 更新设置上下限和时间衰减，重要 Preference 与显式事实不能因短期未使用就自动失效。

---
## 6. C：Memory Infrastructure 设计

### 6.1 Authority Store 与 Projection 分离

```text
Authority Store = 唯一事实来源
Vector/BM25/Cache = 可删除、可重建的 Projection
```

任何索引损坏都可以从 Authority Store 重建，不能把 Vector DB 当作唯一记忆库。

#### Authority 的不变量

Authority Store 不仅保存正文，还承担身份、版本、有效性、租户隔离和演化关系的最终裁决。任何读取结果在进入 Context 前，都应能回到 Authority 验证以下不变量：

```text
memory_id 在租户内唯一
content_version 单调递增
同一版本链同一时刻最多一个当前 ACTIVE 版本
DELETED/SUPERSEDED 不作为默认有效结果返回
每次固化至少关联一条可审计 Evidence
每次版本变化都有 Lineage 和 actor/reason
```

Authority 可采用关系数据库保存结构化元数据和事务关系，大正文或加密附件使用 Object Store，并在 Authority 中保存内容地址、哈希和密钥版本。不能把完整附件复制到每个索引；Projection 只保存检索必需的派生字段。

所有写操作通过应用服务和 Repository 完成。后台 Worker、Repair 和迁移工具也不能直接绕过领域不变量更新表，否则会出现索引看似修好、版本链却已经断裂的问题。

### 6.2 Canonical Storage Objects

```text
memory_events
working_states
task_episodes
episode_events
memory_candidates
long_term_memories
memory_evidence
memory_lineage
memory_activations
retrieval_logs
projection_outbox
audit_logs
forget_requests
```

逻辑上至少要能表达：

```text
Event → Working → Episode → Candidate → Long-Term
Memory ← Evidence
Memory ← Lineage
Memory → Activation → Retrieval Log
Memory → Projection Outbox → Vector/BM25/Cache
```

#### 对象职责与保留周期

| 对象 | 权威内容 | 典型保留策略 | 可否重建 |
|---|---|---|---|
| `memory_events` | 规范化事件与 Policy 结果 | 按来源和敏感级别分级 | 不完全可重建 |
| `working_states` | 当前在线状态及持久化快照 | 任务结束后转入 Episode/归档 | 可从 Snapshot+Events 部分恢复 |
| `task_episodes` | 任务状态、里程碑、结果 | 按任务价值和用户策略保留 | Snapshot 可由 Episode Events 重建 |
| `memory_candidates` | 待固化主张及聚合状态 | REJECTED 到期清理，CONFIRMED 保留 lineage | 可由证据重放但成本高 |
| `long_term_memories` | 当前及历史长期记忆 | 直到过期、归档或 Forget | 权威对象，不依赖 Projection 重建 |
| `memory_evidence` | 来源、可信度和因果分组 | 不短于所支撑记忆 | 部分可回源 |
| `memory_lineage` | 形成与版本演化关系 | 与记忆审计周期一致 | 不应依赖推断重建 |
| `projection_outbox` | 派生更新任务 | 完成后按审计窗口压缩 | 可由版本扫描补建 |
| `retrieval_logs` | 查询、候选、排序和装配 | 在线短保留、聚合指标长保留 | 不可完全重建 |

对象之间不要通过无约束 JSON 引用。核心关系使用外键或应用级完整性检查；跨存储引用至少保存 `target_id + target_version + tenant_id`，以便检测悬空引用和版本错配。

### 6.3 核心实体契约

#### Long-Term Memory Envelope

```json
{
  "memory_id": "M-001",
  "layer": "LONG_TERM",
  "memory_type": "PREFERENCE",
  "normalized_key": "output.format.formal_report",
  "content": {},
  "scope": "PROJECT:A",
  "status": "ACTIVE",
  "confidence": 0.91,
  "utility": 0.76,
  "valid_from": "...",
  "valid_to": null,
  "content_version": 3,
  "projection_version": 2,
  "evidence_refs": ["EV-001"],
  "created_at": "...",
  "updated_at": "..."
}
```

#### Evidence

```json
{
  "evidence_id": "EV-001",
  "source_type": "user_explicit|user_implicit|agent_action|tool_result|system",
  "event_id": "E-001",
  "episode_id": "EP-001",
  "task_id": "T-001",
  "content_ref": "...",
  "occurred_at": "...",
  "confidence": 0.95,
  "explicitness": 1.0,
  "source_location": "conversation:turn-8",
  "trust_level": "high"
}
```

#### Lineage

```text
from_memory_id
to_memory_id
relation
reason
evidence_id
timestamp
```

核心契约还应统一包含以下治理字段：

```text
tenant_id / user_id / created_by / updated_by
schema_version / content_version / policy_version
retention_class / sensitivity_level / encryption_key_id
created_at / updated_at / deleted_at
```

`schema_version` 与 `content_version` 必须分开：前者表示数据结构如何解析，后者表示业务内容修改了几次。迁移程序可以提升 schema_version 而不改变记忆语义，也不应触发一次虚假的 Memory Evolution。

Evidence 的 `content_ref` 默认指向经过 Policy 处理的片段或哈希，不强制复制原始敏感正文。Lineage 的 `relation` 至少覆盖 `DERIVED_FROM`、`REINFORCES`、`REVISES`、`SUPERSEDES`、`COEXISTS_WITH` 和 `DELETED_BY`，并明确关系方向。

### 6.4 Transaction 与一致性边界

Authority 写入采用强一致事务：

```text
BEGIN
  write Memory/Event/Candidate change
  write Evidence and Lineage
  write Idempotency record
  write Projection Outbox
COMMIT
```

索引采用最终一致：

```text
Authority DB = Strong Consistency
Vector/BM25/Cache = Eventual Consistency
```

外部检索必须能识别 Projection Lag，并在必要时回退到 Authority 查询。

#### 关键写事务与并发控制

需要强一致的不是“所有存储一次提交”，而是 Authority 内部的业务事实和待投影事件一次提交。典型固化事务为：

```text
锁定 Candidate 或执行 version check
  → 校验 Evidence、Policy、Scope 和冲突关系
  → 创建/更新 Long-Term Memory
  → 写入 Evidence Link 与 Lineage
  → 更新 Candidate 状态
  → 写入 Outbox（携带目标 content_version）
  → Commit
```

并发固化同一 Candidate 时，只有一个请求能从 `ACCUMULATING` 转为 `CONFIRMED`；其余请求读取已生成的 `memory_id` 幂等返回。并发更新同一记忆时采用 expected content_version，冲突请求重新加载最新版本并重新判断 REINFORCE/REVISE/SUPERSEDE，不能静默覆盖。

Projection Lag 回退应受 Intent 和延迟预算控制。结构化 Preference/Semantic 查询可直接回源 Authority；大规模向量相似检索无法完全回源时，系统返回旧索引候选前必须逐条校验版本，并标记结果完整性可能下降。

### 6.5 Projection Version 与 Outbox

每条 Memory 维护：

```text
content_version
projection_version
```

Outbox Worker 处理：

```text
DB Commit
  → Outbox Pending
  → Vector Projection
  → BM25 Projection
  → Cache Invalidation
  → Success/Retry/Dead Letter
```

`projection_version < content_version` 即表示索引过期。

#### Outbox 的投递语义

Outbox 采用至少一次投递，因此消费者必须幂等。事件键使用 `memory_id + projection_type + content_version`；Worker 只有在目标版本大于现有 Projection Version 时才更新，旧事件晚到时直接确认而不回滚索引。

```text
PENDING → PROCESSING → SUCCEEDED
                    └→ RETRY_WAIT → PROCESSING
                    └→ DEAD_LETTER
```

每次处理记录 `attempt_count`、`last_error_code`、`next_retry_at` 和 `worker_id`。重试采用指数退避和随机抖动；认证失败、schema 不兼容等永久错误直接进入 Dead Letter，并触发告警。Worker 崩溃留下的 `PROCESSING` 任务通过租约超时重新领取。

删除事件优先级高于普通更新。若 `DELETE v5` 已处理，而延迟的 `UPSERT v4` 才到达，消费者必须依据版本和 Tombstone 拒绝复活该 Projection。缓存失效也通过同一版本语义处理，避免数据库已更新但旧 Context 仍从缓存返回。

### 6.6 Repair Mechanism

RepairWorker 周期性检查：

```text
Missing Projection
Stale Projection
Orphan Projection
Deleted Memory Still Indexed
```

修复动作：

```text
rebuild / update / delete / replay outbox
```

Repair 必须幂等，并产生 Infrastructure Trace。

#### Repair 的扫描、修复与安全边界

Repair 分为在线点修复与离线全量校验。在线点修复由读取时发现的版本不一致触发，只修复指定记忆；离线校验按租户、分区和版本游标扫描，避免一次全库比对影响在线延迟。

检测规则至少包括：

```text
Authority ACTIVE 但缺少所需 Projection        → MISSING
Projection Version 小于 Content Version        → STALE
Projection 指向不存在或已删除 Authority        → ORPHAN
Embedding/Analyzer/Schema 版本过旧              → INCOMPATIBLE
同一 memory_id 出现多个当前 Projection          → DUPLICATE
```

修复前再次读取 Authority，防止扫描结果在排队期间已经过期；修复后执行读回验证并更新 `repair_status`。全量重建使用新索引别名：先构建和校验新版本，再原子切换读别名，保留短暂回滚窗口，避免在原索引上边删边建造成长时间不可用。

Repair 不能恢复已被 Forget 的正文。遇到 Tombstone 时只能删除派生对象；任何“根据旧向量反推文本”或从过期缓存回填 Authority 的行为都应被禁止。

### 6.7 Hot Storage 与 Episode 存储

- Working：Hot State + Authority Snapshot；微小变化无需每次建立向量索引；
- Episode：Snapshot + Append-only Events；Snapshot 用于快速恢复，Events 用于审计和重放；
- Candidate：独立存储，默认不可被普通 Retrieval 召回；
- Long-Term：结构化字段与文本字段并存，按 Type 选择 Projection。

#### 分层存储的读写路径

Working 的 Hot Storage 保存当前版本、过期时间和轻量字段，Authority Snapshot 负责恢复。Hot State 丢失时从最新 Snapshot + 后续事件恢复；恢复成功后生成新版本，不直接沿用可能已被其他会话占用的锁。

Episode 的 Append Event 按 `episode_id + seq_no` 唯一，写入必须有序且幂等。Snapshot 构建器读取一个确定的事件水位线，生成摘要后以 Compare-And-Swap 更新 `last_event_seq`；新事件可以继续追加，不阻塞长时间的摘要生成。

Candidate 不建立面向普通用户查询的公开向量索引，但可以建立内部的规范化键、Scope 和近重复索引，用于 Reflection 合并。内部索引同样受租户隔离和 Forget 约束。

Long-Term Projection 按类型差异化：Preference 建结构化键与 Scope 索引；Semantic 建实体/属性索引和语义索引；Procedural 建 Trigger、Precondition、Step 与验证字段索引；Episodic 建 Problem/Environment/Outcome 索引。公共 Envelope 只统一身份和治理字段，不强迫四类内容共享一个粗糙文本 schema。

### 6.8 Storage Adapter 与模块边界

上层通过接口访问存储：

```text
MemoryRepository
WorkingStateRepository
EpisodeRepository
CandidateRepository
EvidenceRepository
ProjectionRepository
RetrievalLogRepository
```

推荐代码边界：

```text
memory/
├── domain/
│   ├── event
│   ├── working
│   ├── episode
│   ├── candidate
│   └── longterm
├── application/
│   ├── ingestion
│   ├── reflection
│   ├── consolidation
│   ├── retrieval
│   ├── evolution
│   └── forget
├── infrastructure/
│   ├── database
│   ├── vector
│   ├── lexical
│   ├── outbox
│   ├── cache
│   └── security
└── interfaces/
    ├── rest
    ├── mcp
    ├── cli
    └── sdk
```

领域层不知道数据库；应用层不知道具体 API；接口层不重复实现记忆算法。

#### 模块协作与禁止依赖

领域层定义状态机、评分输入、Scope 和演化规则；应用层编排事务与外部服务；基础设施层实现数据库、索引、缓存和队列；接口层完成协议转换、鉴权和请求校验。模块之间通过命令、查询和领域事件协作。

建议明确以下禁止项：

- REST/MCP Handler 不得直接调用 Vector DB 并拼接 Context；
- Reflection 模型适配器不得直接写 `long_term_memories`；
- Projection Worker 不得根据索引内容反向修改 Authority；
- Dashboard 不得绕过授权查询其他用户的 Evidence；
- 评测代码不得依赖生产表的偶然字段，应使用稳定 Trace 契约。

接口契约需要版本化。新增字段优先保持向后兼容；改变 Scope、状态枚举或评分含义时提升 API/Schema Version，并提供旧数据迁移和双读验证。这样各阶段可以渐进替换原有实现，不必一次性重写全部模块。

---
## 7. D：Evaluation & Observability 设计

### 7.1 四层评测体系

| 层级 | 评测对象 | 关键问题 |
|---|---|---|
| Formation | A | 该记的是否记住，不该记的是否被过滤？ |
| Retrieval/Context | B | 是否找对、排对、装配对？ |
| Reliability | C | 是否不丢、不重、不乱，索引能否恢复？ |
| End-to-End | A+B+C | 是否真正提升 OS Agent 任务完成效果？ |

#### 评测数据集的组织方式

四层评测共享同一套场景主键和 Ground Truth，避免 Formation 用一批数据、Retrieval 又用另一批无法串联的数据。每个场景至少包含：

```text
scenario_id / user_profile / task_graph / event_sequence
expected_working_state / expected_episode_checkpoints
expected_candidates / expected_long_term_memories
expected_conflicts / expected_forget_scope
retrieval_queries / relevant_memory_ids / task_success_criteria
```

数据由三部分组成：人工构造的边界案例保证可控性，真实任务脱敏回放保证分布接近实际，合成扰动用于覆盖冲突、重复、长上下文和故障注入。训练、调参和最终测试按用户/项目/任务族隔离，防止同一个偏好或流程模板同时出现在训练和测试中。

所有指标按总体、记忆类型、Scope、任务长度和风险等级分桶报告。只看总体均值会掩盖 Global Preference 误写、长任务恢复失败等严重问题。每次评测固定模型版本、Prompt 版本、权重版本和数据集版本，并保存可重放 Trace。

### 7.2 Formation 指标

```text
Memory Precision = Correct Persistent Memory / All Persistent Memory
Memory Recall = Correct Persistent Memory / Ground-truth Memory
False Memory Rate = Incorrect Persistent Memory / All Persistent Memory
Premature Promotion Rate = Prematurely Promoted / All Promotions
Candidate Confirmation Accuracy
```

重点测试：

1. 一次性的“这次用 Word”不能成为 Global Preference；
2. 多次“正式文档使用 Word”应形成稳定 Preference；
3. 明确的“以后所有正式文档都用 Word”可走 Fast Path；
4. 不同 Project Scope 的规则应 COEXIST；
5. 用户主动 Forget 后不得再次形成同一敏感记忆。

#### Formation 的标注与误差分析

Ground Truth 不只标“应该记/不应该记”，还要标注目标 Layer、Type、Scope、形成时机和证据集合。系统在正确内容上选错 Scope，仍然属于形成错误；在证据不足时提前固化，属于 Premature Promotion；把同一证据副本算成多次支持，属于 Evidence Inflation。

建议增加分类型指标：

```text
Type Accuracy
Scope Accuracy
Evidence Attribution Precision
Evidence Independence Accuracy
Promotion Timing Error
Policy Leakage Rate
Abstention Quality
```

Formation Benchmark 以事件序列逐步回放，每一步记录系统状态，而不是只对最终数据库做静态比对。这样可以区分“从未形成”“形成太晚”“形成后被错误覆盖”和“正确形成但索引未更新”。

错误分析至少建立 `EXTRACTION_ERROR`、`SCOPE_ERROR`、`EVIDENCE_ERROR`、`POLICY_ERROR`、`CONFLICT_ERROR`、`TIMING_ERROR` 六类标签，并从 Trace 回溯到发生环节，为 A 层规则和模型提供可执行的改进输入。

### 7.3 Working/Episode 指标

```text
Goal Accuracy
Constraint Recall
Current State Accuracy
Step Completion Accuracy
Task Recovery Accuracy
Pending-step Recall
Constraint Preservation
```

测试长度建议覆盖 10、30、50、100 turns，并加入 Session Interrupt / Resume。

#### Working 与 Episode 的状态级评测

除了字段准确率，还要评估状态是否“足以继续执行”。可设置盲恢复实验：新的 Agent 只获得恢复接口输出，不获得原始对话，判断其能否正确说出当前目标、已完成步骤、下一步、硬约束和待验证资源，并继续完成任务。

Checkpoint Quality 可分解为：

```text
State Completeness：必要字段是否齐全
State Correctness：字段是否与事件一致
State Minimality：是否混入大量无关过程
Boundary Accuracy：Checkpoint 是否发生在正确边界
Resume Action Accuracy：恢复后的首个动作是否合理
```

故意加入窗口切换、并行子任务、重复工具结果、资源移动和会话异常退出，验证系统不会把应用切换误判为任务完成，也不会在恢复时继续使用已失效的文件句柄或工具会话。

### 7.4 Retrieval/Context 指标

```text
Intent Accuracy
Layer Routing Accuracy
Type Routing Accuracy
Recall@1 / Recall@5
MRR / NDCG
Scope Accuracy
Relevant Memory Precision
Context Recall / Context Precision
Conflict Leakage Rate
Context Compression Ratio
Token Efficiency
```

查询集必须包含：精确表达、改写表达、语义表达、跨域表达、长上下文、冲突查询和任务恢复查询。

#### Retrieval 与 Context 的分段诊断

一次检索失败要定位到具体阶段。Router 错误看 Intent/Layer/Type Accuracy；正确记忆未进入候选池看 Recall@K；进入候选但排序靠后看 MRR/NDCG；排位正确却被 Scope 过滤看 Scope Resolver；选中却未装配看 Budget Drop Rate；进入 Context 但 Agent 未使用则看 Context 表达和任务推理。

Context 指标定义为：

```text
Context Precision = Context 中相关且有效的 Item / 所有 Context Item
Context Recall    = 已装配的必要 Item / Ground-truth 必要 Item
Conflict Leakage = 未解释的互斥主张组 / 所有冲突查询
Constraint Loss  = 压缩后丢失的硬约束 / 原始硬约束
Citation Accuracy = 可正确回溯的 Item / 所有带来源 Item
```

离线排序指标和在线任务指标必须同时报告。NDCG 提升但 Task Success 不变，可能说明高分记忆并未被 Agent 有效表达；Task Success 提升但 Context Tokens 大幅增长，则要评估是否只是靠堆叠上下文获得效果。

### 7.5 Reliability 指标

```text
Write Latency
Search Latency
Context Build Latency
Projection Lag
Recovery Time
Index Repair Rate
Duplicate Event Suppression Rate
Forget Success Rate
Residual Retrieval Rate
```

故障注入至少覆盖：Vector 不可用、Outbox 重试、重复事件、服务重启、索引损坏和缓存失效。

#### Reliability 的故障注入矩阵

| 故障 | 预期系统行为 | 核心验收 |
|---|---|---|
| Vector 超时 | 使用部分通道或回源，Trace 标记降级 | 不返回越权或已删除内容 |
| Outbox 重复投递 | 消费者幂等确认 | Projection 不重复、不降版本 |
| Worker 处理中崩溃 | 租约到期后重新领取 | 最终完成且无双写副作用 |
| Authority 提交前崩溃 | 整个事务回滚 | 无半条 Memory/Lineage |
| Authority 提交后崩溃 | Outbox 留存并恢复投影 | 数据最终可检索 |
| Cache 未及时失效 | 版本校验拒绝旧值 | 不泄露 SUPERSEDED/DELETED |
| 全索引损坏 | 从 Authority 构建新索引并切换别名 | RTO/RPO 达标 |
| 重复 Event | 命中 idempotency_key | Frequency 和 Evidence 不增加 |

每个实验至少报告稳态性能、故障期间正确性、降级比例、恢复时间和恢复后残留错误。可靠性优先级是安全与一致性高于召回完整度：服务降级时可以少返回，但不能跨租户返回或复活已删除记忆。

### 7.6 End-to-End 与消融实验

至少比较：

```text
Baseline 0：No Memory
Baseline 1：Flat RAG Memory
Baseline 2：Original MemoryHub
System：Integrated MemoryHub vNext
```

任务覆盖：长任务、跨会话、偏好、冲突、流程学习和相似经验复用。

核心结果：

```text
Task Success Rate
Memory Accuracy
User Correction Rate
Average Tool Calls
Context Tokens
Latency
```

消融项：

```text
去掉 Candidate
去掉 Evidence Accumulation
去掉 Scope
去掉 Retrieval Router
去掉 Reranker
去掉 Episode State
```

#### 端到端实验协议

四个系统使用同一模型、同一工具权限、同一任务输入和尽可能相同的 Token/时间预算。每个任务进行多次重复，随机化运行顺序，并报告均值、方差和置信区间，避免把一次演示成功当作统计结论。

任务集建议至少包括：

| 任务族 | 关键能力 | 主要对照指标 |
|---|---|---|
| 跨会话文档制作 | Working/Episode 恢复 | Success、恢复时间、约束保留 |
| 多项目格式偏好 | Scope-aware Preference | 用户纠正率、Scope Accuracy |
| 软件配置变更 | Semantic 版本演化 | 过期事实使用率 |
| 重复故障排查 | Procedure/Experience 复用 | 工具调用数、修复成功率 |
| 敏感信息撤回 | Policy + Forget | Policy Leakage、Residual Retrieval |
| 长任务中断与分支 | Checkpoint/Branch | Resume Action Accuracy |

消融实验一次只移除一个机制，并保证其余配置一致。若移除 Candidate，需要明确变成“Reflection 直接固化”而非同时关闭 Reflection；若移除 Scope，需要保留相同候选池，以便归因冲突泄漏确实来自 Scope 机制。

结果不仅展示胜负，还要建立“设计点 → 中间指标 → 最终任务指标”的因果链。例如 Candidate 先降低 Premature Promotion，进而降低 User Correction，最终提升 Task Success；如果中间指标没有变化，就不能把最终波动归因于该创新。

### 7.7 五类核心 Trace

#### Formation Trace

```text
Event → Working → Episode → Candidate
      → Evidence Accumulation → Promotion Score → Memory
```

#### Evolution Trace

```text
M1 --REINFORCE--> M1
M1 --COEXIST----> Project-A M2
M1 --SUPERSEDE-> M3
```

#### Retrieval Trace

```text
Query → Intent → Plan → Candidates → Scores
      → Rerank → Conflict Resolve → Context
```

#### Agent Usage Trace

```text
Context Item → Agent Referenced / Ignored
             → Action Influenced
             → Tool Result / User Correction
             → Task Outcome → Utility Feedback
```

Agent Usage Trace 补上“检索正确但是否真正产生作用”这一段。它记录 Context Item ID 与 Agent 行为之间的引用关系、动作结果和用户反馈，不把“进入 Context”直接等同于“有用”。

#### Infrastructure Trace

```text
Memory Write → DB Commit → Outbox
             → Vector/BM25 Projection → Ready
```

#### Trace 的统一关联与采样策略

四类 Trace 通过 `trace_id`、`task_id`、`event_id`、`memory_id` 和 `query_id` 串联，形成从事件到任务结果的完整因果链。每个 Span 记录开始/结束时间、组件版本、输入摘要、输出 ID、状态码和错误分类，但默认不记录未经脱敏的正文。

```text
Task Trace
├── Formation Span
│   └── Candidate/Promotion Decision
├── Infrastructure Span
│   └── Authority/Outbox/Projection
├── Retrieval Span
│   └── Router/Recall/Rerank/Budget/Context
└── Agent Usage Span
    └── Action/Outcome/User Correction
```

错误、高风险 Policy、Forget 和评测流量全量采样；普通成功请求可按比例采样，但聚合指标必须全量计数。Trace 保留期与正文数据分离，日志中使用 ID、分类和数值特征，避免可观测性系统成为第二个未经治理的记忆库。

模型调用还需记录 `model_id`、`prompt_version`、`temperature`、`input_hash` 和输出结构校验结果，才能在升级模型后解释 Formation/Router 指标变化。

### 7.8 Dashboard 最小闭环

比赛展示和开发调试优先实现四页：

1. **Memory Explorer**：按 Type、Scope、Status、Confidence 和 Evidence 查看记忆；
2. **Memory Evolution**：展示形成、版本和冲突演化；
3. **Retrieval Debugger**：解释某次查询为何命中这些记忆；
4. **Benchmark Dashboard**：展示 Formation、Retrieval、Conflict、Task Success 和 Latency。

四页之间需要相互跳转。Memory Explorer 点击一条记忆可查看其 Evidence、Lineage、当前 Projection Version 和最近 Activation；Memory Evolution 可跳到形成它的 Episode；Retrieval Debugger 可查看每个通道、特征分数、冲突解析和预算裁剪；Benchmark 的失败样本可直接打开对应 Trace。

Dashboard 默认展示聚合和脱敏信息，查看原始 Evidence 需要更高权限并记录审计。比赛演示建议准备固定可重放场景，实时展示“事件进入—Candidate 累积—固化—冲突覆盖—检索解释—遗忘验证”，而不是只展示预先计算的总分图表。

### 7.9 Feedback Loop

```text
Memory Included
  → Agent Referenced/Used
  → Task Outcome
  → User Correction
  → Utility/Confidence Update
  → Retrieval Weight / Lifecycle Update
```

第一版可用规则和 LLM Judge 估计“是否使用”；关键指标必须保留原始 Trace，避免只保留一个不可解释的总分。

#### Feedback 的更新规则与防漂移

Feedback Processor 按事件类型更新不同对象：用户纠正触发冲突或置信度调整，任务成功更新 Procedure/Experience Utility，检索未使用主要影响排序特征，显式 Forget 则进入治理流程而不是负反馈分支。

所有自动更新设置最大步长、最小证据数和冷却期。单次任务失败不能立即废弃一条多次验证的 Procedure；连续多次失败且环境一致时，才创建 Revision Candidate。排序权重通过离线回放和灰度实验更新，记忆正文与状态变化仍通过 Evolution 状态机。

LLM Judge 只能作为弱标签，需用人工标注集校准并报告一致率。用户明确纠正和工具验证结果的权重高于 Judge 推测。对长期漂移定期监控 Utility 分布、不同用户群表现和 Scope 错误率，发现异常时可按 `weights_version` 或 `policy_version` 回滚。

---
## 8. 推荐的最小 API 契约

### 8.1 写入接口

```text
POST /memory/events
```

能力：接收事件、执行 Policy、去重、更新 Working，并返回：

```text
event_id
working_state_version
checkpoint_created
episode_id
candidate_ids
memory_ids
```

写入接口要求调用方提供 `request_id` 或 `idempotency_key`，重复请求返回第一次提交结果。默认采用同步接收、异步 Reflection：响应中的 `formation_status` 区分 `EVENT_ACCEPTED`、`WORKING_UPDATED`、`CHECKPOINT_CREATED` 和 `REFLECTION_PENDING`，避免调用方误以为一次 HTTP 返回已经完成长期固化。

错误码至少区分：schema 不合法、身份或 Scope 无效、Policy 拒绝、版本冲突和服务暂时不可用。Policy `DROP` 可以返回成功接收但明确 `memory_action=DROPPED`，同时不在错误信息中回显敏感正文。

### 8.2 检索接口

```text
POST /memory/retrieve
```

输入 `MemoryRetrievalRequest`，返回：

```text
intent
retrieval_plan
selected_memories
context
activations
trace_id
```

返回的 `selected_memories` 是结构化对象，包含 Type、Scope、Version、有效性、分数分解和来源 ID；`context` 是经过预算与冲突处理的渲染结果。调用方不得忽略结构化结果后自行把原始候选重新拼接。

接口支持 `consistency=EVENTUAL|AUTHORITY_CHECKED`。默认低延迟查询允许最终一致；涉及刚刚修改的偏好、Forget 验证和高风险事实时使用 Authority 校验。超时返回可用的部分结果，并通过 `degraded_channels`、`completeness` 和 `warnings` 说明降级情况。

### 8.3 任务恢复接口

```text
GET /memory/tasks/{task_id}/resume
```

返回 Working State + 最新 Episode Snapshot + 未完成步骤 + 当前约束。

恢复响应还应包含 `snapshot_version`、`last_event_seq`、`stale_resources`、`required_revalidation` 和 `resume_token`。Agent 首次续作携带 resume_token，服务以乐观锁把 Episode 从 `SUSPENDED` 转为 `ACTIVE`，防止两个设备同时无感知地恢复同一任务并互相覆盖。

### 8.4 遗忘接口

```text
POST /memory/forget
```

输入记忆范围、用户身份和授权信息，返回：

```text
forget_request_id
authority_status
projection_status
verification_status
residual_retrieval_count
```

Forget 是异步长事务。接口首次返回 `ACCEPTED` 和可轮询的请求 ID，另提供：

```text
GET /memory/forget/{forget_request_id}
```

状态依次为 `READ_BLOCKED`、`CLEARING_PROJECTIONS`、`VERIFYING`、`VERIFIED` 或 `PARTIAL_FAILURE`。请求必须支持 dry-run 影响预览，并要求调用方明确 Scope；对 Global 或批量删除需要更高授权和二次确认机制。

### 8.5 管理与诊断接口

为了支撑可观测和修复，可提供受限接口：

```text
GET  /memory/{memory_id}                    查看 Envelope、Evidence、Lineage
GET  /memory/tasks/{task_id}/episodes       查看任务 Checkpoint
GET  /memory/retrieval/{trace_id}           查看检索解释
POST /memory/projections/{memory_id}/repair 触发点修复
POST /memory/candidates/{candidate_id}/review 人工确认或拒绝
```

这些接口与用户检索接口使用不同权限，Evidence 正文默认脱敏。Repair/Review 等变更操作都需要 idempotency_key、actor、reason 和 Audit Log。

---
## 9. 分阶段实施与验收

### P0：语义和工程闭环

目标：让系统先“语义一致、可写、可读、可恢复”。

必须完成：

```text
统一 Layer/Type/Status/Activation
统一 MemoryEvent 和 RetrievalRequest
Working State
Episode Snapshot
Candidate 独立存储
Authority Store
Evidence / Lineage
Canonical Write Path
Canonical Retrieval Path
基础 Context Builder
基础 Formation/Retrieval 评测
```

验收标准：

- 任意入口都不允许绕过 Canonical Write Path 直写 Long-Term；
- Candidate 默认不可被普通 Retrieval 召回；
- 任务中断后可恢复 Goal、Current Step、Pending Steps 和 Constraints；
- Authority 数据可在索引损坏后重建；
- `/search`、`/context`、MCP 的结果来自同一 Retrieval Service。

建议用一条贯通样例完成 P0 验收：用户开始制作报告，系统更新 Working；阶段切换产生 Episode；一次性格式指令只进入 Candidate；任务中断后恢复目标与待办；索引删除后可从 Authority 重建；REST 与 MCP 对同一请求返回相同的 Memory ID 和版本。

P0 的非功能底线包括租户隔离、Policy 前置、幂等写入、可重放 Trace 和基础备份恢复。此阶段不追求智能评分最优，但不能留下“先直写、以后再治理”的临时旁路。

### P1：比赛核心创新

目标：让系统体现“自适应分层、证据固化和记忆路由”。

必须完成：

```text
Task Boundary Detector
Memory Reflection Engine
Evidence-driven Promotion
Fast Path
Scope-aware Conflict
Retrieval Intent Router
Unified Reranker
Context Budget Manager
Procedural Memory
Memory Evolution
```

验收标准：

- 一次性行为不会被过早固化为全局偏好；
- 多次独立证据可以推动 Candidate 固化；
- 局部 Scope 可以覆盖全局 Scope 但不删除全局记忆；
- 检索意图、目标 Layer 和 Type 可被 Trace 解释；
- Procedural Memory 能从重复成功 Episode 中形成。

P1 验收采用成对对照场景：

- 一次“这次用 DOCX”与多次“该项目正式报告用 DOCX”，验证 Candidate 和 Evidence 累积；
- Global“默认 Markdown”与 Project-A“正式报告 DOCX”，验证 COEXIST 和局部覆盖；
- 两次相似故障修复成功与一次失败路径，验证 Procedure 抽象包含 Preconditions 和 Verification；
- 同一问题分别以精确、改写和语义表达查询，验证 Router、多通道召回和统一排序；
- 预算受限时仍保留硬约束和当前步骤，验证 Context Builder 的语义裁剪。

每项既检查最终答案，也检查 Candidate、Evidence、Lineage、Retrieval Trace 等中间状态，确保演示效果确实来自目标机制。

### P2：增强能力

目标：提升长期性能、可靠性和展示效果。

可选完成：

```text
Utility Feedback
Memory Decay / Dormant
Adaptive Weight Tuning
Automatic Index Repair
Advanced Dashboard
LLM-based Evaluation
Graph-enhanced Retrieval
复杂 Pattern Mining
```

原则：P2 不应阻塞 P0/P1，也不应改变已经稳定的数据契约。

P2 能力按收益和风险灰度上线。Adaptive Weight、Memory Decay 和 LLM Judge 首先只读 Shadow Trace，不修改线上状态；达到离线指标和安全门槛后再小流量启用。Graph Retrieval 和复杂 Pattern Mining 使用独立 Projection，可随时关闭，不改变 Authority Schema。

### 推荐实施顺序

```text
Stage 0：冻结术语、实体和 API 契约
Stage 1：迁移 Working/Episode/Candidate/Authority Store
Stage 2：实现 Reflection/Consolidation/Scope Evolution
Stage 3：统一 Retrieval/Context/Activation
Stage 4：补齐 Outbox/Repair/Forget/Idempotency
Stage 5：建立 Benchmark/Trace/Dashboard/Feedback
```

### 迁移策略与交付物

实施采用“新旧双读对比、单写权威、逐步切流”：

```text
Stage 0  产出术语表、ADR、Schema、API、状态机与测试数据
Stage 1  旧数据映射到新 Envelope，建立 Working/Episode/Candidate 表
Stage 2  新 Formation 以 Shadow 模式运行，与旧写入结果比较
Stage 3  Authority 单写，旧检索与新检索双读但只使用旧结果
Stage 4  小流量切换新 Retrieval，监控正确性、延迟和冲突泄漏
Stage 5  全量切换后关闭旧写入，保留回滚读取窗口
```

旧数据迁移不能机械地把所有记录标成 LONG_TERM。最近消息应按保留策略清理或作为 Episode 来源，已有偏好需要补 Scope 和 Evidence，无法确定的记录进入 `REVIEW`，已有安全规则迁移到 Policy 配置而不是 Preference。

每个阶段的交付物至少包括代码、Schema Migration、回滚脚本、固定 Benchmark、Trace 示例、指标基线和运维手册。切流门槛采用绝对安全门槛加相对效果门槛：Policy Leakage、越权和 Forget 残留不得回退；任务成功、检索质量和延迟与基线比较后决定是否继续扩流。

---
## 10. 项目创新边界与答辩表述

不建议宣称“发明了三层记忆、向量检索或 Reflection”。这些属于已有研究中的常见思想。本项目应强调面向桌面 OS Agent 的系统级组合与工程化增量：

### 创新一：Task-state Hierarchical Memory

将基于时间窗口的 Short/Mid/Long 重构为：

```text
Working State → Task Episode → Persistent Experience
```

由 Context Pressure、Phase Change、Session Interrupt 和任务边界触发恢复与 Checkpoint，适配跨应用、长任务和跨会话执行。

### 创新二：Evidence-driven Memory Consolidation

长期记忆经过：

```text
Candidate → Evidence Accumulation → Promotion Policy
```

并综合 Utility、Stability、Confidence、Explicitness、Task Impact、Scope 和 Conflict，降低幻觉记忆与错误偏好固化。

### 创新三：Memory-aware Retrieval & Evolution

检索先识别 Intent，再按 Layer、Type、Scope、Task State 和版本有效性路由；新证据通过 Reinforce、Revise、Supersede、Coexist 和 Forget 让记忆可解释地演化。

### 工程创新补充

- Authority Store 与 Vector/BM25 Projection 分离；
- Evidence、Lineage、Activation 和 Trace 作为一等对象；
- Forget、Idempotency、Outbox、Repair 形成端侧可审计可靠性闭环；
- 用 Formation、Retrieval、Infrastructure 和 End-to-End 指标验证每个创新点。

推荐答辩表述：

> 本项目不是简单复现某一种记忆模型，而是针对桌面 OS Agent 的多应用、长任务、隐式偏好、端侧延迟和可控遗忘约束，将任务状态记忆、证据驱动固化、作用域冲突演化、意图路由检索和可恢复基础设施整合为一个可评测的闭环系统。

---
## 11. 最终方案的一页总结

```text
输入：用户交互、工具调用、文件操作、系统事件
  ↓
Policy + Normalize + Idempotency
  ↓
Working State：当前目标、阶段、约束、进度、待办
  ↓ checkpoint
Task Episode：可恢复的任务状态机和证据引用
  ↓ reflection
Candidate：待确认的偏好、事实、流程或经验
  ↓ evidence + scope + conflict + utility
Long-Term Memory：Preference / Semantic / Procedural / Episodic
  ↓ authority + outbox
Vector / BM25 / Cache Projection
  ↓ query understanding
Intent Router → Multi-channel Recall → Rerank
  ↓
Scope Conflict Resolution → Context Budget → Context Builder
  ↓ activation
OS Agent Decision / Action
  ↓
Formation Trace + Retrieval Trace + Usage Trace + Infrastructure Trace
  ↓
Benchmark / Feedback → Memory Evolution and Policy Tuning
```

最终要实现的不是“有一个记忆数据库”，而是：

> **一个知道何时记忆、知道记住什么、知道如何找回、知道为何这样决策、能够安全遗忘，并能用实验持续改进的 Adaptive Hierarchical OS Agent Memory System。**
