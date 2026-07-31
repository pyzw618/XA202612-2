# OS Agent Memory Engine

## 项目定位

为 AI Agent 提供本地记忆存储与混合检索能力。当前代码实现了 Embedding 适配、SQLite 持久化，以及 BM25 + FAISS 混合检索的基础能力。

## 当前阶段

- 当前阶段：Phase 02 — Memory API（规划中，尚未开始编码）
- 已完成阶段：Phase 01 — Hybrid Memory Search
- 阶段文档：`docs/phases/`
- 当前优先事项：在开始 Phase 02 前补齐该阶段的 `DESIGN.md` 和 `TASKS.md`。

## 当前架构

- `src/embedding/`：Embedding 接口及其实现。默认工厂 `create_embedding_client()` 会选择合适的适配器；开发环境可使用 Mock 实现。
- `src/memory_store.py`：`MemoryRecord` 的 SQLite 持久化，负责记录的增删查与加载。
- `src/search_engine.py`：BM25、FAISS 和加权混合检索；`MemorySearchEngine` 是统一检索入口。
- `tests/test_search.py`：现有端到端检索验证脚本。

## 关键约束

- SQLite 是记忆记录的事实来源；FAISS 文件是可重建的检索索引。
- Embedding 向量维度必须与 FAISS 索引维度一致。
- `MemoryRecord.id` 是 SQLite 记录和 FAISS 索引映射之间的稳定标识。
- 保持 `MemoryStore` 与 `MemorySearchEngine` 的既有调用方式兼容；如必须破坏兼容性，先在阶段 `DESIGN.md` 说明迁移方案。
- 不要将真实密钥、密码或用户敏感记忆提交到仓库、测试样本或文档。

## 文档与开发流程

1. 先阅读本文件，确认项目状态和约束。
2. 阅读当前阶段目录的 `DESIGN.md` 和 `TASKS.md`。
3. 阅读涉及模块的代码与现有测试后再修改。
4. 按阶段 `DESIGN.md` 的验收标准运行相关测试。
5. 完成任务后勾选或更新 `TASKS.md`；实现偏离设计时同步更新 `DESIGN.md`。
6. 阶段完成时写 `SUMMARY.md`，冻结该阶段的设计结论、验证结果与遗留项，再更新本文件中的“当前阶段”。

## 文档规则

- `DESIGN.md`：记录本阶段的目标、范围、设计、接口和验收标准。
- `TASKS.md`：仅记录可执行任务、状态和当前任务，保持简短。
- `SUMMARY.md`：阶段结束时编写，之后不覆盖历史结论。
- 长期影响多个阶段的决策，必须在对应阶段的 `SUMMARY.md` 中说明“选择、原因和后果”。

