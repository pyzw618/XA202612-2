# 配置说明

> 配置权威定义：`memoryhub/config.py`（dataclass 强类型 + 校验）。本文与代码不一致时以代码为准，并请提交修正。

## 1. 加载机制与优先级

`load_config()` 的取值优先级（高 → 低）：

```
环境变量  >  YAML 配置文件  >  dataclass 默认值
```

1. **`.env` 自动加载**：服务启动时若工作目录（或上级目录）存在 `.env`，自动载入；**已存在的系统环境变量优先，不会被 `.env` 覆盖**。模板见 `.env.example`。
2. **YAML 查找顺序**：`load_config(config_path)` 显式参数 → 环境变量 `MEMORYHUB_CONFIG` → 当前目录 `config.yaml`。
3. 仓库内三份 YAML 的角色：

| 文件 | 角色 |
|---|---|
| `config.yaml` | 本地开发配置（development 模式，mock embedding + FAISS），已提交 |
| `config.example.yaml` | **生产配置样板**（production 模式全部键与注释），复制后按需修改 |
| `packaging/linux/assets/config.yaml` | DEB 安装包内置配置，装机后位于 `/etc/memoryhub/config.yaml` |

4. **服务监听地址/端口不在 YAML 中配置**，由 uvicorn 命令行参数控制：
   - 手动启动：`python -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8099`
   - 脚本启动：`scripts/start-memoryhub-service.{sh,ps1}` 读取 `MEMORYHUB_HOST`（默认 127.0.0.1）、`MEMORYHUB_PORT`（默认 8099）、`MEMORYHUB_PYTHON`
   - DEB 服务：启动器固定 `127.0.0.1:8099`

## 2. 运行模式（`runtime`）

| 键 | 默认 | 说明 |
|---|---|---|
| `runtime.mode` | `development` | `production` / `development` / `test` |
| `runtime.allow_fallback` | `true`（dev/test） | 是否允许降级后端；**production 强制 false** |

`production` 模式触发双层门禁（见 §10），禁止 `mock`、`kylin_mock`、`faiss`、`milvus_mock` 与任何静默降级。

## 3. vNext 链路切流（`vnext`）

| 键 | 默认 | 说明 |
|---|---|---|
| `vnext.mode` | `vnext` | `legacy` / `shadow` / `dual-read` / `canary` / `vnext`（读路径姿态，见 architecture.md §4） |
| `vnext.canary_percent` | `0` | 仅 canary 模式允许 `5/25/50/100`，其他模式必须为 0 |
| `vnext.policy_required` | `true` | 写入必须前置安全 Policy；**生产必须 true** |
| `vnext.authority_single_writer` | `true` | Authority 单写者；**生产必须 true** |
| `vnext.allow_policy_bypass` | `false` | **生产必须 false** |
| `vnext.allow_legacy_read_fallback` | `true` | 兼容读回滚窗口（不代表允许第二个 Authority 写者） |
| `vnext.rollback_window_minutes` | `60` | 每级切流后的可回滚时长 |
| `vnext.observation_window_requests` | `1` | 每级切流的观察窗口请求数 |
| `vnext.formation_mode` | `authority` | `shadow` / `candidate-only` / `authority`（形成链姿态） |
| `vnext.events_default` | `true` | 标准写入口（`/events`、`/sources/*`）默认路由到 vNext canonical write |

## 4. 存储（`storage`）

| 键 | 默认 | 说明 |
|---|---|---|
| `storage.db_path` | `data/memoryhub.db` | SQLite 事实源 |
| `storage.vector_index_path` | `data/vector_index` | FAISS 索引目录（派生数据） |
| `storage.evidence_path` | `data/evidence` | 兼容 JSONL 证据目录（权威证据在 SQLite） |
| `storage.cache_max_size` | `1000` | 检索缓存条数 |

## 5. 检索（`retrieval`）

| 键 | 默认 | 说明 |
|---|---|---|
| `retrieval.default_top_k` | `5` | 默认返回条数 |
| `retrieval.candidate_multiplier` | `4` | 各通道候选放大倍数（融合前） |
| `retrieval.max_query_chars` | `512` | 查询长度上限 |
| `retrieval.target_p95_ms` / `target_p99_ms` | `350` / `500` | 延迟目标（赛题：≤500ms） |
| `retrieval.vector_weight` / `keyword_weight` / `metadata_weight` | `0.6 / 0.3 / 0.1` | 融合权重 |
| `retrieval.rerank_enabled` | `true` | 重排开关 |
| `retrieval.cache_ttl_seconds` | `300` | 结果缓存 TTL |

## 6. LLM（`llm`）

