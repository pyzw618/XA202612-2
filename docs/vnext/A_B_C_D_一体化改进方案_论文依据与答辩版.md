# MemoryHub vNext：A/B/C/D 一体化改进方案（论文依据与答辩版）

> 本文以扩写后的《MemoryHub vNext：A_B_C_D 一体化改进方案.md》为唯一技术基线，结合 `os agent记忆模块调研/osmem.agent.final.md` 的论文调研结果，建立“方案机制—论文依据—项目增量—评测方式”的完整映射，供后续论文撰写、比赛答辩和评委追问时使用。论文发表状态与链接核验日期为 **2026-08-22**；技术实现若与本文表述冲突，以一体化方案中的 Canonical Contract、P0/P1/P2 边界和实测结果为准。

---

## 0. 使用说明：答辩时如何区分“借鉴”和“创新”

本项目不应把已有论文中的单个机制直接表述为“首次提出”。更稳妥、也更有说服力的表述方式是：

```text
已有论文机制
    ↓ 选择、组合、端侧化
MemoryHub 面向 OS Agent 的系统设计
    ↓ 实验验证
项目创新点
```

本文统一使用四种关系标记：

| 标记 | 含义 | 答辩用语 |
|---|---|---|
| `D：直接依据` | 论文已经明确提出相近机制 | “我们借鉴了……” |
| `C：组合依据` | 多篇论文分别提供局部机制，本项目进行系统组合 | “我们综合……形成……” |
| `T：可迁移方法` | 论文不专门研究 OS Agent Memory，但方法可迁移 | “我们将……迁移到桌面 OS 场景……” |
| `N：项目增量` | 论文没有直接给出完整方案，是本项目的组合、适配或新设计 | “我们的增量在于……” |

### 0.1 最重要的边界

论文提供的是经过研究验证的机制积木；本项目真正应主张的不是“发明了记忆、向量检索或 Reflection”，而是：

1. 面向桌面 OS Agent 的任务状态驱动分层；
2. 面向隐式行为和多源事件的证据驱动固化；
3. 面向 Scope、时间和冲突的可解释记忆演化；
4. 面向端侧延迟的意图路由和关系增强检索；
5. 面向可控遗忘、来源可信度和审计的统一治理运行时；
6. 将以上机制组织为一个可存储、可检索、可恢复、可评测的 A/B/C/D 闭环。

以上六项是设计机制边界，不等于答辩时要宣布六个“核心创新”。为与技术基线一致，正式答辩最终收敛为三项核心创新：Task-state Hierarchical Memory、Evidence-driven Consolidation、Memory-aware Retrieval & Evolution；端侧治理运行时和评测/可观测性作为两项工程与验证贡献补充。

### 0.2 证据等级说明

论文汇总中已经区分了正式发表、开源系统、Workshop 和 arXiv 预印本。答辩中应保留这一层次：

- **正式会议/期刊**：可说“论文提出/验证了该机制”；
- **Workshop 或开源系统**：可说“已有系统实现/工程先例”；
- **arXiv 预印本**：可说“近期研究提出/报告探索性结果”，不要说成已被顶会充分验证；
- **Venue Unverified**：只作为威胁模型或设计启发，不作为核心实验结论的唯一依据。

---

## 1. 一页总映射：A/B/C/D 分别对应哪些论文

### 1.1 A：Memory Formation

| 一体化方案机制 | 主要论文 | 关系 | 项目中的实际增量 |
|---|---|---|---|
| Event 标准化、统一摄入契约 | MemGPT；Generative Agents | D/C | 将自然语言、Tool Call/Result、OS 行为和配置统一为 OS Event 契约 |
| 写入期显著性门控 | Generative Agents；SimpleMem | D/C | 规则、Novelty、离线 LLM 灰区三档门控，适配端侧低延迟 |
| Working State 与上下文水位 | MemGPT；CCM；Synapse | D/C/T | 将工作上下文具体化为 Goal、Phase、Constraint、Pending Step 等可恢复状态 |
| Task Episode 与 Checkpoint | Zep/Graphiti；MemoryOS；CCM | C/N | 用 Task Boundary Detector 以阶段、会话和上下文压力触发 Episode，而不是仅按 TTL |
| Reflection 与 Candidate | Generative Agents；Mem0；MemoryBank；PersonaAgent | C | 将 Candidate 作为独立 staging area，禁止未确认候选污染正式检索 |
| 证据驱动固化 | MemoryBank；Mem0；ExpeL；PROV-AGENT | C/N | 跨 Episode 证据累积、Promotion Score、Fast Path 与 Lineage 统一起来 |
| Episodic → Procedural | Agent Workflow Memory；ExpeL；Generative Agents | C/T | 从重复成功 OS 操作轨迹中抽取可执行 Procedure |
| 长期记忆四类型 | MemoryBank；PersonaAgent；AWM；Zep | C/N | 明确 Preference、Semantic、Procedural、Episodic 的职责边界 |

### 1.2 B：Retrieval & Context

| 一体化方案机制 | 主要论文 | 关系 | 项目中的实际增量 |
|---|---|---|---|
| Intent Router | LongMemEval；BGE-M3；HyDE | C/N | 先识别 `CURRENT_STATE` 等七类意图，再决定 Layer、Type、Scope 和召回通道 |
| Multi-channel Recall | BGE-M3；HyDE；LongMemEval | C | dense、sparse、BM25、entity、task、temporal 和 preference 多路按需启用 |
| 关系增强召回（P2） | HippoRAG；A-MEM；Zep | C | 图只负责扩展候选，不直接加分，由精排器做最终裁决；不作为 P0/P1 闭环前提 |
| Unified Relevance/Fusion | BGE-M3；RRF；Generative Agents；MemoryBank | C/N | 先做通道归一化，再把 Scope、Task、Confidence、Utility、Conflict 纳入 RRF 或线性可解释重排 |
| Version/Scope 冲突解析 | Zep；STALE；Reliable Post-Retrieval Assembly | C/N | 同一 `(entity, slot, scope)` 只装配当前有效版本，保留历史和不确定状态 |
| Context Budget | LongLLMLingua；LLMLingua-2；Selective Context | C | 按 Intent 和任务阶段动态分配 Token Budget |
| 选择性注入/拒注 | RECOMP；Selective Context | D/C | Context Builder 可以拒绝无关记忆，而不是强行注入 Top-K |
| 上下文位置组织 | Lost in the Middle；CCM | C | 采用 Current State、Episode、Long-Term、Provenance 的结构化模板和双轨压缩 |

### 1.3 C：Memory Infrastructure

