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
│   ├── user_rule_schemas.py # 用户敏感规则 REST DTO
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

1. **数据结构**: 运行时记忆/安全契约在 `memoryhub/adapter/schemas.py`；
   声明式规则与溯源模型在 `memoryhub/safety_rules/models.py`
2. **接口规范**: 参见 `docs/INTERFACE.md`
3. **规则库**: 内置版本、完整性摘要和来源矩阵见
   `memoryhub/safety_rules/data/` 与 `docs/SAFETY_RULE_LIBRARY.md`
4. **安全边界**: 规则加载/校验、递归扫描、策略决策、全值脱敏、同快照复检、
   用户自定义规则 Overlay、实例内结果认证、最小化 JSONL 审计链、REVIEW 加密隔离
   和强制写入 Gate 已实现。
   普通 SQLite/向量/证据算法仍是脚手架；实现时只能注册为 Gate 的受保护 sink，
   不得接收原始事件或裸文本

## 安全写入链

生产写入从 `SafetyWriteGate` 进入：先完成 `process → validate_result`，再成功追加
脱敏审计记录，最后按动作路由。`ALLOW/MASK` 只向 SQLite、Embedding、向量、
证据链等内容 sink 签发绑定审计记录的 `ApprovedWrite`，普通日志只接收最小化
`SafeLogRecord`；`REVIEW` 原事件只以 AES-256-GCM 密文进入独立隔离区；`REJECT`
不保留原文。审计或隔离失败时不会调用任何普通下游。

前端可通过 `/api/memory/safety/user-rules` CRUD 管理当前用户的敏感规则。
`mask_match` 遮盖命中片段，`drop_event` 跳过整条待记忆事件；matcher 只写不读并以
AES-256-GCM 加密。启用前需把独立的 32 字节随机密钥以 Base64 写入
`MEMORYHUB_USER_RULE_KEY`，由认证网关注入可信 `X-MemoryHub-User` 请求头，并向
`create_app()` 注入基于认证会话的 `user_rule_identity_resolver`；缺少 resolver
时管理接口默认失败关闭。

当前仓库的 `/api/memory/events` 和普通存储业务仍是脚手架。本次已提供
`UserRuleService.detector_provider()` 与 `SafetyWriteGate.from_user_rule_config()`
接线点；实现真实写入端点时必须通过该 Gate，规则才会在每次实际记忆写入中生效。

安全配置与密钥要求见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)，数据契约、
轮转/保留和平台权限边界见 [`docs/INTERFACE.md`](docs/INTERFACE.md)，完整验收矩阵
见 [`docs/SAFETY_ACCEPTANCE.md`](docs/SAFETY_ACCEPTANCE.md)。

## 技术栈

| 组件 | 选型 |
|------|------|
| 服务框架 | FastAPI |
| 结构化存储 | SQLite + SQLAlchemy |
| 向量存储 | FAISS |
| Embedding | 麒麟 SDK / Mock |
| LLM | OpenAI 兼容 API / Ollama |
| 前端 | Vue 3 + Element Plus |