| 键 | 默认 | 说明 |
|---|---|---|
| `llm.api_base` | `https://api.openai.com/v1` | OpenAI 兼容接口（仓库配置默认 dashscope） |
| `llm.api_key` | `""` | **仅经环境变量注入，禁止写入仓库** |
| `llm.model` | `gpt-4o-mini` | 仓库配置默认 `qwen-flash` |
| `llm.temperature` / `max_tokens` | `0.1` / `2048` | 生成参数 |
| `llm.fact_extraction_timeout_seconds` | `1.0` | 可选增强步骤的超时上限（LLM 不可用不阻塞写入） |

旧 `llm.provider` 键已废弃，加载时自动忽略（便于旧 YAML 迁移）。

## 7. Embedding 与向量引擎（`embedding` / `vector_engine`）

| 键 | 默认 | 说明 |
|---|---|---|
| `embedding.provider` | `mock` | `kylin`（生产）/ `kylin_mock` / `mock` / `auto` |
| `embedding.dimension` | `1024`（dev 默认） | **麒麟生产契约固定 768**；真实 SDK 下维度不符抛 `embedding.dimension_mismatch` |
| `embedding.model_name` | `""` | 生产模型 `ensemble-embd_gte-base_uint8-text` |
| `embedding.so_path` | `""` | 显式 .so 路径（空则按默认路径探测，见运行时契约文档） |
| `embedding.query_timeout_ms` | `250` | 单次调用超时（超时返回 `embedding.timeout`，不崩溃） |
| `vector_engine.provider` | `faiss` | `milvus`（生产）/ `milvus_mock` / `faiss` |
| `vector_engine.app_id` | `""` | **milvus / milvus_mock 必填**（部署平台提供），缺失直接配置报错 |
| `vector_engine.so_path` | `""` | Milvus C API 动态库显式路径 |
| `vector_engine.host` / `port` | `127.0.0.1` / `19530` | Milvus 服务地址 |
| `vector_engine.collection` | `memoryhub` | 集合名 |
| `vector_engine.dimension` | `768` | 向量维度 |
| `vector_engine.search_timeout_ms` | `120` | 检索超时 |

## 8. 记忆流水线（`extraction_retry` / `memory_tier` / `knowledge_merge`）

| 键 | 默认 | 说明 |
|---|---|---|
| `extraction_retry.enabled` | `true` | 持久化抽取重试 worker |
| `extraction_retry.interval_seconds` / `batch_size` | `30` / `20` | 重试周期与批量 |
| `memory_tier.enabled` | `true` | 记忆分层 |
| `memory_tier.short_ttl_hours` | `24` | 短期记忆 TTL |
| `memory_tier.scheduler_enabled` | `true` | 生命周期调度器 |
| `memory_tier.consolidate_interval_seconds` | `300` | 调度周期 |
| `memory_tier.degrade_health_threshold` | `0.3` | 长期 → 中期降级健康度阈值 |
| `knowledge_merge.name_weight` / `content_weight` / `steps_weight` | `0.35 / 0.35 / 0.30` | 知识等价/冲突判定权重 |
| `knowledge_merge.equivalent_threshold` / `conflict_threshold` | `0.72` / `0.58` | 判定阈值 |

## 9. 安全（`safety`）

顶层键：`rule_set_id`（`kylin-memoryhub.safety`）、`rule_set_version`（`1.0`）、`auto_mask`（true）、`reject_on_detect`（false，旧调用方迁移用，新代码以 policy 决策为准）、以及扫描器限额 `max_depth`（32，上限 64）、`max_field_chars`（65536）、`max_scan_bytes`（2MiB）、`max_scanned_fields`（10000）、`max_candidates`（2048）、`max_findings`（1024）、`max_path_chars`（4096）。

| 子节 | 关键键（默认） | 说明 |
|---|---|---|
| `safety.policy` | `fallback_action/on_scan_error/on_unmaskable=review`，`auto_sanitize=true`，`fail_closed=true`，`rule_overrides/level_overrides/exceptions=[]` | ALLOW/MASK/REVIEW/REJECT 决策策略；引用未知规则名会启动报错 |
| `safety.audit` | `enabled=true`，`directory=data/safety-audit`，`hmac_key_env=MEMORYHUB_AUDIT_HMAC_KEY`，`retention_days=180`，`rotate_max_bytes=16MiB`，`fail_closed=true` | HMAC 哈希链审计日志 |
| `safety.quarantine` | `enabled=true`，`directory=data/review-quarantine`，`encryption_key_env=MEMORYHUB_QUARANTINE_KEY`，`retention_days=30`，`max_record_bytes=4MiB` | REVIEW 隔离区（AES-256） |
| `safety.user_rules` | `enabled`（仓库配置 false，桌面单机无外部身份源）`encryption_key_env=MEMORYHUB_USER_RULE_KEY`，`max_rules_per_user=100`，`allow_advanced_regex=false` | 用户自定义敏感/遗忘规则 |
| `safety.key_store` | `auto_generate=true`，`persist_external=true`，`strict_permissions=true` | 密钥库（见下） |

