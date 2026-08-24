# docs 文档索引

Kylin-MemoryHub（XA-202612 赛题）项目文档导航。

## 核心文档（根目录，按 main 分支校正 v0.1.0）

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构与模块设计（分层视图 / 数据流 / 统一写入契约） |
| [INTERFACE.md](INTERFACE.md) | REST 数据契约（Schema 1.1，修改数据结构必须同步更新） |
| [CONFIGURATION.md](CONFIGURATION.md) | 配置与安全密钥要求 |
| [PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md) | 深入浅出讲解（新人入门） |
| [产品形态与使用方案.md](产品形态与使用方案.md) | 产品形态与使用方案 |
| [Agent接入设计.md](Agent接入设计.md) | Agent 接入方案（CLI / MCP / OpenCode Plugin 三面契约） |
| [前端页面规划.md](前端页面规划.md) | 桌面控制台 21 页设计规格（desktop-client 依据） |
| [毛玻璃侧边栏实现技术报告.md](毛玻璃侧边栏实现技术报告.md) | 毛玻璃侧边栏实现技术报告 |
| [KYLIN_EMBEDDING_RUNTIME_CONTRACT.md](KYLIN_EMBEDDING_RUNTIME_CONTRACT.md) | 麒麟 Embedding SDK 运行时契约（版本/架构/.so/DBus/768 维） |
| [MemoryHub_技术报告.md](MemoryHub_技术报告.md) | 项目技术报告 |
| [REFACTOR_PLAN_V2.md](REFACTOR_PLAN_V2.md) | 核心记忆模块重构计划 V2 |
| [银河麒麟安装与使用手册.md](银河麒麟安装与使用手册.md) | 银河麒麟安装与使用手册 |
| [赛题要求.md](赛题要求.md) | 赛题原始要求（XA-202612「OS Agent 记忆优化及高效应用研究」） |

## 测试与验收

| 目录 | 内容 |
|------|------|
| [0805数据流测试/](0805数据流测试/) | 数据流测试计划与结果 |
| [0811功能性测试/](0811功能性测试/) | 功能验收与 TEST_PLAN |

## vNext 专项（docs/MemoryHub vNext/ + 子目录）

| 目录 | 内容 |
|------|------|
| [MemoryHub vNext/](MemoryHub vNext/) | MemoryHub vNext A_B_C_D 一体化改进方案 |
| [spec/](spec/) | vNext 规范与契约（VNEXT_GLOSSARY / DATA_CONTRACT / INTERFACE / MIGRATION / STORAGE_SCHEMA / EVENT_GATEWAY / AUTHORITY_WRITE 等） |
| [design/adr/](design/adr/) | vNext 架构决策记录（ADR） |
| [last_improve/](last_improve/) | 改进执行任务方案与 codex 批次文档 |

## 其他主题目录

| 目录 | 内容 |
|------|------|
| [refactor/](refactor/) | 核心记忆模块重构（PHASE_A~I 计划与实施日志） |
| [retrieval/](retrieval/) | 检索 / 向量引擎 / Kylin 集成技术方案 |
| [kylin/](kylin/) | 麒麟原生化专项记录（麒麟数据库原生化过程） |

## 常用入口

- 新人入门：`PROJECT_ANALYSIS.md`（深入浅出）→ `ARCHITECTURE.md`（架构）
- 接口与数据契约：`INTERFACE.md`（**修改数据结构必须同步更新**）
- 部署与验收：`CONFIGURATION.md` + `KYLIN_EMBEDDING_RUNTIME_CONTRACT.md`
- 测试：`0811功能性测试/TEST_PLAN.md`（计划）、各 `*_ACCEPTANCE_RESULT.md`（验收结果）
