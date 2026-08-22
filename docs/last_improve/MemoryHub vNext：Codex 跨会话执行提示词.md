# MemoryHub vNext：Codex 分批次跨会话执行手册

> 版本：2.0
>
> 核心规则：一个会话只允许执行一个批次；一个完成的批次只创建一次本地 Git 提交；提交后必须停止并交接，不得在同一会话启动下一批次。

## 1. 目的与粒度

本手册将《MemoryHub vNext：A/B/C/D 一体化执行任务方案》拆成 18 个依赖闭合的执行批次。每个批次有一份独立提示词，用户在新会话中只发送当前批次的提示词。

这里明确区分三种粒度：

- **阶段**：`S0`～`S5`，用于 Gate 验收。
- **正式任务**：`S0-01`～`S5-10`，用于代码和证据跟踪。
- **执行批次**：`B01`～`B18`，是单个会话的唯一授权边界。

“一个会话一个批次”表示：会话内可以按顺序完成该批次包含的多个正式任务，但不得领取下一批次的任务。如果当前批次因时间、环境或 Blocker 未完成，下一个新会话仍使用同一批次提示词恢复，不得跳批。

## 2. 文件布局

```text
docs/last_improve/
├── MemoryHub vNext：Codex 跨会话执行提示词.md  # 本总控手册
├── MemoryHub vNext：A_B_C_D 一体化执行任务方案.md
├── MemoryHub vNext：A_B_C_D 一体化改进方案.md
├── codex_batches/                         # B01～B18 独立提示词
└── codex_execution/
    ├── STATE.md
    ├── BATCH_BOARD.md
    ├── TASK_BOARD.md
    ├── DECISIONS.md
    ├── EVIDENCE.md
    └── SESSION_LOG.md
```

`BATCH_BOARD.md` 是批次状态的唯一真相源，`TASK_BOARD.md` 是 57 个正式任务状态的唯一真相源。两者必须与代码、测试和 `EVIDENCE.md` 一致。

## 3. 批次划分

| 批次 | 会话范围 | 批次交付/退出条件 | 提示词 |
|---|---|---|---|
| B01 | S0-01～S0-04 | 术语、ADR、数据契约和 API 契约冻结 | `codex_batches/B01_s0_contracts.md` |
| B02 | S0-05～S0-08 + S0 Gate | 迁移、Flag、基线、Golden fixtures 完成，S0 Gate PASS | `codex_batches/B02_s0_delivery_gate.md` |
| B03 | S1-01～S1-03 | Authority Schema、Repository 和 Event Gateway 完成 | `codex_batches/B03_s1_storage_ingress.md` |
| B04 | S1-04～S1-06 | Working、Episode、Candidate 状态闭环 | `codex_batches/B04_s1_task_state.md` |
| B05 | S1-07～S1-08 | Long-Term Authority Facade 和 Canonical Write 组装完成 | `codex_batches/B05_s1_authority_write.md` |
| B06 | S1-09～S1-11 + S1 Gate | 写入口收敛、恢复、重建通过，S1 Gate PASS | `codex_batches/B06_s1_entrypoints_gate.md` |
| B07 | S2-01～S2-03 | Boundary、Reflection Schema 和 Candidate 归一完成 | `codex_batches/B07_s2_reflection_candidates.md` |
| B08 | S2-04～S2-07 | Promotion、Fast Path、Evolution 和分类校验完成 | `codex_batches/B08_s2_consolidation_evolution.md` |
| B09 | S2-08～S2-10 + S2 Gate | Shadow、Trace、Formation 评测完成，S2 Gate PASS | `codex_batches/B09_s2_shadow_eval_gate.md` |
| B10 | S3-01～S3-03 | Retrieval 契约、Router 和 Planner 完成 | `codex_batches/B10_s3_request_planning.md` |
| B11 | S3-04～S3-07 | Fusion、Scope、Budget 和 Context Builder 完成 | `codex_batches/B11_s3_fusion_context.md` |
| B12 | S3-08～S3-10 + S3 Gate | Activation/Trace、入口收敛和评测完成，S3 Gate PASS | `codex_batches/B12_s3_entrypoints_eval_gate.md` |
| B13 | S4-01～S4-03 | Outbox、Projection Version 和 Repair 完成 | `codex_batches/B13_s4_projection_repair.md` |
| B14 | S4-04～S4-06 | Forget 状态机、管理接口和诊断 API 完成 | `codex_batches/B14_s4_forget_diagnostics.md` |
| B15 | S4-07～S4-08 + S4 Gate | 故障注入与可靠性指标完成，S4 Gate PASS | `codex_batches/B15_s4_reliability_gate.md` |
| B16 | S5-01～S5-04 | 统一 Trace、Benchmark、对照实验和 Dashboard 完成 | `codex_batches/B16_s5_benchmark_dashboard.md` |
| B17 | S5-05～S5-08 | Feedback、迁移、Shadow/双读和灰度切流完成 | `codex_batches/B17_s5_migration_cutover.md` |
| B18 | S5-09～S5-10 + S5/P0/P1/Release Gate | 文档、演示、全量验收和回滚证据齐全 | `codex_batches/B18_release.md` |

