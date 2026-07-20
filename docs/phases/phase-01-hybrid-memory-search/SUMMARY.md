# Phase 01 Summary

- 状态：已完成

## 完成内容

- 提供了 Embedding 适配层，支持 Mock 与 Kylin 两种实现路径。
- 使用 SQLite 存储 `MemoryRecord`，其中包含内容、向量、时间和元数据。
- 实现 BM25、FAISS 和默认权重为 0.3 / 0.7 的混合检索。
- 支持 FAISS 索引及其记录 ID 映射的落盘和恢复。

## 最终设计结论

- SQLite 是记忆数据的事实来源；FAISS 仅承担可重建的向量检索索引角色。
- `MemorySearchEngine` 是检索逻辑的统一入口，调用方无需直接协调 BM25 和 FAISS。
- Embedding 实现通过适配层隔离，调用方只依赖统一的 Embedding 接口。

## 验证入口

- 基础检索验证脚本：`tests/test_search.py`。
- 依赖与运行说明：仓库根目录 `README.md`。

## 遗留问题

- 为写入、删除和索引更新建立明确的一致性策略。
- 支持 metadata 过滤和更丰富的 Memory Schema。
- 在真实 Embedding 模型和基准数据集上评估检索质量。
- 提供稳定的 HTTP 接口供 Agent 或上层应用调用。

## 下一阶段建议

以 Memory API 为下一阶段：先确定写入与搜索接口、错误语义和索引更新策略，再实现 FastAPI 层与集成测试。