| 一体化方案机制 | 主要论文/系统 | 关系 | 项目中的实际增量 |
|---|---|---|---|
| 端侧 Hybrid Store | sqlite-vec；LEANN；Mem0 | C/T | SQLite + FTS/Vector/Cache 是推荐端侧部署剖面，不写死 Authority Store 的技术选型 |
| 轻量嵌入与量化 | MRL；RaBitQ；LEANN | C/T | 根据端侧预算选择维度截断、量化和两阶段检索，不把压缩方案写死 |
| Authority/Projection 分离 | WISE；Zep；SISA | C/N | 把关系数据库定义为唯一事实源，Vector/BM25/Cache 仅为可重建 Projection |
| Evidence/Lineage 一等实体 | PROV-AGENT；Zep；A-MEM | C/N | 记忆形成、版本、压缩、检索和删除都保留可回放关系 |
| Outbox、Version、Repair | 分布式一致性工程 + WISE/Zep 的分离思想 | T/N | 强一致 Authority + 最终一致 Projection + RepairWorker 形成稳定基础设施 |
| Idempotency | MemGPT 的统一写入契约；Mem0 的写入裁决 | C/N | 重复 OS 事件不重复放大 Frequency、Evidence 和 Promotion Score |

### 1.4 D：Evaluation & Observability

| 一体化方案机制 | 主要论文 | 关系 | 项目中的实际增量 |
|---|---|---|---|
| 长期记忆失败模式评测 | LongMemEval；MemoryAgentBench | D/C | 将对话记忆失败模式扩展到桌面 OS 多应用、Tool Result 和跨会话任务 |
| 冲突状态评测 | STALE；Reliable Post-Retrieval Assembly | C/T | 增加 Scope、版本链、隐式漂移和 Unknown Current 测试 |
| 遗忘评测 | TOFU；SeUL；RAG-Unlearning | C | 增加 Memory、Evidence、Index、Cache、Context 全链路残留验证 |
| 四层 Evaluation | 上述评测工作 + 本项目系统设计 | C/N | Formation、Retrieval/Context、Reliability、End-to-End 四层统一指标 |
| 全链路 Trace | Generative Agents；PROV-AGENT；Zep | C/N | 展示 Formation、Evolution、Retrieval、Agent Usage、Infrastructure 五种 Trace，并闭环反馈 |
| OS 专属 Benchmark | LongMemEval；MemoryAgentBench；OSWorld 可迁移场景 | T/N | 构造 OSMemBench：偏好漂移、跨应用、遗忘、Tool Result 和长任务混合负载 |

---

## 2. 机制贡献一：Task-state Hierarchical Memory

### 2.1 项目方案

```text
Working State → Task Episode → Candidate → Long-Term Memory
```

- Working Memory 表示当前 Goal、Subgoal、Phase、Constraint、Completed/Pending Steps 和 Tool State；
- Episode 表示可恢复的任务状态机，而不是普通摘要；
- Checkpoint 由 Context Pressure、Phase Change、Session Interrupt、Task Completion/Failure 和 Explicit Save 触发；
- Candidate 是长期记忆写入前的 staging area，不是第四个记忆层；
- Long-Term Memory 继续按照 Preference、Semantic、Procedural、Episodic 分类。

### 2.2 论文依据

| 机制 | 论文依据 | 关系 | 可以借鉴的具体内容 |
|---|---|---|---|
| 分层记忆与上下文换入换出 | MemGPT，ICLR 2024 | D | Main Context、External Context、上下文水位告警和函数化记忆操作 |
| STM/MTM/LTM 生命周期 | MemoryOS，EMNLP 2025 | D | 分层存储、热度/效用驱动的晋升与淘汰 |
| Episode 作为事件/证据层 | Zep/Graphiti，arXiv 2025 | D | Episode 层、时间有效性和事实来源组织 |
| GUI/任务状态压缩 | Synapse，ICLR 2024；CCM，ICLR 2024 | T/C | 将长轨迹压缩为任务相关状态，支持跨轮恢复 |
| 轨迹到工作流 | Agent Workflow Memory，ICML 2025 | D/T | 成功轨迹抽象为可复用工作流 |

### 2.3 项目真正的增量

已有工作分别覆盖分层、上下文管理、Episode 或工作流，但没有直接给出面向桌面 OS Agent 的完整链路：

```text
OS Event → Working State → Task Boundary Detector → Stateful Episode
        → Candidate → Evidence-driven Consolidation
```

因此答辩应说：

> 我们不是提出了“三层记忆”本身，而是将 MemGPT 的工作区、MemoryOS 的分层、Zep 的 Episode 和任务状态抽象组合为面向桌面 OS 的可恢复记忆状态机，并用 Task Boundary Detector 解决跨应用长任务何时形成 Checkpoint 的问题。

### 2.4 评测对应

```text
Goal Accuracy
Current State Accuracy
Task Recovery Accuracy
Pending-step Recall
Constraint Preservation
```

消融：去掉 Episode、去掉 Boundary Detector、改回最近 N 条对话，比较长任务和跨会话恢复效果。

---

## 3. 机制贡献二：Evidence-driven Memory Consolidation

### 3.1 项目方案

```text
Episode → Reflection → Candidate
        → Evidence Accumulation
        → Promotion Policy
        → Long-Term Memory
```

Candidate 记录：

```text
claim
normalized_key
memory_type
scope
confidence
utility
stability
frequency
task_impact
explicitness
evidence_refs
supporting_episode_ids
conflicting_memory_ids
```

Candidate 状态与正式长期记忆必须分开：

```text
ACCUMULATING | CONFIRMED | REJECTED | REVIEW
```

`CONFIRMED` 只表示候选通过固化判定；系统仍需创建独立 Long-Term Memory，并通过 Lineage 记录 Candidate、Evidence 与正式 Memory 的关系。普通 Retrieval 默认不得召回 Candidate。

长期固化不再是：

```text
LLM 抽取 → save()
```

而是结合证据、效用、稳定性、显式程度和冲突状态进行确认。

### 3.2 论文依据

| 机制 | 论文依据 | 关系 | 可以借鉴的具体内容 |
|---|---|---|---|
| Importance 门控与 Reflection | Generative Agents，UIST 2023 | D | 写入期重要性评分、反思触发、insight 的证据指针 |
| 强度强化与衰减 | MemoryBank，AAAI 2024 | D | Ebbinghaus 式强度、重复访问强化、长期衰减 |
| 抽取—对账—写操作 | Mem0，ECAI 2025 | D | 先抽取，再检索相关记忆并执行 ADD/UPDATE/DELETE/NOOP |
| 成功/失败轨迹对比 | ExpeL，AAAI 2024 | D | 通过 UPVOTE/DOWNVOTE 和成败对比治理经验规则 |
| Persona 回放校验 | PersonaAgent，Findings of ACL 2026 | D | 将记忆编译结果回放到任务中做自诊断 |
| 来源和派生链 | PROV-AGENT，IEEE e-Science 2025 | D | 使用 provenance、wasDerivedFrom 和实体关系记录来源 |
| 熵过滤与递归巩固 | SimpleMem，arXiv 2026 | D，预印本 | 源头过滤、递归压缩和后台巩固的设计启发 |