任何正式任务只属于一个批次。不得因为“还有执行空间”越过批次边界。

## 4. 所有批次共用的硬规则

### 4.1 会话启动

每个新会话必须：

1. 从用户发送的批次提示词中确定唯一 `batch_id`。
2. 完整读取本手册、该批次提示词、执行任务方案、当前作用域的 `AGENTS.md` 和全部连续性文件。
3. 在修改代码前核对当前时间、工作目录、Git branch/HEAD/status/diff、已完成任务的产物与证据。
4. 确认 `BATCH_BOARD.md` 中唯一 `IN_PROGRESS` 批次与本提示词一致。
5. 如果状态与仓库不一致，先将事实、判断和处理写入 `STATE.md`，不盲信交接文本。
6. 向用户发送一条简短恢复更新：当前批次、已核对事实、本会话边界和第一个精确操作。

### 4.2 批次内执行

1. 只处理当前批次列出的正式任务、该批次 Gate 和它们必需的小型修正。
2. 批次内仍一次只领取一个正式任务；完成和验收后才可领取本批次的下一个任务。
3. 任务顺序以依赖为先，同等条件下优先最小编号。
4. 实现前读取现有代码和测试；优先复用既有 Policy、Authority、Evidence/Lineage、Outbox、Retrieval 和 evaluation 基础。
5. 不得覆盖、重置或删除用户的无关修改；不主动提交、推送、发布或做不可逆数据操作。
6. 每个正式任务必须经过：实现→定向测试→受影响回归→风险测试→证据固化→逐项验收。
7. 每完成一个可独立验证的检查点，立即更新 `STATE.md`、`TASK_BOARD.md`、`EVIDENCE.md`；重要设计判断追加到 `DECISIONS.md`。
8. DONE 必须有可复现证据；验收未满足则保持 `IN_PROGRESS` 或按事实记录 `BLOCKED`。

### 4.3 批次级 Git 提交

1. 本批次提示词明确授权：只有当前批次全部任务和 Gate（如有）通过后，执行一次本地 `git commit`。
2. 批次内的中间检查点、单个正式任务完成、会话因时间中断或批次被阻断时均不得提交；下一个会话继续同一批次，直到完整验收。
3. 提交前必须检查 `git status`、`git diff` 和暂存区，只暂存当前批次产物及本次必须更新的连续性文件。禁止使用无审查的全仓暂存，禁止夹带用户的无关修改。
4. 提交前先把当前批次/任务写成完成状态、下一批次写成 `READY`，并在 `BATCH_BOARD.md` 的 Commit 栏写 `SELF (Batch-ID: Bxx)`；这样连续性文件本身也包含在该批次唯一提交中。
5. 推荐提交标题：`feat(vnext): complete Bxx <batch-name>`；纯文档或治理批次可使用 `docs(vnext): complete Bxx <batch-name>`。提交正文必须包含唯一 trailer：`Batch-ID: Bxx`。
6. 提交成功后只做只读验证：取得 HEAD SHA、核对提交文件和相关工作区是否干净，并在最终答复中报告 SHA。不要为了把 SHA 回填进文件而产生第二个提交；后续会话通过 `git log --grep="Batch-ID: Bxx"` 解析精确 SHA。
7. 提交失败时，撤回尚未成立的 DONE/READY 状态或保持批次 `IN_PROGRESS`，记录错误和精确重试命令；不得假装 DONE，也不得进入下一批次。
8. 不得对批次提交执行 `--amend`、rebase、reset、push 或历史重写，除非用户另行明确授权。本规则只授权一次本地普通提交。
9. 一个批次只对应一个完成提交；一个提交也不得混入下一批次内容。

