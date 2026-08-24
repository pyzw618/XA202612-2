# MemoryHub vNext Task Board

状态：TODO | READY | IN_PROGRESS | BLOCKED | DONE | DEFERRED

## Gate status

| Gate | Status | Evidence |
|---|---|---|
| S0 | PASS | EVIDENCE.md#s0-gate |
| S1 | PASS | EVIDENCE.md#s1-gate |
| S2 | TODO | |
| S3 | TODO | |
| S4 | TODO | |
| S5 | TODO | |
| P0 | TODO | |
| P1 | TODO | |
| Release | TODO | |

## Tasks

| ID | Status | Depends on | Owner/session | Evidence | Note |
|---|---|---|---|---|---|
| S0-01 | DONE | None | Codex 2026-08-22 | EVIDENCE.md#s0-01 | 枚举、术语和旧值映射；31 项组合测试通过 |
| S0-02 | DONE | S0-01 | Codex 2026-08-22 | EVIDENCE.md#s0-02 | ADR 与边界检查通过 |
| S0-03 | DONE | S0-01 | Codex 2026-08-22 | EVIDENCE.md#s0-03 | vnext/v1 核心对象、fixture 与 58 项回归通过 |
| S0-04 | DONE | S0-03 | Codex 2026-08-22 | EVIDENCE.md#s0-04 | API DTO、接口文档、兼容响应与 38 项组合回归通过 |
| S0-05 | DONE | S0-03 | Codex 2026-08-22 | EVIDENCE.md#s0-05 | dry-run、报告、只读和回滚文档通过 |
| S0-06 | DONE | S0-02 | Codex 2026-08-22 | EVIDENCE.md#s0-06 | 五模式、生产 fail-closed 和配置样例通过 |
| S0-07 | DONE | None | Codex 2026-08-22 | EVIDENCE.md#s0-07 | 基线报告；Hybrid 依赖缺失已保留失败证据，vector-only fallback 指标通过 |
| S0-08 | DONE | S0-03, S0-04 | Codex 2026-08-22 | EVIDENCE.md#s0-08 | Golden fixtures、SHA-256 和 44 项 S0 Gate 回归通过 |
| S1-01 | DONE | S0-03, S0-05 | Codex 2026-08-22 | EVIDENCE.md#s1-01 | 7 张表、治理字段、约束/索引、legacy additive migration 和幂等初始化通过 |
| S1-02 | DONE | S1-01 | Codex 2026-08-22 | EVIDENCE.md#s1-02 | CAS/seq/状态迁移/Evidence 去重/Activation 事务测试通过 |
| S1-03 | DONE | S0-04, S1-02 | Codex 2026-08-22 | EVIDENCE.md#s1-03-final-validation-checkpoint | 11 定向、45 受影响回归通过；安全风险环境 PARTIAL 已记录 |
| S1-04 | DONE | S1-02, S1-03 | Codex 2026-08-22 (B04) | EVIDENCE.md#s1-04-checkpoint | Working State Patch/CAS |
| S1-05 | DONE | S1-02, S1-04 | Codex 2026-08-22 (B04) | EVIDENCE.md#s1-05-checkpoint | Episode Append/Snapshot/Resume |
| S1-06 | DONE | S1-02 | Codex 2026-08-22 (B04) | EVIDENCE.md#s1-06-and-b04-final-validation | Candidate Repository 与检索隔离 |
| S1-07 | DONE | S0-03, S1-02 | Codex 2026-08-22 (B05) | EVIDENCE.md#s1-07-checkpoint | Long-Term Authority Facade |
| S1-08 | DONE | S1-03, S1-04, S1-05, S1-06, S1-07 | Codex 2026-08-22 (B05) | EVIDENCE.md#s1-08-final-validation-and-b05-acceptance | Canonical Write Service |
| S1-09 | DONE | S1-08 | Codex 2026-08-24 (B06) | EVIDENCE.md#s1-09-checkpoint | REST/MCP/CLI/SDK 写入口收敛 |
| S1-10 | DONE | S1-05, S1-08 | Codex 2026-08-24 (B06) | EVIDENCE.md#s1-10-checkpoint | 任务恢复接口与 P0 贯通 |
| S1-11 | DONE | S1-07 | Codex 2026-08-24 (B06) | EVIDENCE.md#s1-11-checkpoint | Authority 到 Projection 重建 |
| S2-01 | DONE | S1-04, S1-05 | Codex 2026-08-24 (B07) | EVIDENCE.md#s2-01-checkpoint | Boundary Detector 硬/规则触发、去抖、三类 Checkpoint |
| S2-02 | DONE | S1-06, S2-01 | Codex 2026-08-24 (B07) | EVIDENCE.md#s2-02-checkpoint | Reflection Schema/Prompt/重试，只产 Candidate |
| S2-03 | DONE | S2-02 | Codex 2026-08-24 (B07) | EVIDENCE.md#s2-03-checkpoint | Candidate 归一键、Scope、近重复合并、独立证据组 |
| S2-04 | TODO | S2-03 | | | Promotion Score 与 reason codes |
| S2-05 | TODO | S2-04 | | | Fast Path 治理 |
| S2-06 | TODO | S1-07, S2-04 | | | Evolution 状态变化 |
| S2-07 | TODO | S2-04, S2-06 | | | Long-Term 内容校验与 Procedure |
| S2-08 | TODO | S0-06, S2-02, S2-03, S2-04, S2-05, S2-06, S2-07 | | | Formation Shadow |
| S2-09 | TODO | S2-02, S2-03, S2-04, S2-05, S2-06, S2-07 | | | Formation/Evolution Trace |
| S2-10 | TODO | S2-08, S2-09 | | | Formation 与恢复评测 |
| S3-01 | TODO | S0-04 | | | Retrieval Request/Response |
| S3-02 | TODO | S3-01 | | | 7 类 Intent Router |
| S3-03 | TODO | S3-02, S1-07 | | | Retrieval Planner 与多通道 |
| S3-04 | TODO | S3-03 | | | Fusion 与 Reranker |
| S3-05 | TODO | S3-04, S2-06 | | | Authority 校验与 Scope Resolver |
| S3-06 | TODO | S3-05 | | | Context Budget Manager |
| S3-07 | TODO | S3-06 | | | Context Builder |
| S3-08 | TODO | S3-03, S3-04, S3-05, S3-06, S3-07 | | | Activation、Log、Trace |
| S3-09 | TODO | S3-08 | | | REST/MCP/CLI/SDK 检索收敛 |
| S3-10 | TODO | S3-09 | | | Retrieval/Context 评测 |
| S4-01 | TODO | S1-01, S1-07 | | | Outbox 升级 |
| S4-02 | TODO | S4-01, S3-08 | | | Projection Version 与 Authority Checked |
| S4-03 | TODO | S4-01, S4-02 | | | Repair Worker |
| S4-04 | TODO | S1-07, S4-01 | | | Forget 状态机 |
| S4-05 | TODO | S4-04 | | | Forget 管理接口 |
| S4-06 | TODO | S2-09, S3-08, S4-03 | | | 诊断 API |
| S4-07 | TODO | S4-01, S4-02, S4-03, S4-04, S4-05 | | | 故障注入矩阵 |
| S4-08 | TODO | S4-01, S4-02, S4-03, S4-04, S4-05, S4-07 | | | 基础设施 Trace/指标 |
| S5-01 | TODO | S2-09, S3-08, S4-08 | | | 五类 Trace 关联、采样、脱敏 |
| S5-02 | TODO | S2-10, S3-10, S4-07 | | | 四层 Benchmark Runner |
| S5-03 | TODO | S5-02 | | | 四系统对照与消融 |
| S5-04 | TODO | S4-06, S5-01, S5-02 | | | 四页 Dashboard |
| S5-05 | TODO | S3-08, S5-01 | | | Agent Usage/Feedback Shadow |
| S5-06 | TODO | S0-05, S1-01, S1-07 | | | 旧数据迁移与校验 |
| S5-07 | TODO | S2-08, S3-09, S5-06 | | | Shadow 与双读报告 |
| S5-08 | TODO | S5-07, S4 Gate | | | 灰度切流与回滚窗口 |
| S5-09 | TODO | S5-08 | | | REST/CLI/MCP/SDK 与运维文档 |
| S5-10 | TODO | S5-03, S5-04, S5-09 | | | 固定演示与最终验收包 |

## Invariant check

- IN_PROGRESS count: 0
- Dependency violations: None
- DONE without evidence: None
- Last checked: 2026-08-24 08:00 +08:00
