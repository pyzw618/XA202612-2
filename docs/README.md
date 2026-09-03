# 文档索引

Kylin MemoryHub（XA-202612 赛题）当前有效文档。**本目录只描述项目的最终状态**；历史过程文档（历次重构计划、执行日志、验收快照）统一归档在仓库根目录 `old/`，不作为开发依据。

## 入门与总览

| 文档 | 内容 |
|---|---|
| [../README.md](../README.md) | 项目总览、快速开始、仓库结构 |
| [赛题要求.md](赛题要求.md) | 比赛题目原文（需求基准） |
| [architecture.md](architecture.md) | 系统架构：分层视图、写入/读取/形成/反馈链路、安全、灰度、可观测性 |

## 使用与运维

| 文档 | 内容 |
|---|---|
| [api.md](api.md) | REST API 参考（6 组 Router 全部路由 + 核心数据契约） |
| [configuration.md](configuration.md) | 全部配置键、环境变量、生产门禁、密钥管理 |
| [deployment.md](deployment.md) | 开发/生产部署、麒麟运行时、DEB 打包、备份恢复、运维脚本 |
| [evaluation.md](evaluation.md) | 评测体系：数据集、指标、驱动脚本、验收结果 |
| [development.md](development.md) | 开发指南：环境、测试、代码规范、文档维护约定 |

## Agent 接入与客户端

| 文档 | 内容 |
|---|---|
| [../agent-integration/README.md](../agent-integration/README.md) | CLI / Python SDK / MCP / OpenCode 插件（接入层权威文档） |
| [../desktop-client/README.md](../desktop-client/README.md) | Qt 桌面控制台构建与页面说明 |
| [../packaging/linux/README.md](../packaging/linux/README.md) | 麒麟 DEB 打包与安装 |

## vNext 规格与契约（docs/vnext/）

vNext 是当前默认主链路的权威规范，与实现共同演进：

| 文档 | 内容 |
|---|---|
| [vnext/VNEXT_PLAN.md](vnext/VNEXT_PLAN.md) | vNext 总体计划（S0–S5 工作分解） |
| [vnext/design/ADR-vnext-memory-architecture.md](vnext/design/ADR-vnext-memory-architecture.md) | 架构决策记录：Authority 与投影边界 |
| [vnext/spec/VNEXT_GLOSSARY.md](vnext/spec/VNEXT_GLOSSARY.md) | 术语表 |
| [vnext/spec/VNEXT_DATA_CONTRACT.md](vnext/spec/VNEXT_DATA_CONTRACT.md) | 数据契约 |
| [vnext/spec/VNEXT_INTERFACE.md](vnext/spec/VNEXT_INTERFACE.md) | REST 接口规范 |
| [vnext/spec/VNEXT_STORAGE_SCHEMA.md](vnext/spec/VNEXT_STORAGE_SCHEMA.md) | 存储 Schema |
| [vnext/spec/VNEXT_EVENT_GATEWAY.md](vnext/spec/VNEXT_EVENT_GATEWAY.md) | 事件网关 |
| [vnext/spec/VNEXT_AUTHORITY_WRITE.md](vnext/spec/VNEXT_AUTHORITY_WRITE.md) | Authority 单写者 |
| [vnext/spec/VNEXT_TRACE.md](vnext/spec/VNEXT_TRACE.md) | 脱敏 Trace 契约 |
| [vnext/spec/VNEXT_MIGRATION.md](vnext/spec/VNEXT_MIGRATION.md) | 迁移与回滚 |
| [vnext/spec/VNEXT_ROLLOUT.md](vnext/spec/VNEXT_ROLLOUT.md) | 灰度切流 |
| [vnext/spec/VNEXT_BACKUP_RECOVERY.md](vnext/spec/VNEXT_BACKUP_RECOVERY.md) | 备份与恢复 |
| [vnext/spec/VNEXT_FAULT_HANDLING.md](vnext/spec/VNEXT_FAULT_HANDLING.md) | 故障处理 |
| [vnext/spec/VNEXT_DEPLOYMENT.md](vnext/spec/VNEXT_DEPLOYMENT.md) | 部署运维手册 |
| [vnext/spec/VNEXT_ACCEPTANCE.md](vnext/spec/VNEXT_ACCEPTANCE.md) | 验收标准 |
| [vnext/spec/VNEXT_GOLDEN_FIXTURES.md](vnext/spec/VNEXT_GOLDEN_FIXTURES.md) | Golden 测试夹具 |

> `docs/vnext/spec/` 中的运维六篇（DEPLOYMENT / BACKUP_RECOVERY / FAULT_HANDLING / MIGRATION / ROLLOUT / ACCEPTANCE）由 `tests/test_vnext_docs.py` 守护：文件缺失或关键命令失效会导致测试失败。

## 参考资料（docs/reference/）

| 文档 | 内容 |
|---|---|
| [reference/kylin-embedding-runtime-contract.md](reference/kylin-embedding-runtime-contract.md) | 麒麟 Embedding 运行时契约（部署前逐项核对） |
| [reference/kylin/kylin-embedding-sdk-api-signatures.md](reference/kylin/kylin-embedding-sdk-api-signatures.md) | kylin-coreai-embedding C API 签名（`embedding/kylin_client.py` 依据） |
| [reference/kylin/kylin-vector-engine-sdk-api-signatures.md](reference/kylin/kylin-vector-engine-sdk-api-signatures.md) | libkysdk-vector-engine-client C API 签名 |
| [reference/kylin/milvus-c-api-minimal-interface.md](reference/kylin/milvus-c-api-minimal-interface.md) | Milvus C API 最小接口（`storage/vector_engine/_milvus_ctypes.py` 依据） |
| [reference/kylin/kylin-environment-handoff-checklist.md](reference/kylin/kylin-environment-handoff-checklist.md) | 麒麟真机环境交接清单 |
