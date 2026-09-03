# MemoryHub vNext：A/B/C/D 一体化执行任务方案

> 方案依据：[MemoryHub vNext：A/B/C/D 一体化改进方案](./MemoryHub%20vNext：A_B_C_D%20一体化改进方案.md)
>
> 文档用途：研发排期、任务领取、联调验收、切流决策与比赛交付
>
> 计划版本：v1.0
>
> 编制日期：2026-08-22
> 计划口径：相对周（W1 起），实际启动时由项目负责人替换为具体日期

## 1. 执行结论

本次改造采用“**契约先行、Authority 单写、Shadow 验证、双读对比、逐步切流**”的方式实施，不进行一次性推倒重写。

交付顺序固定为：

```text
S0 契约冻结
  → S1 Authority 与任务状态闭环
  → S2 Reflection、Candidate 与证据固化
  → S3 统一 Retrieval 与 Context
  → S4 Outbox、Repair 与 Forget 可靠性闭环
  → S5 评测、Dashboard、迁移与全量切流
```

本计划的硬性完成条件是：

1. 所有写入口统一进入 Canonical Write Service，不允许直接写长期记忆或索引；
2. Working State、Task Episode、Candidate、Long-Term Memory 具有明确的数据契约和状态机；
3. `/search`、`/context`、MCP、CLI 和 SDK 复用同一个 Retrieval Service；
4. Authority Store 是唯一事实来源，Vector、BM25、Cache 可删除并重建；
5. Candidate 默认不能被普通检索召回；
6. Forget 后 Authority 立即阻断读取，Projection 异步清除并完成残留检索验证；
7. P0/P1 场景全部通过，核心 Trace 能解释“为何形成、为何召回、是否被使用”；
8. 新旧链路完成双读对比和回滚演练后，才能关闭旧写入路径。

## 2. 范围、优先级与资源假设

### 2.1 交付范围

| 优先级 | 目标 | 必须交付的能力 |
|---|---|---|
| P0 | 语义和工程闭环 | 统一契约、Working、Episode、Candidate、Authority、Evidence/Lineage、Canonical Write/Retrieval、基础 Context、基础评测 |
| P1 | 核心创新闭环 | Boundary、Reflection、Evidence Promotion、Fast Path、Scope Evolution、Intent Router、Reranker、Budget、Procedural Memory |
| P2 | 增强与展示 | Utility Feedback、Decay、Adaptive Weight、自动 Repair、高级 Dashboard、LLM Judge、Graph/Pattern Mining |

P0 和 P1 是正式交付范围；P2 只有在 P0/P1 退出门槛全部通过后才进入上线队列。

### 2.2 非目标

- 不在本轮替换底层大模型供应商；模型通过现有 `memoryhub/llm/` 抽象接入。
- 不在本轮重写 Milvus/FAISS/Kylin SDK 适配器，只补齐统一 Planner、版本校验和降级语义。
- 不把 Dashboard 作为新的业务写入口。
- 不机械地把现有 `short/mid/long` 字段改名后宣称完成；必须落地状态、事务、恢复和验收语义。
- 不在 P0/P1 阶段引入会改变 Authority Schema 的 Graph Memory。

### 2.3 默认资源假设

计划按 8 个自然周、3 条并行工作流估算。角色不等于固定人数，小团队可以一人兼任多个角色。

| 角色 | 主要职责 |
|---|---|
| BE-A：Formation/Domain | Event、Working、Episode、Candidate、Reflection、Consolidation、Evolution |
| BE-B：Retrieval/Infrastructure | Retrieval、Context、Outbox、Repair、Forget、迁移与切流 |
| QA/Eval | 契约测试、数据集、故障注入、指标、Trace 与验收报告 |
| Client/UX | REST/MCP/CLI/SDK 契约同步、桌面 Dashboard、演示场景 |
| Tech Lead | ADR、Schema/API 审核、阶段 Gate、风险与切流决策 |

若只有 1 名开发者，应保持任务依赖顺序执行，预计需要 14～18 周；不得通过跳过契约、迁移验证或故障演练压缩周期。

## 3. 当前仓库基线与改造原则

### 3.1 可复用基线

当前仓库并非从零开始，已有以下可复用能力：

| 现有能力 | 当前落点 | vNext 处理方式 |
|---|---|---|
| Event 与安全门禁 | `memoryhub/adapter/schemas.py`、`core/safety/`、`core/ingestion/` | 扩展 Envelope、Policy 结果和幂等语义，保留现有安全扫描实现 |
| 统一记忆写服务 | `core/memory_write.py`、`core/domain_writer.py` | 升级为 Canonical Write Service 的长期记忆提交端，禁止旁路 |
| Preference/Knowledge/FACT | `adapter/schemas.py`、`storage/models.py` | 通过 Long-Term Envelope 兼容包装，暂不大爆炸合表 |
| Short/Mid 层级 | `ShortTermMemoryRow`、`MidTermMemoryRow`、`core/lifecycle/` | 新建 Working/Episode 契约并迁移；不直接复用 TTL/摘要语义 |
| Evidence/Lineage | `MemoryEvidenceRow`、`MemoryLineageRow` | 原表扩展治理、方向、版本和任务引用字段 |
| Projection Outbox | `MemoryProjectionOutboxRow`、`storage/projection_outbox.py` | 增加版本、租约、死信、删除优先级和幂等消费 |
| 混合检索与重排 | `memoryhub/retrieval/` | 外包一层统一 Router/Planner/Retrieval Service，保留通道实现 |
| Search/Context 接口 | `adapter/api.py` | 收敛为统一请求、统一结果与统一 Trace，保留兼容 DTO |
| Forget/安全/审计 | `core/forget/`、`core/safety/` | 升级为异步请求状态机和残留验证闭环 |
| 评测数据与脚本 | `evaluation/` | 增加 Formation、Working/Episode、Context、Reliability 和 E2E 数据集 |
| MCP/CLI/SDK | `agent-integration/` | 只做协议适配，全部调用同一 REST 契约 |

### 3.2 渐进迁移原则