### 3.3 项目真正的增量

项目的增量不是单独发明“证据”或“候选”，而是将它们组成一个适合 OS 行为记忆的固化协议：

1. 证据必须来自去重后的独立事件或 Episode；
2. 候选必须与 Scope 和冲突关系绑定；
3. Promotion Score 综合 `Utility、Stability、Frequency、Confidence、TaskImpact、Explicitness、ConflictPenalty`；
4. Fast Path 可以缩短确认等待，但不得绕过 Policy、Evidence 和 Lineage；
5. Candidate 默认不可被正式 Retrieval 使用，避免“候选误当事实”。
6. Frequency 只统计去重后的独立证据簇；同一事件生成的日志、摘要和 Episode 引用不能重复计数；
7. Promotion 阈值按记忆类型配置：Preference 重 Explicitness，Semantic 重可验证来源，Procedural 重成功执行与验证，Episodic 重任务影响和复用价值。

推荐答辩表述：

> 现有工作已经分别提供了 Reflection、写入裁决、强度衰减和溯源机制。我们的工作是把它们统一到 Working–Episode–Candidate–Long-Term 管道中，使桌面 OS 中一次偶然行为不会直接变成全局偏好，而是通过跨任务证据积累后再固化。

### 3.4 评测对应

```text
Memory Precision
Memory Recall
False Memory Rate
Premature Promotion Rate
Promotion Precision/Recall
Candidate Confirmation Accuracy
```

重点案例：

- “这次用 Word”不应生成 Global Preference；
- 多次“正式文档都用 Word”应生成稳定 Preference；
- “以后所有正式文档都用 Word”可以 Fast Path；
- 多次成功处理同类故障可生成 Procedural Memory。

---

## 4. 机制贡献三：Long-Term Memory 的四类型与技能演化

### 4.1 项目方案

```text
Long-Term Memory
├── Preference      用户偏好
├── Semantic        用户/项目/环境事实
├── Procedural      可执行方法和技能
└── Episodic        有复用价值的历史案例
```

四种类型必须与 Lifecycle Layer 分开：

```text
Layer = 记忆处于 Working/Episode/Long-Term 哪个生命周期
Type  = Long-Term 记住的是偏好、事实、方法还是案例
```

### 4.2 论文依据与关系

| 项目类型 | 论文依据 | 关系 | 依据内容 |
|---|---|---|---|
| Preference/Semantic 区分 | MemoryBank；PersonaAgent | C | 长期记忆、用户画像和事实/偏好的区分 |
| Episodic Experience | Zep/Graphiti；Generative Agents | C | Episode、历史事件和 Reflection 结果 |
| Procedural Workflow | Agent Workflow Memory | D | 成功轨迹抽象为工作流 |
| 成败经验提炼 | ExpeL | D | 从成功/失败轨迹对比提取规则 |
| 动态关联与演化 | A-MEM，NeurIPS 2025 | D | 写入时建链、关联扩展和记忆演化 |

### 4.3 项目增量

论文分别提供了语义、案例或工作流机制；本项目把它们统一成 OS Agent 的长期类型契约，并明确：

```text
Episodic Experience × 重复成功模式
        → Procedural Candidate
        → 条件/步骤/验证方式
        → Procedural Memory
```

答辩时可说：

> 我们不是把所有历史都保存为 Knowledge，而是区分“用户喜欢什么、环境中什么是真的、遇到问题应该怎么做、过去类似问题如何解决”四种语义，并允许系统从重复成功经历中抽象出可执行流程。

---

## 5. 机制贡献四：Scope-aware Temporal Version 与 Conflict Evolution

### 5.1 项目方案

Scope：

```text
TASK > PROJECT > APPLICATION > DOMAIN > GLOBAL
```

演化动作：

```text
REINFORCE | REVISE | SUPERSEDE | COEXIST | REVIEW
```

长期状态：

```text
ACTIVE | DORMANT | SUPERSEDED | ARCHIVED | DELETED
```

其中 `SUPERSEDE` 是演化动作，`SUPERSEDED` 是被明确替代的旧版本状态；`REVISE` 动作通常生成新 ACTIVE 版本并将旧版本归档。二者不能共用一个枚举字段。

同一条记忆的历史不被覆盖，而是形成版本链；读取时只装配当前有效版本，查询历史时支持 as-of。

### 5.2 论文依据

| 机制 | 论文依据 | 关系 | 可以借鉴的具体内容 |
|---|---|---|---|
| 双时间轴、边失效、不物理删除 | Zep/Graphiti，arXiv 2025 | D | valid time、transaction time、失效边和 superseded_by |
| 写端冲突状态裁决 | STALE，arXiv 2026 | D，预印本 | KEEP/STALE/REPLACE/UNKNOWN 与隐式失效识别 |
| 读侧确定性装配 | Reliable Post-Retrieval Assembly，arXiv 2026 / COLM 2026 Lifelong Agent Workshop poster | D，Workshop/预印本 | 将证据抽取与策略执行分离，按明确版本元数据聚合当前值；适用边界主要是 current-value 查询 |
| 写入候选与 CRUD 更新 | Mem0，ECAI 2025 | D | ADD/UPDATE/DELETE/NOOP 的写入裁决骨架 |
| 定位—编辑—验证 | ROME，NeurIPS 2022 | T | 以 `(entity, slot)` 定位、编辑后验证的结构化思路 |
| 主存储—侧存储分离 | WISE，NeurIPS 2024 | T | Current/Archive 分离和查询路由思想 |

### 5.3 项目真正的增量

项目的增量包括：

1. 将 Scope 作为冲突判定的一等条件，区分“全局偏好”和“项目局部规则”；
2. 将 `COEXIST` 正式纳入演化协议，避免简单覆盖；
3. 将 `REVIEW` 作为写端演化动作，将 `UNKNOWN_CURRENT` 作为读侧 Resolver 输出或不确定性标记，而不是长期记忆状态；
4. 将 Preference 也建模成带 `value、valid_interval、scope、confidence、version` 的版本对象；
5. 将读侧确定性装配与写端关系裁决放入同一 Canonical Pipeline。

推荐答辩表述：

> Zep 提供了时间版本的基础，STALE 和 Reliable Post-Retrieval Assembly 提供了近期的冲突处理启发；我们的增量是把这些机制改造成面向 OS 场景的 Scope-aware 版本引擎，使“全局默认 Markdown”和“项目 A 使用 DOCX”能够共存。写端无法判定时进入 Review，读侧无法确定当前值时返回 Unknown Current，而不是让模型在冲突文本中自行猜测。

