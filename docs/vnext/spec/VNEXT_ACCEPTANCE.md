# MemoryHub vNext 最终验收报告

版本：`vnext/v1`

批次：`B18`

日期：2026-08-26

## 验收结论

MemoryHub vNext **S0～S5 的历史验收保持通过；S6-04 最终验收在本报告的检查项全部完成后生效**。

- 所有写入口统一进入 `CanonicalWriteService`，无生产旁路。
- Working/Episode/Candidate/Long-Term 具备明确契约与状态机。
- `/search`、`/context`、MCP、CLI、SDK 复用同一 `RetrievalService`。
- Authority Store 是唯一事实来源；Vector/BM25/Cache 可删除并重建。
- Candidate 默认不进入普通检索。
- Forget 后 Authority 立即阻断读取，Projection 异步清除，残留为 0。
- P0/P1 场景全部通过，Trace 可解释。
- 新旧链路完成双读对比和回滚演练。

## 批次与任务状态

| 批次 | 任务 | 状态 | 证据 |
|---|---|---|---|
| B01 | S0-01～S0-04 | DONE | EVIDENCE.md#s0-01 等 |
| B02 | S0-05～S0-08；S0 Gate | DONE/PASS | EVIDENCE.md#s0-gate |
| B03 | S1-01～S1-03 | DONE | EVIDENCE.md#s1-03-final-validation-checkpoint |
| B04 | S1-04～S1-06 | DONE | EVIDENCE.md#s1-06-and-b04-final-validation |
| B05 | S1-07～S1-08 | DONE | EVIDENCE.md#s1-08-final-validation-and-b05-acceptance |
| B06 | S1-09～S1-11；S1 Gate | DONE/PASS | EVIDENCE.md#s1-gate |
| B07 | S2-01～S2-03 | DONE | EVIDENCE.md#s2-03-checkpoint |
| B08 | S2-04～S2-07 | DONE | EVIDENCE.md#s2-07-checkpoint |
| B09 | S2-08～S2-10；S2 Gate | DONE/PASS | EVIDENCE.md#b09-final-validation-and-acceptance |
| B10 | S3-01～S3-03 | DONE | EVIDENCE.md#s3-03-checkpoint |
| B11 | S3-04～S3-07 | DONE | EVIDENCE.md#s3-07-checkpoint |
| B12 | S3-08～S3-10；S3 Gate | DONE/PASS | EVIDENCE.md#b12-final-validation-and-s3-gate-acceptance |
| B13 | S4-01～S4-03 | DONE | EVIDENCE.md#s4-03-checkpoint |
| B14 | S4-04～S4-06 | DONE | EVIDENCE.md#s4-06-checkpoint |
| B15 | S4-07～S4-08；S4 Gate | DONE/PASS | EVIDENCE.md#s4-gate |
| B16 | S5-01～S5-04 | DONE | EVIDENCE.md#b16-final-validation-and-acceptance |
| B17 | S5-05～S5-08 | DONE | EVIDENCE.md#s5-08-and-b17-final-acceptance |
| B18 | S5-09～S5-10；S5/P0/P1/Release Gate | DONE/PASS | EVIDENCE.md#b18-final-acceptance |

## Gate 检查清单

### S0 Gate

- [x] 术语、状态机和 7 类 Intent 无重复定义
- [x] API 与数据契约已冻结为 `vnext/v1`
- [x] Feature Flag 可关闭任意新链路
- [x] 基线报告可重复生成
- [x] Schema 变更有升级和回滚方案

### S1 Gate

- [x] Policy 在任何持久化、日志与异步任务前生效
- [x] 重复事件不会重复更新 Working、Evidence 或统计
- [x] Working/Episode 可跨进程恢复
- [x] Candidate 不进入普通检索
- [x] 任意生产写入口无法绕过 Canonical Write Service
- [x] 索引损坏后可由 Authority 重建

### S2 Gate

- [x] “这次用 DOCX”只形成局部 Candidate，不形成 Global Preference
- [x] 多个独立任务中的明确证据能推动 Candidate 固化
- [x] Global Markdown 与 Project-A DOCX 以 COEXIST 保存并按 Scope 生效
- [x] 两次成功修复可形成带验证步骤的 Procedure
- [x] 所有形成和演化决策可由 Evidence、阈值和 reason code 解释

### S3 Gate

- [x] 7 类 Intent 均有标注样本和可解释路由结果
- [x] 精确、改写、语义表达可进入统一候选池和统一排序
- [x] Candidate、DELETED、SUPERSEDED 和其他租户记忆无法进入 Context
- [x] 有限预算下硬约束与当前步骤不丢失
- [x] REST/MCP/CLI/SDK 不存在各自拼 Context 的实现

