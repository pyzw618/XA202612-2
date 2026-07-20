# Phase 01：Hybrid Memory Search

## 目标

验证本地 AI Agent 记忆的基础能力：生成或接收 Embedding、持久化 MemoryRecord，并通过关键词与向量混合检索返回相关记忆。

## 范围

- Embedding 抽象，以及 Mock 和 Kylin 实现。
- SQLite 持久化 MemoryRecord。
- BM25、FAISS 和加权 Hybrid Search。
- FAISS 索引保存与加载。

## 设计结论

- `MemoryStore` 使用 SQLite 保存记忆记录，作为数据事实来源。
- `MemorySearchEngine` 统一组合 BM25 与 FAISS 两条检索路径。
- FAISS 使用记录 ID 与内部索引位置的映射，索引文件可由 SQLite 中的记录重建。
- 开发环境使用确定性的 Mock Embedding；部署环境预留 Kylin Embedding 适配器。

## 关键约束

- 向量维度必须与 FAISS 索引维度相同。
- 写入数据与检索索引的一致性由后续阶段继续完善。
- 测试数据不得使用真实密钥、密码或个人信息。

## 验收标准

- 能够写入、读取和删除 MemoryRecord。
- 能够执行 BM25、FAISS 与 Hybrid Search。
- 索引能够保存，并在重启后加载。