1. `events`、`preferences`、`knowledge` 先保持兼容读取，通过新增字段或视图映射到 vNext 契约；
2. `short_term_memory` 不直接升级为 Working State；新增 `working_states`，迁移后再停止旧写入；
3. `mid_term_memory` 不直接视为 Task Episode；新增 `task_episodes` 与 `episode_events`，存疑数据标记 `REVIEW`；
4. `memory_evidence`、`memory_lineage`、`memory_projection_outbox` 采用增量迁移；
5. Preference 与 Knowledge 暂不物理合表，使用统一 `LongTermMemoryEnvelope` 和 Repository Facade 提供 Authority 语义；
6. 所有新能力由 Feature Flag 控制，具备 Shadow、双读、灰度和回滚状态；
7. 旧 API 在兼容窗口内保留，但内部不得继续维护第二套业务算法。

### 3.3 建议新增代码边界

在不进行全仓目录重排的前提下，建议逐步新增以下模块：

```text
memoryhub/
├── domain/
│   ├── contracts.py
│   ├── working.py
│   ├── episode.py
│   ├── candidate.py
│   ├── long_term.py
│   └── evolution.py
├── application/
│   ├── canonical_write.py
│   ├── working_service.py
│   ├── episode_service.py
│   ├── reflection_service.py
│   ├── consolidation_service.py
│   ├── retrieval_service.py
│   ├── context_service.py
│   └── forget_service.py
├── retrieval/
│   ├── intent_router.py
│   ├── planner.py
│   ├── fusion.py
│   ├── scope_resolver.py
│   └── context_builder.py
└── observability/
    ├── trace_models.py
    ├── trace_store.py
    └── metrics.py
```

现有模块在迁移期可以调用这些应用服务；禁止同时在新旧模块中实现两套状态机。

## 4. 总体里程碑与阶段 Gate

| 阶段 | 周期 | 关键输出 | 退出 Gate |
|---|---:|---|---|
| S0 契约冻结 | W1 | 术语、ADR、Schema、API、Feature Flag、基线报告 | 契约评审通过；Golden fixtures 可被序列化和校验 |
| S1 Authority 与任务状态 | W2～W3 | Working、Episode、Candidate、Authority Facade、Canonical Write | P0 写入/恢复贯通；无生产写旁路；索引删除可重建 |
| S2 记忆形成与演化 | W3～W4 | Boundary、Reflection、Promotion、Fast Path、Scope Evolution、Procedure | P1 Formation 成对场景通过；Candidate 不泄漏 |
| S3 Retrieval 与 Context | W4～W5 | Router、Planner、Fusion/Rerank、Scope Resolver、Budget、Activation | REST/MCP/CLI 结果 ID/版本一致；Trace 可解释完整链路 |
| S4 可靠性与遗忘 | W5～W6 | 版本化 Outbox、Repair、异步 Forget、故障注入 | 删除不复活；Projection 可修复；Forget 残留为 0 |
| S5 评测、展示与切流 | W6～W8 | 四层评测、消融、Dashboard、迁移、双读、灰度、运维材料 | 安全硬门槛无回退；P0/P1 全过；完成回滚演练 |

阶段不能仅凭代码合并宣布完成；必须提交对应 Gate 证据：测试报告、Trace 样例、迁移校验、指标对比和回滚记录。

## 5. 详细任务分解

说明：`人日`是开发与自测估算，不含跨团队等待时间。每项任务完成时必须附测试证据和关联文档。

### S0：冻结术语、契约与变更边界

| ID | 任务与主要动作 | 交付物/建议路径 | 依赖 | 角色 | 人日 | 验收标准 |
|---|---|---|---|---|---:|---|
| S0-01 | 冻结 Layer、Type、Formation Status、Evolution Status、Action、Activation、Scope、Intent 枚举；建立旧值映射表 | `docs/vnext/spec/VNEXT_GLOSSARY.md`、`memoryhub/domain/contracts.py` | 无 | Tech Lead + BE-A | 1.5 | 不再用单一 `level` 同时表达生命周期与类型；7 类 Intent 唯一 |
| S0-02 | 编写架构决策记录，明确 Authority/Projection、Canonical Path、模块禁止依赖与兼容策略 | `docs/vnext/design/ADR-vnext-memory-architecture.md` | S0-01 | Tech Lead | 1 | ADR 评审通过；列出明确的禁止调用关系 |
| S0-03 | 定义 vNext Pydantic 契约：Event、Working Patch/Snapshot、Episode Event/Snapshot、Candidate、Long-Term Envelope、Evidence、Lineage、Activation | `memoryhub/domain/contracts.py`、`docs/vnext/spec/VNEXT_DATA_CONTRACT.md` | S0-01 | BE-A | 3 | 所有对象含 tenant/user、schema/content version、时间与治理字段；JSON fixture 校验通过 |
| S0-04 | 定义统一 API vNext 契约和兼容响应：write、retrieve、resume、forget、diagnostic | `docs/vnext/spec/VNEXT_INTERFACE.md`、`adapter/vnext_schemas.py` | S0-03 | BE-A + Client | 2 | 错误码、幂等、部分降级、Authority 校验模式、分页和版本均有定义 |
| S0-05 | 设计数据迁移与回滚，明确新增表、扩展列、旧值映射、存疑数据处理 | `docs/vnext/spec/VNEXT_MIGRATION.md`、`scripts/migrate_vnext.py --dry-run` 骨架 | S0-03 | BE-B | 2 | 支持 dry-run；输出 count/hash/tenant/scope/invalid/review 报告；不做不可逆删除 |
| S0-06 | 建立 Feature Flag 与链路模式：legacy、shadow、dual-read、canary、vnext | `memoryhub/config.py`、`config.example.yaml` | S0-02 | BE-B | 1.5 | 各模式可启动；production 默认不能静默降级或绕过 Policy |
| S0-07 | 固化基线：全量测试、检索指标、延迟、写旁路扫描、当前数据统计 | `evaluation/results/vnext_baseline/` | 无 | QA/Eval | 2 | 报告记录 commit、配置、模型/索引版本、数据集 hash 与测试结果 |
| S0-08 | 建立 vNext Golden fixtures 和契约测试 | `tests/fixtures/vnext/`、`tests/test_vnext_contracts.py` | S0-03、S0-04 | QA/Eval | 2 | 覆盖正常、冲突、敏感、重复、过期版本、删除与降级响应 |