### S4 Gate

- [x] Authority 提交前失败无半条数据；提交后失败可由 Outbox 恢复
- [x] Outbox 重复和乱序不会造成降版本或删除对象复活
- [x] 索引全损坏可在目标 RTO/RPO 内重建
- [x] Forget 验收查询 residual retrieval count = 0
- [x] 降级时允许少返回，但不允许越权、泄漏或返回已删除数据

### S5 Gate

- [x] P0/P1 全部测试与场景通过
- [x] Policy Leakage、跨租户泄漏、Forget 残留均为 0
- [x] 任务成功率、用户纠正率、Context Tokens、延迟已与基线比较
- [x] 迁移、索引重建、服务回滚均至少演练一次
- [x] Dashboard 和演示数据不包含未脱敏正文
- [x] 旧写入关闭后，旧读取兼容窗口和最终下线日期已登记（见下节）

### S6-04 / Release Gate

- [x] 六类固定演示及 `all` 在干净环境重放通过
- [x] README 中的演示命令与输出契约自动化验证通过
- [x] 完整受影响回归、安全/Policy/租户/Forget、lint、compile、diff 检查通过
- [x] 旧读取兼容窗口、负责人和最终下线日期已真实登记

## 旧读兼容窗口登记

| 字段 | 登记值 |
|---|---|
| 旧写入关闭时间 | 2026-08-26（S6-04 验收基线） |
| 旧读取兼容窗口 | 2026-08-26 00:00（Asia/Shanghai）至 2026-09-25 23:59（Asia/Shanghai） |
| 最终下线日期 | 2026-09-26（Asia/Shanghai） |
| 负责人 | Mr.X（Git 发布身份：111974179+Weirdo-1224@users.noreply.github.com） |
| 登记状态 | REGISTERED；窗口期间保留 legacy read、Authority 单写和只读回滚 |
| 依据 | `docs/vnext/spec/VNEXT_ROLLOUT.md`、`docs/vnext/spec/VNEXT_MIGRATION.md`、S6-04 验收记录 |

Release 只有在上方三个未完成项全部勾选，且登记状态仍为 `REGISTERED` 时才可勾选完成。

## 交付物清单

### 工程交付

- [x] vNext 领域契约、应用服务、Repository 和迁移脚本
- [x] Working/Episode/Candidate/Long-Term 完整形成链
- [x] 统一 Retrieval/Context/Activation 链
- [x] 版本化 Outbox、Repair、Forget 状态机
- [x] REST/MCP/CLI/SDK 兼容实现
- [x] Feature Flag、Shadow、双读、灰度和回滚配置
- [x] 全量测试、故障注入与生产环境检查脚本

### 评测与展示交付

- [x] Formation、Working/Episode、Retrieval/Context、Reliability、E2E 数据集
- [x] No Memory、Flat RAG、Original、vNext 对照报告
- [x] Candidate、Evidence、Scope、Router、Reranker、Episode 消融报告
- [x] Memory Explorer、Evolution、Retrieval Debugger、Benchmark Dashboard
- [x] 固定可重放的比赛演示场景与 Trace
- [x] 指标基线、最终结果、环境 manifest 与数据集 hash

### 文档交付

- [x] 术语表、ADR、数据契约、API 契约、Trace 契约
- [x] 数据迁移、部署、备份恢复、Repair、Forget 与回滚手册
- [x] 用户手册和 Agent 接入说明
- [x] 项目创新说明、实验方法、结果分析和已知限制
- [x] 最终验收报告与发布签字记录

## 已知限制

- 生产 Milvus/Kylin 性能需在真机环境做最终验收；当前 Mock/FAISS 证据已证明功能正确性。
- Windows 仅作开发验证；生产目标为银河麒麟 V11 x86_64。
- 桌面客户端 Qt 构建受限于本地 `cmake` 可用性，已记录为 PARTIAL。

## 发布建议

1. 在银河麒麟真机执行 `evaluation/runners/run_vnext_eval.py --suite all` 性能验收。
2. 按 `docs/vnext/spec/VNEXT_ROLLOUT.md` 执行 5%→25%→50%→100% 灰度切流。
3. 切流期间每日执行 `scripts/repair_projections.py --dry-run` 与 `tests/test_forget_semantic.py`。
4. 旧读取兼容窗口已登记为 2026-08-26 至 2026-09-25，最终下线日期为 2026-09-26；窗口期结束前由负责人复核并执行下线。
