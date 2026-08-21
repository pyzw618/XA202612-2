# docs 文档索引

Kylin-MemoryHub（XA-202612 赛题）项目文档导航。按主题分目录存放：

| 目录 | 内容 | 关键文档 |
|------|------|----------|
| `spec/` | 核心规范与契约（全项目常被引用） | [INTERFACE.md](spec/INTERFACE.md) · [ARCHITECTURE.md](spec/ARCHITECTURE.md) · [CONFIGURATION.md](spec/CONFIGURATION.md) |
| `design/` | 总体设计与总结 | [TECHNICAL_SUMMARY.md](design/TECHNICAL_SUMMARY.md) · [PROJECT_ANALYSIS.md](design/PROJECT_ANALYSIS.md) · [产品形态与使用方案.md](design/产品形态与使用方案.md) · [Agent接入设计.md](design/Agent接入设计.md) |
| `frontend/` | 前端（Qt 桌面客户端） | [前端页面规划.md](frontend/前端页面规划.md) · [毛玻璃侧边栏实现技术报告.md](frontend/毛玻璃侧边栏实现技术报告.md) |
| `kylin/` | 麒麟原生化专项（Embedding / 向量引擎） | [麒麟数据库原生化过程.md](kylin/麒麟数据库原生化过程.md) · [KYLIN_EMBEDDING_RUNTIME_CONTRACT.md](kylin/KYLIN_EMBEDDING_RUNTIME_CONTRACT.md) |
| `tests/` | 测试计划与验收结果 | [0805数据流测试/](tests/0805数据流测试/) · [0811功能性测试/](tests/0811功能性测试/)（含 [TEST_PLAN.md](tests/0811功能性测试/TEST_PLAN.md)） |
| `refactor/` | 核心记忆模块重构（计划、阶段日志、ADR） | [REFACTOR_PLAN_V2.md](refactor/REFACTOR_PLAN_V2.md) |
| `retrieval/` | 检索 / 向量引擎 / Kylin 集成技术方案 | 目录内日期命名文档（如 [2026-08-10_retrieval_performance_evaluation_plan.md](retrieval/2026-08-10_retrieval_performance_evaluation_plan.md)） |

## 根目录

- [赛题要求.md](赛题要求.md) — 赛题原始要求（XA-202612「OS Agent 记忆优化及高效应用研究」）

## 常用入口

- 新人入门：`design/PROJECT_ANALYSIS.md`（深入浅出）→ `design/TECHNICAL_SUMMARY.md`（技术总结）→ `spec/ARCHITECTURE.md`（架构）
- 接口与数据契约：`spec/INTERFACE.md`（**修改数据结构必须同步更新**）
- 部署与验收：`spec/CONFIGURATION.md` + `kylin/KYLIN_EMBEDDING_RUNTIME_CONTRACT.md`
- 测试：`tests/0811功能性测试/TEST_PLAN.md`（计划）、各 `*_ACCEPTANCE_RESULT.md`（验收结果）
