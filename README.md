# Kylin-MemoryHub

面向银河麒麟 OS Agent 的可插拔本地记忆中枢。

## 项目结构

```
memoryhub/                  # 核心 Python 包
├── app.py                  # FastAPI 应用入口
├── config.py               # 配置管理
├── adapter/                # OS Agent 接入适配层
│   ├── api.py              # REST 路由定义
│   ├── schemas.py          # 核心数据结构 (Pydantic)
│   └── simulator.py        # OS Agent 模拟器
├── core/                   # 记忆核心逻辑
│   ├── ingestion/          # 多源数据接入 (清洗/标准化/质量评分)
│   ├── preference/         # 偏好记忆 (抽取/置信度/版本管理)
│   ├── knowledge/          # 知识记忆 (抽取/模板/工作流挖掘)
│   ├── conflict/           # 冲突处理 (检测/解决)
│   ├── safety/             # 安全过滤与精准遗忘
│   └── lifecycle/          # 记忆生命周期管理
├── retrieval/              # 混合检索引擎
│   ├── hybrid.py           # 混合检索入口
│   ├── vector_search.py    # FAISS 向量检索
│   ├── keyword_search.py   # BM25 关键词检索
│   ├── reranker.py         # 重排序
│   └── cache.py            # LRU 缓存
├── storage/                # 持久化存储层
│   ├── database.py         # SQLite + SQLAlchemy
│   ├── models.py           # ORM 模型
│   ├── vector_store.py     # FAISS 索引管理
│   └── evidence_store.py   # 证据链存储
├── llm/                    # LLM 抽象层
│   ├── base.py             # 抽象接口
│   ├── openai_client.py    # OpenAI 兼容 API
│   └── ollama_client.py    # Ollama 本地推理
└── embedding/              # Embedding 抽象层
    ├── base.py             # 抽象接口
    ├── kylin_client.py     # 麒麟 SDK 封装
    └── mock_client.py      # 开发用 Mock

evaluation/                 # 评测模块
├── metrics/
│   ├── preference_eval.py  # 偏好提取评测
│   ├── retrieval_eval.py   # 检索评测
│   ├── conflict_eval.py    # 冲突处理评测
│   └── latency_benchmark.py # 性能基准测试

docs/
├── ARCHITECTURE.md         # 项目整体架构可视化
└── INTERFACE.md            # 数据结构与接口规范文档
```

## 快速开始

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动服务
uvicorn memoryhub.app:app --reload

# 访问 API 文档
# http://localhost:8000/docs
```

## 开发规范

1. **数据结构**: 所有模型定义在 `memoryhub/adapter/schemas.py`
2. **接口规范**: 参见 `docs/INTERFACE.md`
3. **实现约定**: 各模块接口已定义，具体功能 `raise NotImplementedError` 待实现

## 技术栈

| 组件 | 选型 |
|------|------|
| 服务框架 | FastAPI |
| 结构化存储 | SQLite + SQLAlchemy |
| 向量存储 | FAISS |
| Embedding | 麒麟 SDK / Mock |
| LLM | OpenAI 兼容 API / Ollama |
| 前端 | Vue 3 + Element Plus |