**密钥管理**：审计 HMAC、隔离区加密、用户规则加密三把密钥相互独立（各 32 字节）。首次启动若未通过环境变量提供，`SafetyKeyStore` 自动生成并保存到 `<db_path 父目录>/security/safety-keys.json`（POSIX 0700/0600）。密钥文件路径可用 `MEMORYHUB_SAFETY_KEY_FILE` 覆盖。**备份数据库时必须同时备份密钥文件**（见 [vnext/spec/VNEXT_BACKUP_RECOVERY.md](vnext/spec/VNEXT_BACKUP_RECOVERY.md)）。

## 10. 生产门禁

`runtime.mode=production` 时执行双层校验，任何一项不满足抛 `ProductionGateError`，服务拒绝启动：

1. **静态门禁** `validate_production_gate()`（配置加载后立即执行）：
   - `embedding.provider=kylin`、`vector_engine.provider=milvus`、维度 768；
   - `runtime.allow_fallback=false`；
   - `vnext.policy_required=true`、`vnext.authority_single_writer=true`、`vnext.allow_policy_bypass=false`。
2. **运行时门禁** `validate_production_runtime()`（客户端/引擎构造后）：动态库可加载、Milvus 已连接、会话可初始化。

部署前自检：`python scripts/check_kylin_embedding_runtime.py`（逐项对照 [reference/kylin-embedding-runtime-contract.md](reference/kylin-embedding-runtime-contract.md)）。

## 11. 环境变量总表

### 后端服务（`memoryhub/config.py` 读取）

| 环境变量 | 对应配置 |
|---|---|
| `MEMORYHUB_CONFIG` | YAML 配置文件路径 |
| `MEMORYHUB_RUNTIME_MODE` / `MEMORYHUB_RUNTIME_ALLOW_FALLBACK` | `runtime.*` |
| `MEMORYHUB_VNEXT_MODE` / `MEMORYHUB_VNEXT_CANARY_PERCENT` | `vnext.mode` / `vnext.canary_percent` |
| `MEMORYHUB_VNEXT_POLICY_REQUIRED` / `_AUTHORITY_SINGLE_WRITER` / `_ALLOW_POLICY_BYPASS` / `_LEGACY_READ_FALLBACK` / `_EVENTS_DEFAULT` | `vnext.*` 布尔键（接受 0/1/true/false/yes/no） |
| `MEMORYHUB_DB_PATH` / `MEMORYHUB_DEBUG` | `storage.db_path` / `debug` |
| `MEMORYHUB_EMBEDDING_PROVIDER` / `MEMORYHUB_VECTOR_ENGINE_PROVIDER` / `MEMORYHUB_VECTOR_ENGINE_APP_ID` | `embedding.provider` / `vector_engine.*` |
| `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`（别名 `MEMORYHUB_LLM_API_BASE` / `_API_KEY` / `_MODEL`） | `llm.*`（便携名优先） |
| `MEMORYHUB_SAFETY_KEY_FILE` | 密钥库文件路径覆盖 |
| `MEMORYHUB_AUDIT_HMAC_KEY` / `MEMORYHUB_QUARANTINE_KEY` / `MEMORYHUB_USER_RULE_KEY` | 三把安全密钥（可选，缺省自动生成） |

### 服务脚本

| 环境变量 | 说明 |
|---|---|
| `MEMORYHUB_PYTHON` | 服务用 Python 解释器（默认 `<repo>/.venv/bin/python`） |
| `MEMORYHUB_HOST` / `MEMORYHUB_PORT` | 监听地址/端口（默认 `127.0.0.1:8099`） |

### Agent 接入端（CLI / MCP / 插件，详见 agent-integration/README.md）

`MEMORYHUB_API_URL`、`MEMORYHUB_USER_ID`、`MEMORYHUB_TENANT_ID`、`MEMORYHUB_TOP_K`、`MEMORYHUB_MIN_CONFIDENCE`、`MEMORYHUB_SCENE`、`MEMORYHUB_TASK_TYPE`、`MEMORYHUB_PROJECT`、`MEMORYHUB_API_TIMEOUT`、`MEMORYHUB_AUTO_RECORD` 等。

### DEB 打包

`MEMORYHUB_PACKAGE_VERSION` / `MEMORYHUB_PACKAGE_REVISION`（缺省从 `pyproject.toml` 读版本、revision=1）。

## 12. 其他顶层键

| 键 | 默认 | 说明 |
|---|---|---|
| `debug` | `false` | 调试模式（仓库 `config.yaml` 开发配置为 true） |

> 注意：YAML 中的未知顶层键会被静默忽略（如历史遗留的 `host`/`port`/`log_level` 已从仓库配置移除——监听地址由 uvicorn 参数控制）。
