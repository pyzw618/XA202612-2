# VNEXT_PLAN.md

# 1. 文档定位

本文档是 MemoryHub vNext 优化工作的长期约束文档，用于描述 vNext 的目标架构、核心原则、阶段边界与最终完成标准。

它不是某一个 Stage 的执行清单，也不是临时任务记录。后续所有 Codex 会话在执行 vNext 相关任务前，都应优先阅读本文档，并以本文档作为架构边界。

除非明确进行架构决策更新，否则 Codex 不应主动修改本文档。

---

# 2. 项目背景

MemoryHub 是面向 OS Agent / Coding Agent / MCP Agent 的独立 Memory Runtime。

它不负责替代 Agent 的 Planner、ReAct、Tool Calling 或业务推理能力，而是负责：

- 记忆写入
- 记忆形成
- 任务状态维护
- 历史经历组织
- 长期记忆沉淀
- 记忆检索
- Context 构造
- 记忆演化
- 精准遗忘
- 安全治理
- 可观测性与灰度切换

当前系统长期记忆的 Authority 仍以现有 SQLite 数据层为主，Milvus、FAISS、BM25 等属于 Retrieval Projection，而不是最终事实源。

---

# 3. 当前架构状态

当前 MemoryHub 处于 Legacy + vNext 双轨状态。

Legacy 主链路大致为：

```text
Event
  ↓
Preference / Knowledge Extractor
  ↓
Preference / Knowledge
  ↓
Authority Storage
  ↓
Hybrid Retrieval
```

vNext 目标链路为：

```text
Raw Event
  ↓
Canonical Event
  ↓
Working State
  ↓
Task Episode
  ↓
Reflection
  ↓
Candidate
  ↓
Consolidation
  ↓
Long-Term Authority
  ↓
Intent-aware Retrieval
  ↓
Context
  ↓
Agent Usage
  ↓
Feedback / Evolution
```

vNext 的目标不是重新建设一套孤立的 Memory 数据库，而是重新定义：

> 什么信息值得成为记忆，以及记忆是如何形成、被使用和演化的。

---

# 4. vNext 核心领域模型

## 4.1 Event

Event 是系统最原始的行为或事实输入。来源可以包括：

- 用户对话
- Tool Call
- Tool Result
- 文件修改
- 命令执行
- 任务状态变化
- 用户显式 remember
- Agent 反馈
- 配置变化

Event 本身不等于长期 Memory。

## 4.2 Working State

Working State 描述：

> 当前任务现在处于什么状态。

典型内容包括 current goal、current step、completed steps、pending steps、constraints、active entities、current findings、blockers、recent failures、next action 等。

Working State 是面向“当前任务恢复”和“继续执行”的实时状态，不应退化为简单 Event Log。

## 4.3 Task Episode

Episode 描述：

> 一个任务或任务阶段发生过什么。

Episode 应组织任务目标、重要过程、关键工具调用、成功/失败结果、状态转折、重要决策、最终结果与可复用经验。

Episode 不是 Working Snapshot，而是任务经历。

## 4.4 Candidate

Candidate 表示：

> 系统认为可能值得长期记住的 Claim，但仍处于待证实状态。

Candidate 应尽量保留 Claim、Memory Type、Scope、Evidence、Contradictory Evidence、Confidence、Utility、Stability、Formation Source、Status 等信息；具体字段以现有 Domain Contract 为准，不为满足本文档额外建立平行模型。

Candidate 不等于“已经确认、仅等待写数据库的 Memory”。

## 4.5 Long-Term Authority

长期记忆至少包括：

- Preference
- Semantic
- Procedural
- Episodic

vNext 最终仍应通过 Long-Term Authority Facade 落入现有权威数据层，避免建立重复的长期事实源。

---

# 5. vNext 核心设计原则

## 5.1 Event 不等于 Memory

禁止默认采用：

```text
Event
→ LLM
→ Long-Term Memory
```

Event 首先应成为 Working / Episode 的输入。只有经过 Reflection、Candidate 和 Consolidation 后，才可能进入长期 Authority。

## 5.2 先 deterministic，后 LLM

可以通过 Event 类型、Tool Name、Tool Result、Status、File Path、Command Result 等确定的信息，应优先通过规则和 Reducer 处理。

LLM 主要用于多 Event 语义总结、隐含任务目标理解、跨事件模式识别、Candidate 生成、Memory Type 判断以及难以用规则判断的状态变化。

## 5.3 Formation 必须由语义边界驱动

vNext 不应长期保持“每一个 Event 都触发 Reflection”的模式。

目标模式：

```text
Event Stream
  ↓
Working / Episode 累积
  ↓
Meaningful Boundary
  ↓
Reflection
  ↓
Candidate
```

Boundary 可以来自 Task Start、Task Complete、Task Failed、User Explicit Remember、Significant State Change、Long-running Episode Checkpoint、Session Boundary 或手动触发。

## 5.4 Scope 是 Memory 的一等属性

Memory 不能只回答“内容是什么”，还必须回答“在哪个范围成立”。至少考虑 tenant、user、project、task、session、global。

禁止因为同一 Session 内重复出现同一行为，就轻易晋升为全局 Preference。