### 5.4 评测对应

```text
Conflict Classification Accuracy
Scope Resolution Accuracy
Version Evolution Accuracy
Unknown Current Precision
As-of Query Accuracy
```

案例：

```text
T1：Global = Markdown
T2：Project-A = DOCX       → COEXIST
T3：以后所有项目 = DOCX     → SUPERSEDE Global
```

---

## 6. 机制贡献五：Memory-aware Retrieval 与关系增强检索

### 6.1 项目方案

```text
Retrieval Request
  → Query Understanding
  → Intent Router
  → Retrieval Planner
  → Multi-channel Recall
  → Normalized Fusion / Explainable Rerank
  → Scope/Version Conflict Resolution
  → Context Budget / Context Builder
  → Activation + Trace
```

其中 P0/P1 的必选通道为 Semantic、Lexical/BM25、Metadata、Entity、Task 和 Scope；HyDE 查询扩展、Graph-Augmented Funnel 与 Cross-encoder Rerank 属于 P2 可选增强能力，必须在基础检索闭环稳定后按收益和延迟实测决定是否启用。

统一七类 Retrieval Intent：

```text
CURRENT_STATE
TASK_HISTORY
PREFERENCE
SEMANTIC_FACT
PROCEDURE
EXPERIENCE
MIXED
```

### 6.2 论文依据

| 机制 | 论文依据 | 关系 | 可以借鉴的具体内容 |
|---|---|---|---|
| 查询扩展 | HyDE，ACL 2023 | D | 用假设文档/改写弥合查询与记忆的表述鸿沟 |
| dense/sparse 多路 | BGE-M3，Findings of ACL 2024 | D | 单模型 dense、sparse、多路召回和重排漏斗 |
| 时间感知检索 | LongMemEval，ICLR 2025 | D | 时间解析、失败模式和 time-aware query expansion |
| 图扩散多跳召回 | HippoRAG，NeurIPS 2024 | D | 知识图和 Personalized PageRank 关联扩散 |
| 写入时建链 | A-MEM，NeurIPS 2025 | D | 记忆属性、动态链接和查询期关联扩展 |
| 三路混合与时序知识图 | Zep/Graphiti，arXiv 2025 | C | 关键词、语义、图和时间有效性结合 |
| 记忆流基础评分 | Generative Agents，UIST 2023 | D | relevance、recency、importance 三因素 |
| 价值与访问强化 | MemoryBank，AAAI 2024 | D | 强度、访问和衰减信号 |

### 6.3 项目真正的增量

论文已经分别给出混合召回、图扩散、时间检索和 RRF；项目的增量在于端侧 OS 约束下的统一路由和可解释融合：

1. `Intent-aware Routing`：按 Query Intent 只启用相关通道，避免所有通道全开；
2. `Explainable Fusion`：先归一化各通道分数，再将 Scope、Confidence、Utility、Recency 等特征用于统一排序；第一版可用 RRF/线性 Reranker；
3. `Graph-Augmented Funnel（P2）`：图扩展只产生候选，不直接提高最终分，避免图噪声污染排序；
4. `Temporal/Scope Hard Filter`：时间与作用域优先做硬约束；
5. `Activation Trace`：记录命中、注入和实际使用，支持后续 Utility Feedback。

### 6.4 推荐答辩表述

> 我们没有重新发明向量检索，而是针对 OS 查询中路径、应用名、快捷键、文件名和时间条件较多的特点，先建立按意图启用的结构化、语义和关键词多路检索，并加入 Scope/Version 过滤和端侧降级路径。HyDE、HippoRAG 和 A-MEM 提供的是 P2 查询扩展与关系增强依据，只有实测证明其收益大于延迟和噪声成本时才启用。

### 6.5 评测对应

```text
Intent Accuracy
Layer/Type Routing Accuracy
Recall@1 / Recall@5
MRR / NDCG
Scope Accuracy
Relevant Memory Precision
p50/p95/p99 Latency
```

延迟设计可引用调研报告中的 420ms 内部预算草案，但答辩时必须说明：

> 420ms 是系统设计预算分解，≤500ms 是项目目标，二者都不是论文已经证明或项目已经达到的结果；必须在目标设备上报告 p50/p95/p99、降级通道和数据规模。

---

## 7. 机制贡献六：Selective + Compressed Context Builder

### 7.1 项目方案

```text
Retrieved Memories
  → Select/Reject
  → Compress
  → Organize
  → Budget
  → Context
```

上下文结构：

```text
[CURRENT WORKING STATE]
[RELEVANT EPISODE]
[USER AND PROJECT MEMORY]
[PROCEDURE / EXPERIENCE]
[PROVENANCE]
```

### 7.2 论文依据

| 机制 | 论文依据 | 关系 | 可以借鉴的具体内容 |
|---|---|---|---|
| 选择性增强、允许拒注 | RECOMP，ICLR 2024 | D | 相关内容不足时输出空串/不注入，避免噪声增强 |
| 问题感知压缩 | LongLLMLingua，ACL 2024 | D | 依据 Query 和信息密度分配压缩预算 |
| token 分类压缩 | LLMLingua-2，Findings ACL 2024 | D | 蒸馏式 token 选择器和端侧压缩器 |
| 自信息删减 | Selective Context，EMNLP 2023 | D | 无训练的信息密度删减兜底 |
| 位置偏置 | Lost in the Middle，TACL 2024 | D | 关键内容的位置组织和“三明治”模板启发 |
| 跨轮压缩 | CCM，ICLR 2024 | D/C | Working/Archival 双轨和滚动压缩 |

### 7.3 项目真正的增量

1. 将选择、压缩、组织和预算统一到 Memory Context Contract；
2. 根据 OS Agent 当前阶段决定注入内容：规划阶段偏摘要和经验，工具选择阶段偏偏好和 API 先验，执行阶段偏路径、坐标和快捷键等精确细节；
3. 将 Scope Conflict Resolution 放在 Context Builder 之前；
4. 对结构化字段设置不可压缩白名单；
5. 用任务成败和用户纠正反馈校准拒注阈值。

### 7.4 推荐答辩表述

> 相关论文分别回答了“要不要注入、压缩多少、放在哪里、如何跨轮压缩”。我们将这四类机制组合成面向 OS Agent 的 Context Builder，并增加任务阶段、Scope 冲突、结构化字段白名单和任务结果反馈，使检索到的记忆不等于自动进入 Prompt。

### 7.5 评测对应

```text
Context Recall
Context Precision
Conflict Leakage Rate
Compression Ratio
Token Efficiency
Task Success Rate
```

---