#### S0 Gate

- [ ] 术语、状态机和 7 类 Intent 无重复定义；
- [ ] API 与数据契约已冻结为 `vnext/v1`；
- [ ] Feature Flag 可关闭任意新链路；
- [ ] 基线报告可重复生成；
- [ ] Schema 变更有升级和回滚方案。

### S1：Authority Store 与任务状态闭环

| ID | 任务与主要动作 | 交付物/建议路径 | 依赖 | 角色 | 人日 | 验收标准 |
|---|---|---|---|---|---:|---|
| S1-01 | 新增 `working_states`、`task_episodes`、`episode_events`、`memory_candidates`、`memory_activations`、`retrieval_logs`、`idempotency_records`；扩展 Event/Evidence/Lineage/Outbox | `storage/models.py`、迁移脚本 | S0-03、S0-05 | BE-B | 4 | 唯一键、索引、租户隔离、版本字段和状态约束齐全；迁移可重复运行 |
| S1-02 | 实现 Repository 接口与事务测试 | `storage/vnext_repositories.py` | S1-01 | BE-B | 4 | Working CAS、Episode seq、Candidate 状态迁移、Evidence 去重、Activation 写入均有并发测试 |
| S1-03 | 升级 Event Gateway：Envelope 校验→身份/Scope→Policy→MASK/DROP/REVIEW→幂等→Commit | `application/canonical_write.py`、复用 `core/safety/` | S0-04、S1-02 | BE-A | 4 | 敏感正文不会先进入日志/队列/幂等缓存；重复事件不增加 Evidence/Frequency |
| S1-04 | 实现 Working State 字段级 Patch、来源优先级、乐观锁、语义合并与结构化压缩 | `domain/working.py`、`application/working_service.py` | S1-02、S1-03 | BE-A | 5 | 可恢复 goal/current step/pending/constraints；过期 base_version 不做静默覆盖 |
| S1-05 | 实现 Episode Append + Snapshot + Resume + Close；资源陈旧检查和 resume token | `domain/episode.py`、`application/episode_service.py` | S1-02、S1-04 | BE-A | 5 | Snapshot 后事件可重放；双设备恢复用乐观锁；输出 stale_resources 和 required_revalidation |
| S1-06 | 实现 Candidate Repository 和默认检索隔离 | `domain/candidate.py`、`storage/vnext_repositories.py` | S1-02 | BE-A | 3 | ACCUMULATING/CONFIRMED/REJECTED/REVIEW 合法迁移；普通搜索无法召回 Candidate |
| S1-07 | 建立 Long-Term Authority Facade，兼容 Preference/Knowledge/FACT，并统一 Envelope/Version/Scope/Status | `domain/long_term.py`、`storage/authority_repository.py` | S0-03、S1-02 | BE-B | 4 | 同一版本链最多一个 ACTIVE；SUPERSEDED/DELETED 默认不可读；现有 API 兼容 |
| S1-08 | 组装 Canonical Write Service：Event→Working→Checkpoint/Episode→异步 Reflection 任务；长期提交复用 `MemoryWriteService`/`DomainMemoryWriter` | `application/canonical_write.py` | S1-03～S1-07 | BE-A | 5 | Authority 事务内同时写业务对象、Evidence/Lineage、幂等记录和 Outbox |
| S1-09 | 收敛 REST、Agent replay、MCP、CLI、SDK 写入口；扩展旁路扫描 | `adapter/api.py`、`agent-integration/`、`tests/test_no_production_write_bypass.py` | S1-08 | BE-A + Client | 3 | 同一事件从各入口得到相同 event/working/episode ID；业务代码无直接长期表写入 |
| S1-10 | 实现任务恢复接口和 P0 贯通用例 | `GET /api/memory/tasks/{task_id}/resume`、`tests/test_vnext_p0_flow.py` | S1-05、S1-08 | QA/Eval + BE-A | 3 | 中断后恢复 Goal、Current Step、Pending Steps、Constraints；续作版本冲突可见 |
| S1-11 | 实现 Authority→Projection 全量重建最小工具 | `scripts/rebuild_projections.py` | S1-07 | BE-B | 2 | 删除测试索引后可从 Authority 恢复相同 memory_id/content_version；不恢复删除对象 |

#### S1 Gate（P0-A/C）

- [ ] Policy 在任何持久化、日志与异步任务前生效；
- [ ] 重复事件不会重复更新 Working、Evidence 或统计；
- [ ] Working/Episode 可跨进程恢复；
- [ ] Candidate 不进入普通检索；
- [ ] 任意生产写入口无法绕过 Canonical Write Service；
- [ ] 索引损坏后可由 Authority 重建。

### S2：Reflection、证据固化与记忆演化