## 5.5 Candidate Promotion 必须证据化

Promotion 不应主要依赖简单 frequency。长期目标应考虑独立 Episode 数、来源多样性、显式程度、正向证据、反向证据、时间跨度、Scope 一致性和类型特定规则。

同一 Episode 内重复行为不应被当作多份独立证据。

## 5.6 Retrieval 必须利用多层 Memory

目标 Retrieval 不是单一 Vector Search。

```text
Intent
  ↓
Planner
  ↓
Working / Episode / Authority / Keyword / Vector / Metadata
  ↓
Fusion
  ↓
Rerank
  ↓
Scope Filter
  ↓
Context Budget
  ↓
ContextPayload
```

不同 Intent 应优先不同 Memory Layer，例如 CURRENT_STATE → Working、TASK_HISTORY → Episode、PREFERENCE → Preference Authority、PROCEDURE → Procedural、EXPERIENCE → Episode + Procedural。

## 5.7 Retrieval 与 Usage 必须闭环

被召回不等于有用。

目标链路：

```text
RECALLED
  ↓
SELECTED
  ↓
IN_CONTEXT
  ↓
USED
  ↓
OUTCOME
```

只有实际被 Agent 使用，并且对任务产生有效帮助的 Memory，才应该获得更高 utility / stability。

## 5.8 Legacy 与 vNext 必须可对照

vNext 不允许通过直接删除 Legacy 来证明自己成立。应保持 legacy、shadow、dual-read、canary、vnext 等切换与验证能力。

---

# 6. 当前阶段策略

当前 Formation 模式保持：

```text
candidate-only
```

Stage 1 不进行 vNext Long-Term Authority 全量接管。

Stage 1 优先解决：

```text
Event
  ↓
Meaningful Working State
  ↓
Meaningful Episode
  ↓
Boundary-triggered Reflection
  ↓
Candidate
```

---

# 7. 总体 Stage 划分

## Stage 1 — Formation 实化

目标：让 vNext 真正能够从真实 Agent Event 中形成有意义的 Working State、Episode 和 Candidate。

主要工作：

- 真实 Structured Reflection
- Event → Working State Reducer
- Episode enrichment
- Boundary-driven Formation
- Formation Scenario Tests

## Stage 2 — Retrieval 实化

目标：让 vNext Retrieval 真正利用 Working / Episode / Authority 等多层 Memory。

主要工作：

- Working Executor
- Episode Executor
- Authority Executor
- Keyword Executor
- Vector Executor
- Scope 传播
- Intent-aware planning
- Multi-channel fusion

## Stage 3 — Feedback 闭环

目标：建立 Memory 使用结果到 Memory 演化的反馈链。

主要工作：

- Activation 状态完整化
- USED 反馈
- Agent Outcome
- Utility 更新
- Stability 更新
- Memory Evolution

## Stage 4 — Evaluation & Cutover

目标：用真实 Benchmark 验证 vNext 是否优于 Legacy，并完成安全切换。

主要工作：

- Formation Benchmark
- Retrieval Benchmark
- Legacy vs vNext
- Shadow
- Canary
- Cutover

---

# 8. 全局 Codex 执行约束

## 8.1 先分析，后修改

每个新 Codex 会话首先执行 Codebase Reconnaissance，不得读取少量文件后立即开始大范围修改。

## 8.2 不允许跨 Stage 提前实现

当前 Stage 只处理当前目标，禁止为了“顺手优化”提前修改后续 Stage。

## 8.3 优先复用现有组件

如果已有 Repository、Service、Domain Contract、Boundary Detector、LLM Client、Safety Gate、Observability 等组件，应优先复用，禁止无必要建立平行体系。

## 8.4 控制修改范围

单个 Batch 原则上修改不超过 8 个核心源码文件。如果必须扩大范围，应先说明原因，不应直接扩散修改。

## 8.5 行为验收优先

验收应优先描述 Given / When / Then，而不是“新增某个类”“新增某个方法”。类与方法只是实现手段。

## 8.6 每个 Batch 必须停止

完成当前 Batch 后：运行测试、输出证据、更新 PROGRESS.md、停止。禁止自动开始下一个 Batch。

---

# 9. 最终完成标准

vNext 只有同时满足以下条件，才可视为真正完成：

1. Memory Formation 不再依赖逐 Event 直接长期抽取。
2. Working State 能稳定表达当前任务状态。
3. Episode 能恢复重要任务过程。
4. Candidate 能表达证据、Scope 和不确定性。
5. Retrieval 能基于 Intent 选择合适 Memory Layer。
6. Scope Leak 得到严格控制。
7. Memory 的实际使用结果可以反馈到 utility / evolution。
8. Legacy 与 vNext 可以通过 Benchmark 定量比较。
9. vNext 在关键指标上优于 Legacy。
10. 最终切换可以通过 Shadow / Canary 完成，而不是一次性替换。

---

# 10. 当前执行入口

当前优先执行：

```text
docs/vnext/stages/stage1-formation.md
```

所有 Codex 会话同时阅读：

```text
docs/vnext/VNEXT_PLAN.md
docs/vnext/stages/stage1-formation.md
docs/vnext/PROGRESS.md
```