## 8. 工程创新：Authority Store、Projection 与端侧 Hybrid Memory Store

### 8.1 项目方案

```text
Authority Store
  ├── Events
  ├── Working States
  ├── Episodes
  ├── Candidates
  ├── Long-Term Memories
  ├── Evidence
  └── Lineage
        ↓ Outbox
Vector Index / BM25 / Cache Projection
```

一致性边界：

```text
Authority DB = 强一致
Vector/BM25/Cache = 最终一致、可修复
```

### 8.2 论文和系统依据

| 机制 | 依据 | 关系 | 适用说明 |
|---|---|---|---|
| SQLite + Vector 混合 | sqlite-vec，开源扩展 | D/T | 单文件、端侧、关系字段和向量索引共存 |
| 低存储向量索引 | LEANN，MLSys 2026 | D/T | 个人设备上的低存储索引和按需重算 |
| 量化 | RaBitQ，SIGMOD 2024 | D/T | 低比特近似搜索和误差控制 |
| 可变维度嵌入 | MRL，NeurIPS 2022 | D/T | 根据端侧预算选择嵌入维度 |
| 语义缓存 | GPTCache，NLP-OSS 2023 | D | 相似查询缓存短路 |
| Vector + Graph 记忆层 | Mem0，ECAI 2025 | C | 结构化记忆、向量和图的组合先例 |
| Current/Archive 分离 | WISE，NeurIPS 2024 | T | 主存储与侧存储分离的可迁移思想 |
| 影响局部化 | SISA，IEEE S&P 2021 | T | 分区、局部重建和删除影响控制 |

### 8.3 项目真正的增量

Authority Store、Projection、Outbox、Repair、Projection Version 不是某一篇论文的直接复现，而是本项目为解决工程一致性问题做的系统设计：

1. Vector/BM25 损坏时可以从 Authority Store 重建；
2. `content_version > projection_version` 时可以确定索引过期；
3. Outbox 保证 Memory、Evidence、Lineage 和 Projection 更新请求同一事务提交；
4. RepairWorker 处理 Missing、Stale、Orphan 和 Deleted Projection；
5. Idempotency 防止 OS 重复事件放大记忆统计；
6. Working 采用 Hot Storage，Episode 采用 Snapshot + Append-only Events。

SQLite + sqlite-vec/FTS 是首选端侧部署剖面，而不是领域契约的一部分。若后续改用其他关系数据库或向量引擎，只要仍满足 Authority 强一致、Projection 可重建、版本可校验和 Forget 可传播，就不改变项目创新口径。LEANN 面向超大规模低存储场景，属于 P2 升级路径。

推荐答辩表述：

> 论文和开源系统提供了端侧混合存储、量化和缓存的技术基础；我们的工程增量是把“真实记忆”和“检索索引”分离，令索引可重建、写入可追踪、删除可验证，从而避免把向量库本身当作唯一事实来源。

### 8.4 评测对应

```text
Write Latency
Search Latency
Projection Lag
Recovery Time
Index Repair Rate
Duplicate Event Suppression Rate
Memory Loss Rate
```

---

## 9. 工程创新：Evidence、Lineage、Activation 与可观测性

### 9.1 论文依据

| 项目对象 | 主要依据 | 关系 | 项目用法 |
|---|---|---|---|
| Evidence | Generative Agents；PROV-AGENT | C | 记录原始事件、Episode、来源位置、可信度和显式程度 |
| Lineage | PROV-AGENT；Zep；A-MEM | C | 记录生成、修订、替代、摘要、合并和删除关系 |
| Activation | MemGPT；MemoryOS；RECOMP | C/N | 区分“长期记忆存在”和“本次被激活进入上下文” |
| Formation Trace | Generative Agents；PROV-AGENT | C/N | Event → Candidate → Memory 的形成过程 |
| Evolution Trace | Zep；A-MEM | C/N | 版本和冲突关系图 |
| Retrieval Trace | LongMemEval；BGE-M3；RECOMP | C/N | Query → Intent → Recall → Rerank → Context |
| Agent Usage Trace | 论文普遍缺少统一定义 | N | 记录记忆是否被引用、是否影响工具调用和任务结果 |
| Infrastructure Trace | 分布式一致性工程；PROV-AGENT | T/N | 记录 Authority Commit → Outbox → Projection → Ready/Repair |

### 9.2 项目真正的增量

项目把记忆对象从单一 `memory.text` 扩展为：

```text
Memory
  ← Evidence
  ← Lineage
  → Projection
  → Activation
  → Retrieval Log
  → Agent Usage Feedback
```

这样可以回答五个答辩中很有价值的问题：

1. 系统为什么记住这条信息？
2. 这条信息后来为什么被修改或替代？
3. 这次查询为什么命中了它？
4. 它进入上下文后是否真的帮助了 Agent？
5. Authority 写入后，索引是否按正确版本完成同步或修复？

---

## 10. 安全与遗忘：Controllable + Auditable Forgetting

### 10.1 项目方案

```text
Natural-language Forget Request
  → Intent Parsing
  → Scope Resolution
  → Target Identification
  → Dependency Analysis
  → Phase 1: Authority Tombstone / Read Block
  → Phase 2: Candidate/Evidence Relation + Vector/BM25/Cache Cleanup
  → Phase 3: Exact/Paraphrase/ID Probe Verification
  → Audit Log
```

Policy Engine 独立于 Preference Memory，至少支持：

```text
ALLOW | MASK | DROP | REVIEW
```

### 10.2 论文依据

| 机制 | 论文依据 | 关系 | 可以借鉴的具体内容 |
|---|---|---|---|
| 分区和影响局部化 | SISA，IEEE S&P 2021 | D/T | shard/slice、checkpoint 和局部重建 |
| 遗忘质量评测 | TOFU，COLM 2024 | D | forget/retain/neighbor 三类样本和探针验证 |
| Span 级选择性遗忘 | SeUL，AAAI 2025 | D | 敏感片段标注和部分遗忘 |
| RAG 知识库遗忘 | RAG-Unlearning，IEEE TDSC 2026 | D | 硬删除与抑制条目双通道 |
| 记忆投毒威胁模型 | MPBench，arXiv 2026 | D，Venue Unverified | 多写入通道、多漏洞和攻击面建模 |
| 来源绑定授权 | TMA-NM，arXiv 2026 | D，Venue Unverified | origin binding、trust level 和 action gate |

### 10.3 项目真正的增量

项目的主要增量是把以上机制统一成端侧 Memory Policy 和 Forget Runtime：