| ID | 任务与主要动作 | 交付物/建议路径 | 依赖 | 角色 | 人日 | 验收标准 |
|---|---|---|---|---|---:|---|
| S2-01 | 实现 Task Boundary Detector：硬触发、规则分数、模型建议、去抖及三类 Checkpoint | `domain/episode.py`、`application/boundary_detector.py` | S1-04、S1-05 | BE-A | 4 | Complete/Failed/Explicit 为硬触发；窗口短切换不会错误关闭任务；Context Pressure 只产生轻检查点 |
| S2-02 | 定义 Reflection 输入输出 Schema、Prompt 版本和失败重试；只产 Candidate，不直接写长期记忆 | `application/reflection_service.py`、`memoryhub/core/reflection/` | S1-06、S2-01 | BE-A | 4 | 输出结构校验；记录 model_id/prompt_version/input_hash；模型不可直接写 Authority |
| S2-03 | 实现 Candidate 归一键、Scope、近重复合并和独立证据组 | `application/candidate_service.py` | S2-02 | BE-A | 4 | 同一事件不形成独立证据；同一任务重复表述不错误累计“独立证据” |
| S2-04 | 实现 Promotion Score、类型阈值、决策区间和可解释 reason codes | `application/consolidation_service.py` | S2-03 | BE-A | 4 | 一次隐式行为不固化为 Global；多次独立证据可推动固化；REVIEW/REJECT 可解释 |
| S2-05 | 实现 Fast Path 白名单和治理约束 | `application/consolidation_service.py` | S2-04 | BE-A | 2 | 用户显式长期规则/高可信工具事实可快速固化；敏感、模糊 Scope 和冲突内容不可走 Fast Path |
| S2-06 | 实现 Evolution：REINFORCE/REVISE/SUPERSEDE/COEXIST/REVIEW 与状态变化 | `domain/evolution.py`、`application/evolution_service.py` | S1-07、S2-04 | BE-A | 5 | 动作与状态分离；版本链方向正确；局部覆盖不删除全局规则；并发更新按 expected version 处理 |
| S2-07 | 按类型实现 Long-Term 内容校验，重点补齐 Procedural Trigger/Preconditions/Steps/Verification/Failure Recovery | `domain/long_term.py` | S2-04、S2-06 | BE-A | 4 | Procedure 必须来自重复成功 Episode；失败样本进入约束或恢复步骤，不能直接当成功流程 |
| S2-08 | Formation Shadow 模式：与旧抽取/写入结果对比但不影响线上结果 | `application/reflection_service.py`、Feature Flag | S0-06、S2-02～S2-07 | BE-A + QA | 3 | 可输出候选差异、过早固化、漏固化、Scope/Type 差异；Shadow 绝不写 ACTIVE Long-Term |
| S2-09 | 实现 Formation/Evolution Trace | `observability/trace_models.py`、`observability/trace_store.py` | S2-02～S2-07 | QA/Eval | 3 | Event→Working→Episode→Candidate→Memory 全链可通过 ID 追溯；默认不记录未脱敏正文 |
| S2-10 | 建立 Formation 与 Working/Episode 数据集、评测器及 P1 成对场景 | `evaluation/datasets/vnext_formation_*`、`evaluation/metrics/formation_eval.py` | S2-08、S2-09 | QA/Eval | 5 | 报告 Formation Precision/Recall、Premature Promotion、Scope/Type、Resume、Constraint Preservation |

#### S2 Gate（P1-A）

- [ ] “这次用 DOCX”只形成局部 Candidate，不形成 Global Preference；
- [ ] 多个独立任务中的明确证据能推动 Candidate 固化；
- [ ] Global Markdown 与 Project-A DOCX 以 COEXIST 保存并按 Scope 生效；
- [ ] 两次成功修复可形成带验证步骤的 Procedure；
- [ ] 所有形成和演化决策可由 Evidence、阈值和 reason code 解释。

### S3：统一 Retrieval、Context 与 Activation

| ID | 任务与主要动作 | 交付物/建议路径 | 依赖 | 角色 | 人日 | 验收标准 |
|---|---|---|---|---|---:|---|
| S3-01 | 实现统一 `MemoryRetrievalRequest/Response`，兼容旧 `SearchRequest/Response` | `adapter/vnext_schemas.py` | S0-04 | BE-B | 2 | 包含 query/task/working/scope/intent hint/budget/consistency/trace；旧客户端不破坏 |
| S3-02 | 实现 Query Understanding 与 7 类 Intent Router，支持多意图和低置信降级 | `retrieval/intent_router.py` | S3-01 | BE-B | 4 | 输出 intent、confidence、target layers/types、reason；MIXED 有明确拆分规则 |
| S3-03 | 实现 Retrieval Planner 与多通道召回适配，复用 Milvus/FAISS/BM25/metadata/current state | `retrieval/planner.py` | S3-02、S1-07 | BE-B | 4 | 每个 Intent 只启用必要通道；生产 Milvus 门禁保持；通道降级可见 |
| S3-04 | 实现候选去重、Fusion 和统一 Reranker，输出分数分解及版本 | `retrieval/fusion.py`、升级 `retrieval/reranker.py` | S3-03 | BE-B | 4 | 相同 memory_id/version 只保留一项；旧版本不覆盖新版本；每项分数可解释 |
| S3-05 | 实现 Authority 有效性校验与 Scope-aware Conflict Resolver | `retrieval/scope_resolver.py` | S3-04、S2-06 | BE-B | 4 | DELETED/SUPERSEDED 不泄漏；TASK>PROJECT>APPLICATION>DOMAIN>GLOBAL；冲突组带 resolution |
| S3-06 | 实现 Context Budget Manager 的分类配额、硬约束保护和语义裁剪 | `retrieval/context_builder.py` | S3-05 | BE-B | 4 | 预算不足时保留目标、当前步骤、硬约束和必要 Procedure；记录每项保留/丢弃原因 |
| S3-07 | 实现结构化 Context Builder 和兼容文本渲染 | `application/context_service.py` | S3-06 | BE-B | 4 | 输出 Current State/Constraints/Relevant Memory/Conflict Notes/Source IDs；禁止未解释冲突 |
| S3-08 | 实现 Activation、Retrieval Log 与 Retrieval Trace | `application/retrieval_service.py`、`observability/` | S3-03～S3-07 | QA/Eval + BE-B | 4 | 记录 query→plan→candidates→scores→scope→budget→context；Activation 不改变 Layer |
| S3-09 | 收敛 `/search`、`/context`、v2 search、MCP、CLI、SDK 到同一服务 | `adapter/api.py`、`adapter/memory_v2_api.py`、`agent-integration/` | S3-08 | BE-B + Client | 4 | 相同请求在所有入口返回相同 Memory ID、content_version、顺序和 trace_id |
| S3-10 | 建立 Router、Recall、Ranking、Scope、Context 分段评测与回归集 | `evaluation/metrics/vnext_retrieval_eval.py`、新数据集 | S3-09 | QA/Eval | 5 | 输出 Intent/Layer/Type Accuracy、Recall@K、MRR/NDCG、Context Precision/Recall、Conflict Leakage、Constraint Loss |