### 4.4 严格批次停止条件

出现以下任一情况，本会话必须停止实施并交接：

- 当前批次全部任务和 Gate（如有）已验收通过；
- 当前批次存在无法在本会话解除的 Blocker；
- 环境、时间或上下文不足以安全完成本批次剩余工作。

批次完成时，必须把完成状态和下一批次 READY 状态一起纳入该批次唯一 Git 提交；提交成功并只读验证后，只允许在最终答复中报告 SHA 和下一份提示词路径。

**禁止在同一会话中执行、领取、试做、预研或预先修改下一批次的代码。“还有执行空间”不是越批授权。**

### 4.5 会话交接

每个会话结束前必须：

1. 更新 `STATE.md` 的当前批次、批次状态、批次内当前任务、最后证据、Blocker 和精确下一步。
2. 更新 `BATCH_BOARD.md` 和 `TASK_BOARD.md`，且分别最多只有一个 `IN_PROGRESS`；批次完成时记录唯一 commit SHA。
3. 把实际命令、结果、环境、指标和产物写入 `EVIDENCE.md`。
4. 在 `SESSION_LOG.md` 追加一条，明确记录 `batch_id`、已完成、未完成、修改文件、测试、Blocker 和下一条可执行命令。
5. 最终答复只汇报当前批次，不宣称未执行的下一批次已开始。

## 5. 状态对账与 Blocker

新会话必须用代码、测试、文档、Git 现场和产物路径对账：

| 对账对象 | 检查方式 | 不一致时处理 |
|---|---|---|
| 当前批次 | `BATCH_BOARD` 的唯一 `IN_PROGRESS`，或最早 `READY` | 不自动跳批；先恢复真实批次 |
| 当前任务 | `TASK_BOARD` 的唯一 `IN_PROGRESS` | 多个时停止领取，按代码与证据恢复 |
| 已完成任务 | 产物路径、测试、`EVIDENCE` | 证据失效则重新打开该任务 |
| Git 现场 | branch、HEAD、status、diff | 保留未知修改，不覆盖 |
| Schema/API | ORM、迁移、路由、客户端、契约测试 | 不可运行或入口未收敛时不算完成 |
| 安全 | Policy、租户、Forget、版本过滤测试 | 泄漏直接阻断当前 Gate |
| 评测 | 可复现命令、数据集 hash、环境与报告 | 只有报告没有命令时标记 PARTIAL |

仅在缺少用户授权、外部环境、密钥、真机、不可推断的产品决策或上游产物，且已穷尽安全范围内检查时，才标记 `BLOCKED`。Blocker 不授权转入下一批次。

## 6. 使用方法

1. 打开 `codex_execution/BATCH_BOARD.md`，选择唯一 `IN_PROGRESS` 批次；如果没有，选择最早 `READY` 批次。
2. 在新会话中明确要求“按 `<批次提示词路径>` 执行”。
3. 会话结束后，根据交接结果，在下一个新会话中发送同一批次（未完成）或下一批次（已完成）的提示词。

不要使用“持续到 S0～S5 全部完成”作为单个会话的 `/goal`。如果使用目标功能，目标必须只包含当前批次，并把“完成后交接、不进入下一批次”写入停止条件。

## 7. 现有进度迁移

旧版提示词曾允许“当前会话仍有执行空间时领取下一个 READY 任务”，因此同一会话已从 S0 推进到 S1-03。这些已完成任务只要代码和证据对账有效，仍保持 DONE，不因新批次模型重做。

新模型下的当前批次是 **B03（S1-01～S1-03）**。B03 完成后必须停止；B04 只能在用户开启的新会话中执行。

B01/B02 的历史工作已按任务归属追溯拆分并完成独立提交：B01=`a502f9a`，B02=`1b84af1`。当前 B03 业务变更仍留在工作区，后续完整验收后按标准规则创建自己的唯一提交；不再需要 transition baseline 例外。

## 8. 全局完成条件

只有 B01～B18 全部 DONE，57 个正式任务全部 DONE，S0～S5、P0、P1 和 Release Gate 全部 PASS，且无未解决的安全、租户、数据一致性、Forget 或回滚阻断时，整个 MemoryHub vNext 目标才算完成。

该全局完成条件只用于项目验收，不授权任何单个会话跨批次执行。