1. 从自然语言请求解析遗忘粒度：条目级、Span 级、概念级；
2. 沿 `derived_from`、摘要、Embedding、Cache 和 Lineage 关系做级联清理；
3. Authority 先写 Tombstone，Projection 异步清除并可验证；
4. Audit 只保存请求范围、影响清单、验证结果和日志哈希，不重新保存敏感正文；
5. 通过 Residual Retrieval Rate 和 Probe Leakage Rate 验证“删干净”。
6. 返回 `READ_BLOCKED`、`PROJECTIONS_CLEARED`、`BACKUP_EXPIRY_PENDING`、`VERIFIED` 或 `PARTIAL_FAILURE`，在异步副本尚未清理时不宣称彻底删除。

推荐答辩表述：

> 现有研究分别解决了分区删除、选择性遗忘、RAG 知识库删除和遗忘评测。我们的增量是将这些机制贯通到 OS Agent 的自然语言遗忘流程中，并把 Memory、Evidence、Vector、BM25、Cache、派生摘要和审计验证纳入同一个可追踪影响范围。

### 10.4 评测对应

```text
Forget Success Rate
Residual Retrieval Rate
Probe Leakage Rate
Forget Precision
Retain Utility
Deletion Latency
Poisoning Attack Success Rate
```

注意：MPBench、TMA-NM 等 Venue Unverified 研究只能作为威胁模型和设计启发，不能作为本项目安全效果的唯一证据。

---

## 11. D 层：评测设计与论文对应

### 11.1 Formation Evaluation

依据：Generative Agents 的 importance/Reflection、MemoryBank 的强化衰减、Mem0 的写入裁决、PersonaAgent 的回放诊断。

项目指标：

```text
Memory Precision
Memory Recall
False Memory Rate
Premature Promotion Rate
Candidate Confirmation Accuracy
Preference Calibration / ECE
```

### 11.2 Working/Episode Evaluation

依据：MemGPT 的工作上下文、MemoryOS 的分层、CCM/Synapse 的状态压缩，以及本项目的 Task Boundary Detector 和 Episode State Machine。

项目指标：

```text
Goal / Current State Accuracy
Pending-step Recall
Constraint Preservation
Boundary Accuracy
Task Recovery Accuracy
Resume Action Accuracy
```

采用盲恢复实验：新的 Agent 只获得恢复接口输出，不读取原始对话，检验其能否继续完成任务。

### 11.3 Retrieval Evaluation

依据：LongMemEval 的长期交互失败模式、BGE-M3 的多路召回、HippoRAG 的关联扩散、HyDE 的查询扩展。

项目指标：

```text
Recall@1 / Recall@5
MRR / NDCG
Intent Accuracy
Scope Accuracy
Relevant Memory Precision
Latency p50/p95/p99
```

### 11.4 Conflict Evaluation

依据：Zep 的时间版本、STALE 的失效状态、Reliable Post-Retrieval Assembly 的读侧装配、Mem0 的写入裁决。

项目指标：

```text
Conflict Classification Accuracy
Scope Resolution Accuracy
Version Evolution Accuracy
Unknown Current Precision
As-of Query Accuracy
```

### 11.5 Context Evaluation

依据：RECOMP 的拒注、LongLLMLingua/LLMLingua-2 的压缩、Lost in the Middle 的位置实验、CCM 的跨轮压缩。

项目指标：

```text
Context Precision
Context Recall
Conflict Leakage Rate
Compression Ratio
Token Efficiency
Task Success Rate
```

### 11.6 Reliability、Forgetting 与 Safety Evaluation

依据：SISA、TOFU、SeUL、RAG-Unlearning、MPBench 和 TMA-NM。

项目指标：

```text
Forget Success Rate
Residual Retrieval Rate
Probe Leakage Rate
Retain Accuracy
Poisoning ASR
Audit Completeness
```

可靠性还要覆盖：

```text
Projection Lag / Recovery Time
Duplicate Event Suppression Rate
Index Repair Rate
Version Regression Count
Cross-tenant Leakage = 0
```

故障注入至少包括 Vector 不可用、Outbox 重复投递、Worker 崩溃、缓存未失效、索引损坏和重复 Event。可靠性验收优先保证安全与一致性：降级时可以少返回，但不得返回越权、已删除或旧版本内容。

### 11.7 End-to-End 对照组

```text
Baseline 0：No Memory
Baseline 1：Flat Vector/RAG Memory
Baseline 2：Original MemoryHub
System：Integrated MemoryHub vNext
```

至少开展以下消融：

```text
w/o Episode
w/o Candidate
w/o Evidence Accumulation
w/o Scope/Version
w/o Retrieval Router
w/o Reranker
w/o Context Budget
w/o Forget Verification
```

四组系统使用同一模型、工具权限、任务输入和预算，多次重复运行并报告均值、方差与置信区间。消融一次只移除一个机制，同时保留其他候选池和配置不变，避免把多项变化错误归因于单个创新点。

### 11.8 OSMemBench：项目可主张的新评测方向

论文汇总指出，LongMemEval 和 MemoryAgentBench 已覆盖长期、增量式文本交互中的多类记忆能力，但没有完整覆盖桌面 OS 的多应用、文件与工具状态、跨会话任务恢复和遗忘传播。因此可把以下内容作为项目后续增强或潜在学术贡献：

```text
OSMemBench
├── Cross-application Preference
├── Tool-result-driven Experience
├── Long-horizon Task Recovery
├── Implicit Preference Drift
├── Scope-aware Conflict
├── Natural-language Forgetting
└── End-to-end Latency
```

答辩时应说“我们设计并构建面向 OS Agent 的评测集/测试集”，不要直接声称已经形成公开基准，除非完成数据发布和复现协议。

---

## 12. 六项机制如何收敛为三项核心创新和两项补充贡献

第 2～7 节按技术机制展开了六项贡献，但技术基线只主张三项核心创新。答辩时将四类型契约并入 Task-state Hierarchical Memory，将 Scope/Version/Conflict 与 Retrieval/Context 合并为 Memory-aware Retrieval & Evolution；基础设施治理和评测可观测性作为两项补充贡献。这样既保持技术文档完整，也避免核心创新数量在两份文档中不一致。