#### S3 Gate（P0-B/P1-B）

- [ ] 7 类 Intent 均有标注样本和可解释路由结果；
- [ ] 精确、改写、语义表达可进入统一候选池和统一排序；
- [ ] Candidate、DELETED、SUPERSEDED 和其他租户记忆无法进入 Context；
- [ ] 有限预算下硬约束与当前步骤不丢失；
- [ ] REST/MCP/CLI/SDK 不存在各自拼 Context 的实现。

### S4：Projection、Repair、Forget 与可靠性

| ID | 任务与主要动作 | 交付物/建议路径 | 依赖 | 角色 | 人日 | 验收标准 |
|---|---|---|---|---|---:|---|
| S4-01 | 升级 Outbox：`content_version/projection_type`、事件唯一键、租约、退避、Dead Letter、删除优先级 | `storage/models.py`、`storage/projection_outbox.py` | S1-01、S1-07 | BE-B | 4 | 至少一次投递下无重复投影；旧 UPSERT 不得复活已处理 DELETE；Worker 崩溃可重领 |
| S4-02 | 实现 Projection Version 校验、Authority Checked 读取和 Cache 版本失效 | `storage/projection_service.py`、`application/retrieval_service.py` | S4-01、S3-08 | BE-B | 3 | 过期候选进入 Context 前逐条校验；高风险查询可强制 Authority 校验 |
| S4-03 | 实现点修复和离线 Repair Worker：Missing/Stale/Orphan/Incompatible/Duplicate | `storage/repair.py`、`scripts/repair_projections.py` | S4-01、S4-02 | BE-B | 5 | 修复前二次读 Authority；修复后读回验证；全量重建使用新索引/别名与回滚窗口 |
| S4-04 | 将 Forget 升级为请求状态机：dry-run、READ_BLOCKED、清投影、验证、部分失败重试 | `application/forget_service.py`、扩展 `core/forget/` | S1-07、S4-01 | BE-B | 5 | 首次提交即阻断 Authority 读取；清理 Vector/BM25/Cache/Candidate/Activation 派生数据；保留合规 Tombstone |
| S4-05 | 实现 Forget 查询/管理接口和批量高风险授权约束 | `POST/GET /api/memory/forget...` | S4-04 | BE-B + Client | 2 | 返回 request/projection/verification 状态与 residual count；Global/批量必须明确 Scope 和更高授权 |
| S4-06 | 增加诊断 API：memory/evidence/lineage/retrieval trace/projection repair/candidate review | `adapter/management_api.py`、`adapter/memory_v2_api.py` | S2-09、S3-08、S4-03 | BE-B | 3 | 管理接口与用户接口权限分离；变更操作含 actor/reason/idempotency/audit |
| S4-07 | 建立故障注入矩阵及自动化测试 | `tests/test_vnext_reliability.py`、`evaluation/run_reliability_eval.py` | S4-01～S4-05 | QA/Eval | 5 | 覆盖 Vector 超时、重复投递、Worker 崩溃、提交前后崩溃、缓存陈旧、索引损坏、重复事件 |
| S4-08 | 实现 Infrastructure Trace 和可靠性指标 | `observability/metrics.py` | S4-01～S4-07 | QA/Eval | 3 | 输出 Write/Search/Context latency、Projection lag、Recovery time、Repair rate、Forget success、Residual retrieval |

#### S4 Gate（P0-C）

- [ ] Authority 提交前失败无半条数据；提交后失败可由 Outbox 恢复；
- [ ] Outbox 重复和乱序不会造成降版本或删除对象复活；
- [ ] 索引全损坏可在目标 RTO/RPO 内重建；
- [ ] Forget 验收查询 residual retrieval count = 0；
- [ ] 降级时允许少返回，但不允许越权、泄漏或返回已删除数据。

### S5：评测、Dashboard、迁移、切流与交付

| ID | 任务与主要动作 | 交付物/建议路径 | 依赖 | 角色 | 人日 | 验收标准 |
|---|---|---|---|---|---:|---|
| S5-01 | 统一五类 Trace 的关联、采样、脱敏和保留策略 | `observability/`、`docs/vnext/spec/VNEXT_TRACE.md` | S2-09、S3-08、S4-08 | QA/Eval | 3 | trace/task/event/memory/query ID 可串联；高风险/错误/Forget 全采样；普通正文不落 Trace |
| S5-02 | 建立四层 Benchmark 数据与 Runner：Formation、Retrieval、Infrastructure、E2E | `evaluation/datasets/vnext_*`、`evaluation/run_vnext_eval.py` | S2-10、S3-10、S4-07 | QA/Eval | 6 | 固定数据版本、标注说明、随机种子、模型/Prompt/权重版本；一条命令产出报告 |
| S5-03 | 执行四系统对照与消融：No Memory、Flat RAG、Original、vNext | `evaluation/results/vnext_final/` | S5-02 | QA/Eval | 5 | 同模型、工具权限、预算；报告均值、方差、置信区间和中间指标；一次只移除一个机制 |
| S5-04 | 实现最小四页 Dashboard：Explorer、Evolution、Retrieval Debugger、Benchmark | `desktop-client/` | S4-06、S5-01、S5-02 | Client/UX | 8 | 四页互相跳转；可查看 Evidence/Lineage/版本/Activation/分数/预算；默认脱敏且有权限审计 |
| S5-05 | 实现 Agent Usage Trace 和 Utility Feedback Shadow 更新 | `application/feedback_service.py` | S3-08、S5-01 | BE-A + QA | 4 | 区分 Included/Referenced/Action Influenced/Outcome/Correction；Shadow 不自动改正文或状态 |
| S5-06 | 完成旧数据迁移工具与校验，输出 REVIEW 清单 | `scripts/migrate_vnext.py`、`evaluation/results/vnext_migration/` | S0-05、S1-01、S1-07 | BE-B | 5 | count/hash/tenant/scope/version/evidence 校验通过；存疑记录不静默变成 LONG_TERM ACTIVE |
| S5-07 | 执行 Formation Shadow 和 Retrieval 双读对比，形成切流报告 | `evaluation/results/vnext_shadow/` | S2-08、S3-09、S5-06 | QA/Eval | 5 | 报告差异分类、正确性、延迟、冲突泄漏、Policy/Forget；达到门槛才允许灰度 |
| S5-08 | 灰度切流 5%→25%→50%→100%，保留回滚读取窗口 | 配置、切流记录、监控面板 | S5-07、S4 Gate | Tech Lead + BE-B | 4 | 每级观察至少一个约定窗口；安全硬门槛零回退；回滚开关经演练可用 |
| S5-09 | 更新 REST/CLI/MCP/SDK、部署、迁移、备份恢复和故障处理文档 | `docs/spec/`、`agent-integration/docs/`、`README.md` | S5-08 | Client + BE-B | 3 | 文档命令在干净环境可执行；接口与代码零漂移；含回滚和数据恢复步骤 |
| S5-10 | 准备固定可重放演示与最终验收包 | `examples/vnext_demo/`、最终报告 | S5-03、S5-04、S5-09 | 全体 | 4 | 完整展示形成、证据累积、Scope 覆盖、检索解释、任务恢复和 Forget 验证 |