| 答辩定位 | 论文依据 | 组合/自研增量 | 主要指标 |
|---|---|---|---|
| 核心创新 1：Task-state Hierarchical Memory | MemGPT、MemoryOS、Zep、CCM、Synapse、AWM | OS 任务边界驱动的 Working–Episode–Candidate–Long-Term 闭环，并区分四类长期记忆 | 任务恢复、状态准确率、流程复用 |
| 核心创新 2：Evidence-driven Memory Consolidation | Generative Agents、MemoryBank、Mem0、ExpeL、PROV-AGENT | 跨 Episode 独立证据累积、Candidate staging、分类型 Promotion、Fast Path 保留溯源 | 偏好准确率、False Memory Rate、Premature Promotion |
| 核心创新 3：Memory-aware Retrieval & Evolution | Zep、STALE、Reliable Post-Retrieval Assembly、BGE-M3、LongMemEval、RECOMP；图增强为 P2 | Scope 共存、版本链、Intent Routing、可解释融合、冲突解析、预算与拒注闭环 | 冲突正确率、Recall/NDCG、as-of、Task Success |
| 工程贡献：Auditable On-device Memory Runtime | sqlite-vec、SISA、RAG-Unlearning、PROV-AGENT；LEANN/TMA-NM 为增强依据 | Authority/Projection 分离、Outbox/Repair、来源治理和全链路 Forget | 残留率、恢复时间、Projection Lag、可靠性 |
| 评测贡献：OS Memory Evaluation & Five Traces | LongMemEval、MemoryAgentBench、TOFU、OSWorld 可迁移场景 | Formation、Working/Episode、Retrieval、Reliability、End-to-End 评测与五类 Trace；OSMemBench 为待构建方向 | 各层指标、故障注入、消融、端到端成功率 |

### 12.1 三分钟答辩稿

> 我们的 MemoryHub vNext 不是把所有历史塞进向量库，而是构建了一条面向桌面 OS Agent 的完整记忆闭环。第一项核心创新是 Task-state Hierarchical Memory：借鉴 MemGPT 和 MemoryOS 的分层思想，把短期记忆改成当前任务状态，把中期记忆改成可恢复的 Task Episode，并由任务边界触发 Checkpoint，同时区分偏好、事实、流程和案例四类长期记忆。第二项核心创新是 Evidence-driven Consolidation：结合 Generative Agents、MemoryBank、Mem0 和 PROV-AGENT，引入 Candidate、独立证据累积和可追溯固化，避免一次偶然行为直接形成错误长期偏好。第三项核心创新是 Memory-aware Retrieval & Evolution：结合 Zep、STALE、BGE-M3、LongMemEval 和 RECOMP，统一 Scope/时间版本、意图路由、多路召回、冲突解析和上下文预算，让全局规则与项目规则能够共存，并避免过期记忆进入上下文。工程上，我们用 Authority Store、Outbox、可重建 Projection 和可审计遗忘保证端侧可靠性；验证上，通过 Formation、Working/Episode、Retrieval、Reliability 和 End-to-End 实验以及五类 Trace 证明每个机制的作用。我们的创新重点不是单个基础算法，而是针对 OS Agent 的系统级组合、端侧化和可验证闭环。

---

## 13. 评委常见追问与建议回答

### 问题一：你们和 Mem0 有什么区别？

建议回答：

> Mem0 为我们提供了“抽取—检索相关记忆—ADD/UPDATE/DELETE/NOOP”的写入裁决基础。我们的区别在于：MemoryHub 面向桌面 OS 的多源事件和长任务，引入 Working State、Task Episode、Scope、Evidence、Lineage、版本链和端侧 Authority/Projection 分离；Candidate 也不会直接等同于正式长期记忆。我们的贡献是把偏好、任务状态、流程经验和安全治理放进一个完整生命周期，而不是只做通用对话记忆写入。

### 问题二：你们和 MemoryOS 有什么区别？

建议回答：

> MemoryOS 提供了分层记忆和热度驱动生命周期的基础。我们的增量是把中期层明确建模为可恢复 Task Episode，并用 Task Boundary Detector 管理跨应用 OS 任务；同时增加 Candidate、证据固化、Scope 冲突、意图路由、Authority Store 和可审计 Forget。因此我们的研究重点是 OS 任务状态和完整闭环，而不是只实现 STM/MTM/LTM 三层。

### 问题三：你们的创新是否只是把多篇论文拼在一起？

建议回答：

> 我们明确把工作分成“论文依据”和“项目增量”。单个机制如 Reflection、混合检索和压缩并非原创；项目增量在于针对桌面 OS 的约束进行接口统一、Scope/时间语义组合、端侧延迟切分和全链路验证。我们会用消融实验分别去掉 Candidate、Scope、Router、Context Budget 等组件，证明系统级组合不是简单堆叠。

### 问题四：为什么不能直接把所有记忆做向量搜索？

建议回答：

> OS 查询中有大量实体、文件路径、应用、时间和作用域条件。纯向量搜索容易找回语义相似但版本错误、Scope 错误或已经失效的记忆。因此我们先做 Intent Routing 和结构化过滤，再做 dense/sparse/entity/temporal 多路召回，最后进行版本冲突处理和 Context Budget。向量只负责其中一个召回通道。

### 问题五：为什么需要 Candidate，不能抽取后直接写入？

建议回答：

> 用户一次“这次用 Word”可能只是任务局部要求，不能直接变成全局偏好。Candidate 允许系统先保留主张、Scope、置信度和证据，等待跨 Episode 重复或用户显式确认，再决定是否固化。这一机制的直接目标是降低 False Memory Rate 和 Premature Promotion Rate。

### 问题六：85%/88%/500ms 是已有结果，还是项目目标？

建议回答：

> 这三个数字是项目验收目标，不是论文替我们证明的结果，也不能在完成实验前表述为“已经达到”。我们将采用 No Memory、Flat RAG、Original MemoryHub 和 vNext 四组对照，在固定目标设备、数据版本、模型版本和预算下多次运行，分别报告偏好准确率、知识召回率、冲突正确率、p50/p95/p99 延迟和置信区间。每个创新点还会进行单变量消融；未达到目标时如实报告瓶颈和降级路径。

### 问题七：如果用户要求忘记，怎样保证真的删干净？

建议回答：

> Forget 先写 Authority Tombstone 并立即阻断读取，再异步清理 Candidate、Evidence 关系、Vector、BM25、Cache、派生摘要和 Context 缓存，最后用精确、改写和 ID 探针检查残留检索率。只有状态达到 VERIFIED 才能说在线副本已验证清除；若备份仍在到期窗口内，则明确返回 BACKUP_EXPIRY_PENDING。审计日志只保留请求范围、影响对象和验证结果，不重新保存敏感正文。

---

## 14. 论文证据边界：哪些内容答辩时要谨慎