#### S5 Gate（发布 Gate）

- [ ] P0/P1 全部测试与场景通过；
- [ ] Policy Leakage、跨租户泄漏、Forget 残留均为 0；
- [ ] 任务成功率、用户纠正率、Context Tokens、延迟已与基线比较；
- [ ] 迁移、索引重建、服务回滚均至少演练一次；
- [ ] Dashboard 和演示数据不包含未脱敏正文；
- [ ] 旧写入关闭后，旧读取兼容窗口和最终下线日期已登记。

## 6. 依赖关系与并行安排

### 6.1 关键路径

```text
S0-01 契约
  → S0-03 数据模型
  → S1-01/02 存储与 Repository
  → S1-03/04/05/06 Event + Working + Episode + Candidate
  → S1-08 Canonical Write
  → S2-02/03/04 Reflection + Promotion
  → S2-06 Evolution
  → S3-05 Scope Resolver
  → S3-07/08 Context + Trace
  → S4-04 Forget
  → S5-07/08 双读与切流
```

任何关键路径任务延期时，优先取消 P2，不得取消 Policy、幂等、Authority 校验、Forget 验证或回滚演练。

### 6.2 可并行工作流

| 工作流 | 可并行任务 | 汇合点 |
|---|---|---|
| Formation | S1-03～S1-06、S2-01～S2-07 | S1-08、S2 Gate |
| Retrieval/Infra | S1-07、S1-11、S3-01～S3-08、S4-01～S4-05 | S3-09、S4 Gate |
| QA/Eval | S0-07/08、S1-10、S2-09/10、S3-10、S4-07/08 | 每阶段 Gate |
| Client/UX | S0-04、S1-09、S3-09、S4-06、S5-04/09 | S5 发布 Gate |

### 6.3 建议周排期

| 周次 | Formation/Domain | Retrieval/Infrastructure | QA/Client |
|---|---|---|---|
| W1 | 术语、Schema、API | ADR、迁移、Flag | 基线、fixtures、契约测试 |
| W2 | Event、Working | 新表、Repository、Authority Facade | P0 场景骨架、写旁路扫描 |
| W3 | Episode、Candidate、Canonical Write | 重建工具、入口收敛 | 恢复/迁移/多入口一致性测试 |
| W4 | Boundary、Reflection、Promotion | Retrieval Request、Router、Planner | Formation 数据集与 Shadow 报告 |
| W5 | Evolution、Procedure | Fusion、Scope、Budget、Context | Retrieval 分段评测、客户端联调 |
| W6 | Formation 修正 | Outbox、Repair、Forget | 故障注入、可靠性指标 |
| W7 | Feedback Shadow | 迁移、双读、灰度准备 | E2E/消融、Dashboard |
| W8 | 缺陷收敛 | 切流、回滚演练 | 最终报告、文档、演示与发布 Gate |

## 7. 验收场景清单

### 7.1 P0 必测贯通场景

| 场景 ID | 输入与动作 | 必须观察的中间状态 | 预期结果 |
|---|---|---|---|
| E2E-P0-01 | 用户开始制作报告并给出格式约束 | Event、Working Patch、version | Working 包含 goal/current step/pending/constraints |
| E2E-P0-02 | 从检索阶段切换为生成阶段 | Boundary decision、Episode event/snapshot | 产生 PHASE_CHECKPOINT，不关闭任务 |
| E2E-P0-03 | 用户说“这次请用 DOCX” | Candidate、Evidence group | 只形成局部 Candidate，不形成 Global Long-Term |
| E2E-P0-04 | 服务重启后恢复任务 | Snapshot、replayed events、resume token | 恢复目标、约束、待办；陈旧资源要求复验 |
| E2E-P0-05 | 删除 Vector/BM25 索引后重建 | Authority scan、Outbox/Repair Trace | Memory ID 与 content_version 恢复一致 |
| E2E-P0-06 | 相同请求从 REST/MCP/CLI 发起 | request/trace/result IDs | 返回相同有效记忆 ID、版本和排序 |
| E2E-P0-07 | 同一事件重复提交 | idempotency record | 不重复累计 Evidence、Frequency 或 Candidate |
| E2E-P0-08 | 事件包含 Token/私密正文 | Policy、redaction/audit | DROP/MASK 正确，原文不进入日志、Trace 或索引 |

### 7.2 P1 核心创新场景

| 场景 ID | 设计点 | 预期结果 |
|---|---|---|
| E2E-P1-01 | Evidence Promotion | 多个独立任务重复明确“Project-A 正式报告用 DOCX”后固化 Project Scope Preference |
| E2E-P1-02 | Scope Coexist | Global Markdown 与 Project-A DOCX 同时 ACTIVE，Project-A 中局部规则优先，离开项目后 Global 仍有效 |
| E2E-P1-03 | Procedure Formation | 两次相似成功修复与一次失败形成包含前置条件、步骤、验证和失败恢复的 Procedure |
| E2E-P1-04 | Router/Recall | 精确词、改写、语义表达均召回同一目标；Trace 展示 Intent、通道和分数 |
| E2E-P1-05 | Context Budget | 低 Token 预算下保留硬约束、当前步骤与必要 Procedure，裁剪原因可见 |
| E2E-P1-06 | Evolution | 新配置按证据和 Scope 得出 REINFORCE/REVISE/SUPERSEDE/COEXIST，不做无解释覆盖 |
| E2E-P1-07 | Agent Usage | 进入 Context 的记忆可区分被引用、被忽略、影响动作及任务结果 |

### 7.3 安全与可靠性零容忍场景

- 跨用户/跨租户检索返回任何记录；
- Candidate、REVIEW 敏感正文、DELETED 或 SUPERSEDED 记录进入普通 Context；
- DELETE v5 后延迟 UPSERT v4 复活索引；
- Forget 已进入 `READ_BLOCKED` 后仍可从 Cache、Vector、BM25 或 Evidence 接口读取正文；
- Outbox 重投导致 Evidence、Lineage、Frequency 或 Projection 重复；
- 迁移将无 Scope/无 Evidence 的存疑数据静默转为 Global ACTIVE。

出现以上任一情况，当前阶段 Gate 直接失败，不以平均指标抵消。

## 8. 指标门槛与报告口径

具体数值先以 S0 基线校准；以下是发布时必须执行的最低口径。

| 维度 | 必报指标 | 门槛/判定方式 |
|---|---|---|
| Formation | Precision、Recall、Premature Promotion、Evidence Coverage、Scope/Type Accuracy | P0/P1 Golden 场景 100% 通过；新系统相对 Original 不回退 |
| Working/Episode | State Field Accuracy、Resume Action Accuracy、Constraint Preservation、Episode Completeness | 硬约束丢失率 0；P0 恢复场景 100% 通过 |
| Retrieval | Intent/Layer/Type Accuracy、Recall@K、MRR、NDCG、Scope Accuracy | 相对基线不回退；比赛硬指标沿用项目最终验收阈值 |
| Context | Precision、Recall、Conflict Leakage、Constraint Loss、Citation Accuracy | Conflict Leakage=0；Constraint Loss=0；来源 ID 可回溯 |
| Reliability | Write/Search/Context P95/P99、Projection Lag、Recovery Time、Repair Rate | 生产麒麟/Milvus 延迟沿用既有 P95≤350ms、P99≤500ms 目标；故障后无错误复活 |
| Forget | Success Rate、Residual Retrieval Count | 授权范围内成功率 100%；残留检索数 0 |
| E2E | Task Success、User Correction、Tool Calls、Context Tokens、Latency | 与 Baseline 0/1/2 同预算比较，报告置信区间，不只报单次演示 |

若真实麒麟环境暂不可用，代码 Gate 与 Mock 故障 Gate 可以先完成，但发布状态必须标记“待真机性能验收”，不得用 Mock 延迟冒充生产结果。

## 9. 测试与验证命令

任务实现时应逐层执行，最终以仓库环境实际可用的 Python 入口为准：

```powershell
# 单元与契约测试
.\.venv\Scripts\python.exe -m pytest tests/test_vnext_contracts.py -q

# P0/P1 贯通测试
.\.venv\Scripts\python.exe -m pytest tests/test_vnext_p0_flow.py tests/test_vnext_p1_flow.py -q

# 安全、旁路与租户隔离
.\.venv\Scripts\python.exe -m pytest tests/test_no_production_write_bypass.py tests/test_user_isolation.py tests/test_safety_pipeline.py -q

# Outbox、Forget 与故障注入
.\.venv\Scripts\python.exe -m pytest tests/test_vnext_reliability.py tests/test_projection_outbox.py tests/test_forget_semantic.py -q

# 全量回归
.\.venv\Scripts\python.exe -m pytest -q

# 数据迁移预演
.\.venv\Scripts\python.exe scripts/migrate_vnext.py --dry-run --report evaluation/results/vnext_migration/dry_run.json

# 统一评测
.\.venv\Scripts\python.exe evaluation/run_vnext_eval.py --suite all --output-dir evaluation/results/vnext_final
```

上述 vNext 文件由对应任务创建。在文件尚未落地前，任务状态不得标记为“已验收”。

## 10. 每个任务的 Definition of Ready / Done

### 10.1 Definition of Ready

任务进入开发前必须满足：

- 上游契约和依赖任务已合并或提供稳定 mock；
- 输入、输出、错误码、状态迁移和权限边界已明确；
- 至少有一个正常用例、一个边界用例、一个失败用例；
- 涉及 Schema 时已有迁移和回滚方案；
- 涉及模型时已有 Prompt 版本、结构化输出和无模型降级策略；
- 涉及 Projection 时已定义 content/projection version 行为；
- 涉及敏感数据时已通过 Policy 与 Trace 脱敏评审。

### 10.2 Definition of Done

任务只有同时满足以下条件才算完成：

1. 代码和 Schema 已实现，且不存在临时生产旁路；
2. 单元、契约、集成和必要的故障测试通过；
3. 新增行为有 Trace 或结构化日志，可定位失败阶段；
4. API/配置/迁移/运维文档同步更新；
5. 兼容性和回滚路径已验证；
6. 测试报告记录 commit、环境、配置和数据集版本；
7. 对应验收标准已由非实现者复核；
8. 未解决风险已登记 owner、截止时间和降级方案。

## 11. Issue/任务卡模板

每个任务从本文件拆到 Issue 时使用以下模板：

```markdown
## 任务
- ID：Sx-xx
- 目标：
- Owner：
- Reviewer：
- 计划开始/完成：
- 依赖：
- Feature Flag：

## 输入与输出契约
- 输入：
- 输出：
- 错误码：
- 状态迁移：

## 实现范围
- 修改文件：
- 新增迁移：
- 不在范围：

## 验收
- [ ] 正常用例
- [ ] 边界用例
- [ ] 失败/故障用例
- [ ] 安全与租户隔离
- [ ] Trace/指标
- [ ] 兼容与回滚

## 证据
- 测试命令与结果：
- Trace ID/截图：
- 评测报告：
- 风险与后续：
```