| 论文/工作 | 使用建议 |
|---|---|
| Zep/Graphiti，arXiv 2025 | 可作为 Episode、双时间轴和混合检索的研究依据；标明是 arXiv/系统工作 |
| SimpleMem，arXiv 2026 | 可作为源头过滤和递归巩固启发；不要用作唯一实验依据 |
| STALE，arXiv 2026 | 可作为隐式冲突和 UNKNOWN 状态依据；核心指标需自行复现 |
| Reliable Post-Retrieval Assembly，arXiv 2026 / COLM 2026 Lifelong Agent Workshop poster | 调研早期简称“Deterministic Recipe”；可作为 current-value 装配依据，不能泛化为所有检索任务均有效 |
| RAG-Unlearning，IEEE TDSC 2026 | 可作为 RAG 知识库遗忘依据，同时要报告本项目实际残留率 |
| MPBench，arXiv 2026，Venue Unverified | 仅作记忆投毒威胁模型参考 |
| TMA-NM，arXiv 2026，Venue Unverified | 仅作来源绑定和授权门控参考 |
| sqlite-vec | 作为开源工程组件，不称作顶会论文 |
| GPTCache，NLP-OSS Workshop 2023 | 作为语义缓存工程先例，避免夸大为核心理论依据 |
| MemoryAgentBench，ICLR 2026 | 用于长期交互和冲突评测方法参考；OSMemBench 需要自己构建 |

---

## 15. 推荐引用优先级

### S 级：答辩和系统骨架优先精读

1. MemGPT，ICLR 2024：分层记忆、工作上下文和主动记忆管理；
2. Generative Agents，UIST 2023：Memory Stream、Importance、Reflection、证据指针；
3. Mem0，ECAI 2025：抽取—对账—CRUD 写入裁决；
4. MemoryBank，AAAI 2024：记忆强度、强化和衰减；
5. MemoryOS，EMNLP 2025：三级记忆生命周期；
6. Zep/Graphiti，arXiv 2025：Episode、双时间轴和版本化记忆；
7. BGE-M3，Findings of ACL 2024：dense/sparse 混合检索；
8. LongMemEval，ICLR 2025：长期记忆检索失败模式。

### A 级：支撑主要创新和指标

1. ExpeL，AAAI 2024：成败轨迹对比和经验规则治理；
2. Agent Workflow Memory，ICML 2025：轨迹到流程抽象；
3. A-MEM，NeurIPS 2025：写入建链和关联演化；
4. HippoRAG，NeurIPS 2024：图扩散和多跳关联召回；
5. RECOMP，ICLR 2024：选择性增强和拒注；
6. LongLLMLingua，ACL 2024：问题感知压缩；
7. Lost in the Middle，TACL 2024：上下文位置组织；
8. RAG-Unlearning，IEEE TDSC 2026：外部记忆遗忘。

### B 级：工程增强和安全扩展

1. MRL，NeurIPS 2022；RaBitQ，SIGMOD 2024；LEANN，MLSys 2026：端侧索引与压缩；
2. SISA，IEEE S&P 2021；TOFU，COLM 2024；SeUL，AAAI 2025：遗忘与验证；
3. PROV-AGENT，IEEE e-Science 2025：溯源与审计；
4. HyDE，ACL 2023：查询扩展；
5. LLMLingua-2，Findings ACL 2024；Selective Context，EMNLP 2023；CCM，ICLR 2024：上下文压缩和跨轮状态。

### 15.1 2025—2026 年高风险引用核验记录

下表只核验“条目是否存在、当前发表层级是什么”，不代表项目可以直接继承论文中的效果数字。正式论文或答辩稿应使用完整 BibTeX/脚注，不要只写系统简称。

| 工作 | 截至 2026-08-22 的核验状态 | 答辩口径 |
|---|---|---|
| [MemoryOS](https://aclanthology.org/2025.emnlp-main.1318/) | EMNLP 2025 Main，DOI `10.18653/v1/2025.emnlp-main.1318` | 可说“论文提出三级记忆管理”，OS 适配是本项目增量 |
| [PersonaAgent](https://aclanthology.org/2026.findings-acl.1315/) | Findings of ACL 2026，DOI `10.18653/v1/2026.findings-acl.1315` | 可支撑 episodic/semantic memory 与 test-time preference alignment |
| [MemoryAgentBench](https://openreview.net/forum?id=DT7JyQC3MR) | ICLR 2026 Conference Paper | 可支撑增量多轮记忆能力评测，不等同于 OS 桌面基准 |
| [Agent Workflow Memory](https://proceedings.mlr.press/v267/wang25bx.html) | ICML 2025，PMLR 267 | 可支撑成功轨迹到 workflow 的抽象 |
| [A-Mem](https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html) | NeurIPS 2025 Main Conference | 可支撑写入建链与记忆演化；图增强在本项目中属 P2 |
| [LEANN](https://proceedings.mlsys.org/paper_files/paper/2026/hash/e27ea0cd50b798ff8942caf9203f0992-Abstract-Conference.html) | MLSys 2026 | 仅作为大规模低存储索引升级路径，不是 P0 依赖 |
| [Mem0](https://dblp.org/rec/conf/ecai/ChhikaraKASY25.html) | ECAI 2025，DOI `10.3233/FAIA251160` | 可说“抽取、固化和检索架构依据”，不能把项目 Scope/Episode 说成 Mem0 已提供 |
| [Reliable Post-Retrieval Assembly](https://arxiv.org/abs/2606.01435) | arXiv 2026；COLM 2026 Lifelong Agent Workshop poster | 结论边界是带明确版本元数据的 current-value 问题，不宜泛化 |
| [STALE](https://arxiv.org/abs/2605.06527) | arXiv 2026 预印本 | 可作隐式冲突和 CUPMem 设计启发，效果需本地复验 |
| [SimpleMem](https://arxiv.org/abs/2601.02553) | arXiv 2026 预印本 | 可作压缩、递归巩固和自适应检索启发 |
| [MPBench](https://arxiv.org/abs/2606.04329) | arXiv 2026 预印本 | 只作记忆投毒威胁模型和安全评测参考 |
| [TMA-NM](https://arxiv.org/abs/2606.24322) | arXiv 2026 预印本 | 只作来源绑定与 act gate 启发，不把其 0% ASR 当作本项目结果 |
| [When Machine Unlearning Meets RAG](https://doi.org/10.1109/TDSC.2025.3620832) | IEEE TDSC 23(2), 2026 | 文中“RAG-Unlearning”的正式题名；可迁移知识库级行为遗忘思路 |

---

## 16. 最终答辩落点

### 16.1 一句话版本

> MemoryHub vNext 以已有记忆研究为机制基础，针对桌面 OS Agent 的长任务、多应用、隐式偏好、低延迟和可控遗忘约束，构建了 Working–Episode–Candidate–Long-Term 的任务状态驱动记忆闭环，并用 Scope-aware Evolution、Memory-aware Retrieval 和可审计端侧基础设施实现形成、使用、演化和验证的一体化。

### 16.2 不能混淆的三件事

```text
论文已有机制 ≠ 项目原创
组合和 OS 适配 ≠ 简单复制
设计预算/预期收益 ≠ 已经实测的实验结果
```

### 16.3 项目创新的最稳妥表述

```text
已有工作提供机制依据
本项目完成 OS 场景化组合和端侧工程化
通过消融、对照、延迟和遗忘实验验证系统增量
```