## 12. 风险登记

| 风险 | 触发信号 | 影响 | 应对措施 | Owner |
|---|---|---|---|---|
| 概念映射再次漂移 | 新模块继续使用 `short/mid/long` 表达多重含义 | API、评测和迁移失配 | S0 契约测试作为 CI Gate；旧值只允许出现在兼容层 | Tech Lead |
| Working 并发覆盖 | version conflict、约束无故消失 | 任务无法可靠恢复 | CAS + 字段级合并；互斥字段进入冲突队列 | BE-A |
| Reflection 过早固化 | Global Preference 数量突增、纠正率上升 | 错误记忆长期污染 | Candidate staging、独立证据组、Shadow、阈值分类型 | BE-A |
| 新旧链路双写分叉 | 同一事件产生不同 memory/version | 切流失败、回滚困难 | Authority 单写；Shadow 只记录差异；禁止双 Authority | BE-A/BE-B |
| Scope 错误 | Conflict Leakage、项目规则外溢 | Agent 使用错误规则 | Scope 绑定不可推断成 Global；Resolver 独立测试 | BE-B |
| Outbox 乱序复活删除数据 | DELETE 后重新出现向量 | 严重隐私与一致性事故 | Tombstone + content version + 删除优先级 + 乱序故障测试 | BE-B |
| Trace 成为第二记忆库 | 日志出现正文或敏感 Evidence | 隐私泄漏 | ID/hash/分类为主；正文默认不采集；高权限审计 | QA/Eval |
| 指标提升但任务无收益 | NDCG 上升、Task Success 不变 | 创新无法证明 | 建立“设计点→中间指标→E2E”因果链和消融实验 | QA/Eval |
| 真机环境不足 | 无法给出 Kylin/Milvus 实测 | 发布证据不足 | 提前准备一键脚本与环境 manifest；明确待真机 Gate | Tech Lead |
| 任务量超出周期 | W4 关键路径未完成 | P0/P1 延期 | 先移除 P2、Graph、高级调权；不削弱安全和恢复能力 | Tech Lead |

## 13. 发布与回滚策略

### 13.1 切流步骤

```text
1. legacy：旧链路提供结果，vNext 关闭
2. shadow：vNext Formation/Router 运行但不影响业务结果
3. dual-read：Authority 单写；新旧 Retrieval 同时读，只返回旧结果
4. canary-5：5% 请求返回 vNext，观察安全、正确性、延迟
5. canary-25/50：逐级扩流，每级完成约定观察窗口
6. vnext-100：全量返回新结果，旧读取保留回滚窗口
7. retire：关闭旧写入及旧算法，最后下线兼容读取
```

### 13.2 自动停止条件

发生以下任一事件立即停止扩流并回滚结果读取：

- Policy Leakage、跨租户结果、Forget 残留大于 0；
- DELETED/SUPERSEDED 记忆进入 Context；
- 任务恢复丢失硬约束；
- P95/P99 超出约定预算且无安全降级路径；
- 新旧结果差异中出现未解释的 Scope/版本倒退；
- Outbox Dead Letter 持续增长或 Projection Lag 超过阈值。

回滚只切换读取和 Formation 开关，不回滚已经正确提交的 Authority 数据；若 Schema 必须回退，按迁移文档执行兼容读取，禁止直接删除新表。

## 14. 最终交付物清单

### 14.1 工程交付

- [ ] vNext 领域契约、应用服务、Repository 和迁移脚本；
- [ ] Working/Episode/Candidate/Long-Term 完整形成链；
- [ ] 统一 Retrieval/Context/Activation 链；
- [ ] 版本化 Outbox、Repair、Forget 状态机；
- [ ] REST/MCP/CLI/SDK 兼容实现；
- [ ] Feature Flag、Shadow、双读、灰度和回滚配置；
- [ ] 全量测试、故障注入与生产环境检查脚本。

### 14.2 评测与展示交付

- [ ] Formation、Working/Episode、Retrieval/Context、Reliability、E2E 数据集；
- [ ] No Memory、Flat RAG、Original、vNext 对照报告；
- [ ] Candidate、Evidence、Scope、Router、Reranker、Episode 消融报告；
- [ ] Memory Explorer、Evolution、Retrieval Debugger、Benchmark Dashboard；
- [ ] 固定可重放的比赛演示场景与 Trace；
- [ ] 指标基线、最终结果、环境 manifest 与数据集 hash。

### 14.3 文档交付

- [ ] 术语表、ADR、数据契约、API 契约、Trace 契约；
- [ ] 数据迁移、部署、备份恢复、Repair、Forget 与回滚手册；
- [ ] 用户手册和 Agent 接入说明；
- [ ] 项目创新说明、实验方法、结果分析和已知限制；
- [ ] 最终验收报告与发布签字记录。

## 15. 项目负责人每周检查表

- [ ] 关键路径任务是否按依赖推进；
- [ ] 是否出现任何新的直接表写入或接口自建算法；
- [ ] 契约、Schema、API、测试和文档是否同步；
- [ ] Shadow/双读差异是否已经分类并指派 Owner；
- [ ] Policy、租户隔离、Forget、版本有效性是否保持零容忍；
- [ ] Formation/Retrieval/Reliability/E2E 指标是否能从 Trace 解释；
- [ ] P2 工作是否挤占 P0/P1 关键路径；
- [ ] 风险是否有 Owner、截止时间、降级和回滚方案；
- [ ] 下一阶段 Gate 的证据是否已经开始准备，而非阶段结束后补写。

---

本计划的执行原则可以归纳为一句话：

> 先用稳定契约和 Authority Store 建立可信事实，再用 Candidate、Evidence、Routing 和 Trace 增加智能；任何智能能力都不能绕过治理、恢复、验证和回滚边界。
