# Kylin-MemoryHub 配置说明

> `load_config()` 支持本文列出的主要 YAML 配置及运行时环境变量覆盖。安全密钥值
> 不写入 YAML：单机部署默认由 MemoryHub 首次启动自动生成并持久化，外部环境变量
> 仍具有最高优先级。

## 快速开始

### 1. 环境变量配置（推荐）

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入实际配置。

### 2. YAML 配置文件（高级）

复制 `config.example.yaml` 为 `config.yaml`：

```bash
cp config.example.yaml config.yaml
```

环境变量优先级高于 YAML 配置。

---

## 配置项详解

### 服务监听配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| — | `host` | `0.0.0.0` | 服务监听地址（`127.0.0.1` 仅本机） |
| — | `port` | `8099` | 服务监听端口（当前仓库所有集成/客户端默认端口） |

```yaml
host: "0.0.0.0"
port: 8099
```

FastAPI 接口文档：`http://<host>:8099/docs`。启动方式：
`python -m uvicorn memoryhub.app:app --host <host> --port <port>`，
或使用 `scripts/start-memoryhub-service.ps1`（Windows）/ `.sh`（Linux）。

### 运行模式配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `MEMORYHUB_RUNTIME_MODE` | `runtime.mode` | `development` | 运行模式：`production` / `development` / `test` |
| `MEMORYHUB_RUNTIME_ALLOW_FALLBACK` | `runtime.allow_fallback` | `true`（dev/test）/ `false`（production） | 是否允许 FAISS 等降级后端 |

`production` 模式下禁止 `mock`、`kylin_mock`、`faiss`、`milvus_mock` 和静默降级；
`development` / `test` 模式可在明确记录告警后启用 `allow_fallback`。

### LLM 配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `LLM_PROVIDER` | `llm.provider` | `openai` | LLM 提供商 |
| `LLM_API_BASE` | `llm.api_base` | `http://localhost:11434/v1` | API 地址 |
| `LLM_API_KEY` | `llm.api_key` | - | API 密钥 |
| `LLM_MODEL` | `llm.model` | `qwen2:1.5b` | 模型名称 |

**支持的 LLM 后端：**

- **Ollama**（本地推理）
  ```yaml
  llm:
    provider: "ollama"
    api_base: "http://localhost:11434/v1"
    model: "qwen2:7b"
  ```

- **OpenAI 兼容 API**
  ```yaml
  llm:
    provider: "openai"
    api_base: "https://api.openai.com/v1"
    api_key: "sk-..."
    model: "gpt-4o-mini"
  ```

### Embedding 配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `EMBEDDING_PROVIDER` | `embedding.provider` | `mock` | Embedding 提供商 |
| `EMBEDDING_DIMENSION` | `embedding.dimension` | `1024` | 向量维度 |

**支持的 Embedding 后端：**

- **麒麟 SDK**（生产唯一允许）
  ```yaml
  embedding:
    provider: "kylin"
    dimension: 768
    model_name: "ensemble-embd_gte-base_uint8-text"
  ```

- **Mock / kylin_mock**（开发测试或诊断场景）
  ```yaml
  embedding:
    provider: "mock"
    dimension: 768
  ```

生产模式（`runtime.mode=production`）下禁止 `mock`、`kylin_mock` 和 `auto`。

### 检索配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `RETRIEVAL_TOP_K` | `retrieval.default_top_k` | `5` | 返回结果数 |
| `VECTOR_WEIGHT` | `retrieval.vector_weight` | `0.6` | 向量检索权重（仅 HybridRetriever fallback 使用） |
| `KEYWORD_WEIGHT` | `retrieval.keyword_weight` | `0.3` | BM25 权重（仅 HybridRetriever fallback 使用） |
| `METADATA_WEIGHT` | `retrieval.metadata_weight` | `0.1` | 元数据权重（仅 HybridRetriever fallback 使用） |

**权重调整建议：**

- 语义搜索为主：`vector_weight: 0.8`
- 精确匹配为主：`keyword_weight: 0.6`
- 均衡模式：默认值

### 存储配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `DB_PATH` | `storage.db_path` | `data/memoryhub.db` | SQLite 路径（端侧唯一事实源） |
| `VECTOR_INDEX_PATH` | `storage.vector_index_path` | `data/vector_index` | FAISS 索引路径（仅 development/test 使用） |
| `EVIDENCE_PATH` | `storage.evidence_path` | `data/evidence` | 证据链路径 |

### 向量引擎配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `MEMORYHUB_VECTOR_ENGINE_APP_ID` | `vector_engine.app_id` | - | Milvus/Milvus mock 必填的非空 SDK 应用标识 |

`vector_engine.provider=milvus` 或 `milvus_mock` 时必须提供 `app_id`；该值由测试/部署平台提供，
不是 collection 名或 user ID，也不应写入日志。`faiss` 不消费此字段。

### 安全配置

```yaml
safety:
  rule_set_id: "kylin-memoryhub.safety"
  rule_set_version: "1.0"

  policy:
    policy_id: "default"
    version: "1.0"
    rule_overrides: []
    level_overrides: []
    exceptions: []
    fallback_action: "review"
    on_scan_error: "review"
    on_unmaskable: "review"
    auto_sanitize: true
    fail_closed: true

  # 以下两个字段只为 v0.1 调用方迁移保留
  auto_mask: true
  reject_on_detect: false

  # 端侧密钥存储；空 path 自动放在数据库父目录的 security/ 下
  key_store:
    path: ""
    auto_generate: true
    persist_external: true
    import_legacy_env: true
    legacy_env_file: "~/.config/memoryhub/safety.env"
    strict_permissions: true

  # 安全处置审计；密钥值不会出现在 YAML 中
  audit:
    enabled: true
    directory: "data/safety-audit"
    hmac_key_env: "MEMORYHUB_AUDIT_HMAC_KEY"
    key_id: "device-local-v1"
    rotate_max_bytes: 16777216
    retention_days: 180
    max_record_bytes: 65536
    lock_timeout_seconds: 5.0
    strict_permissions: true
    fsync: true
    fail_closed: true

  # REVIEW 原事件隔离；仅保存 AES-256-GCM 密文
  quarantine:
    enabled: true
    directory: "data/review-quarantine"
    encryption_key_env: "MEMORYHUB_QUARANTINE_KEY"
    key_id: "device-local-v1"
    retention_days: 30
    max_record_bytes: 4194304
    strict_permissions: true
    fsync: true
    fail_closed: true

  # 用户自定义敏感规则；matcher 只以 AES-256-GCM 密文持久化
  user_rules:
    enabled: true
    encryption_key_env: "MEMORYHUB_USER_RULE_KEY"
    key_id: "device-local-v1"
    max_rules_per_user: 100
    max_matcher_chars: 2048
    allow_advanced_regex: false
    detector_cache_size: 256

  # 递归扫描资源预算
  max_depth: 32
  max_field_chars: 65536
  max_scan_bytes: 2097152
  max_scanned_fields: 10000
  max_candidates: 2048
  max_findings: 1024
  max_path_chars: 4096
```

未提供 `sensitive_patterns` 时，`SafetyConfig` 会通过包内
`catalog.json` 精确加载 `rule_set_id@rule_set_version`；版本不存在、摘要不符、
规则或溯源无效时直接失败，不会静默回退。内置 JSON 会随 wheel 一起打包，
加载不依赖当前工作目录。

声明式 `RuleDefinition` 至少包含 `rule_id`、`category`、`risk_level`、
`default_action`、`pattern`、版本化 `validator` / `masker`、`target_paths`、
`priority`、结构化 `standard_ref`、`rule_version` 和 `enabled`。其中：

- `credential | personal | sensitive_personal` 是彼此独立的分类；
- `risk_level` 只描述风险，不能直接推出动作；
- `redact_allow` 编译为现有 `SafetyAction.MASK`，只有脱敏并复检成功后才能继续；
- `target_paths` 是锚定的 RFC 6901 模板，`*` 匹配一段、`**` 匹配多段；
- 规则模板用 `~2` 精确表示字面星号键；实际 Finding 路径仍是严格 RFC 6901；
- validator/masker 只能引用固定白名单中的版本化 ID，不支持动态 import/eval；
- `redact_allow` 只能使用固定的 `[REDACTED...]` replacement，且 masker 注册项必须
  显式声明 `full_redaction` capability 并通过加载时契约探针；
- 法律、国标、RFC、安全指南和项目策略通过 `standard_ref` 分别注明用途。

旧 `sensitive_patterns` 字段仍接受结构化 `SensitiveRule` 作为迁移入口，但它会
绕过来源目录和组件引用，不应复制内置规则形成第二份事实源。匿名 `list[str]`
不再有效；仅 `SensitiveDetector(custom_patterns={...})` 暂时保留
`dict[str, str]` 迁移入口，未知旧规则默认进入 `REVIEW`。
启用的结构化规则本身不得配置 `ALLOW`；有命中的放行只能来自下述受治理例外。

兼容开关只允许收紧策略：`reject_on_detect: true` 强制所有命中拒绝，
`false` 不会降级规则自身的 `REJECT`；`auto_mask: false` 或
`policy.auto_sanitize: false` 会把原本的 `MASK` 提升为 `REVIEW`，不会放行
未脱敏事件。完整默认规则与溯源见
`memoryhub/safety_rules/data/builtin-1.0.json`（规则集清单见
`memoryhub/safety_rules/data/catalog.json`）。

普通 `rule_overrides` / `level_overrides` 不能使用 `ALLOW`，且有效动作始终取
覆盖值与规则建议中更严格的一项，因此 `REJECT`/`REVIEW` 基线不能被普通覆盖降级。
需要按场景和用途
放行低风险上下文标识时，必须配置有限期例外，例如：

```yaml
policy:
  exceptions:
    - exception_id: "network-diagnostics-ip"
      version: "1.0"
      scope:
        rule_names: ["ip_address"]
        scenes: ["network"]
        task_types: ["network_diagnostics"]
        field_paths: []
      reason: "受控网络诊断需要保留目标地址"
      owner: "security-team"
      valid_from: "2026-07-24T00:00:00Z"
      expires_at: "2026-12-31T23:59:59Z"
      rule_set_digest: ""  # 生产配置建议绑定当前规则集摘要
      action: "allow"
      enabled: true
```

`rule_names` 必填，且来源类型、事件类型、场景、任务用途或字段路径至少限制一项；
各维度之间按 AND 匹配；有效窗口按 `SafetyDecision.decided_at` 判断为
`[valid_from, expires_at)`，而不是使用扫描时刻。扫描时尚未过期不会锁定放行
资格，决策时已到 `expires_at` 就不生效。例外必须包含原因、负责人、版本和带时区
的过期时间；版本、原因、负责人及字符串作用域在去除首尾空白后必须非空。当前只允许低风险
上下文标识使用 `ALLOW`；凭据、个人身份
与敏感个人信息仍分别保持 `REJECT`、`MASK` 或 `REVIEW` 安全下限。

扫描预算都必须是正整数；`max_depth` 另有 `64` 的安全硬上限。深度、单字段、
总 UTF-8 字节、字段/节点或 JSON
Pointer 在建立可信事件快照前超限时，`scan()` 直接抛出只含稳定代码的
`SafetyScanError`；此时没有可安全绑定的 `event_digest`，不能伪造不完整报告。
可信快照建立后，候选数、最终 Finding 数或 validator 运行异常会保留已确认命中，
同时返回 `scan_complete: false` 和不含原文的稳定 issue code。生产
`process()` 会按 `policy.on_scan_error` 失败关闭，且不会把不完整扫描的事件
暴露给普通持久化链。

默认情况下，MemoryHub 会生成三把独立的 32 字节密钥，并保存为
`<storage.db_path 父目录>/security/safety-keys.json`。目录和文件在 POSIX/麒麟上
分别使用 `0700` 和 `0600`，密钥值不会写入仓库、YAML、命令行或普通日志：

- `MEMORYHUB_AUDIT_HMAC_KEY` 用于输入 HMAC 指纹、持久审计记录认证和跨轮转链；
- `MEMORYHUB_QUARANTINE_KEY` 是 REVIEW 隔离区的 32 字节 AES-256-GCM 密钥；
- `MEMORYHUB_USER_RULE_KEY` 是用户规则 matcher 的 32 字节主密钥。实现会通过
  HKDF 派生独立的加密与 HMAC 指纹子密钥；它仍不得与前两项复用；
- 上述环境变量均为可选覆盖。`persist_external: true`（默认）会在首次启动时把
  有效外部密钥导入本地私有文件，之后不再要求启动脚本重复注入；受管部署可同时
  设置 `auto_generate: false` 和 `persist_external: false`，只使用外部密钥；
- `MEMORYHUB_SAFETY_KEY_FILE` 可覆盖密钥文件位置，且必须使用绝对路径；
- `audit.directory` 与 `quarantine.directory` 使用相对路径时，以
  `storage.db_path` 的父目录为基准解析，不再依赖服务启动时的工作目录；
- 升级旧版单机部署时，会以纯文本键值格式安全读取权限为 `0600` 的
  `~/.config/memoryhub/safety.env` 并导入一次；不会执行其中的 shell 内容；
- 备份 MemoryHub 数据时必须同时备份 `security/safety-keys.json`。已有审计链、
  REVIEW 隔离记录或用户规则密文存在而对应密钥丢失时，服务拒绝启动写入链，
  不会生成新密钥覆盖历史；
- 生产环境保持 `strict_permissions: true`、`fsync: true` 和
  `fail_closed: true`；审计写入或隔离写入失败时不得继续普通存储/Embedding；
- 审计目录与隔离目录在银河麒麟上分别使用 `0700`，记录、锁和状态文件使用
  `0600`，并拒绝路径层级中的符号链接；目录还必须位于服务账户控制的可信父目录；
- `retention_days` 只删除已关闭的审计分段或到期隔离项；审计保留清理会留下
  带认证的链锚点，不能把删除后的后缀验证表述为完整历史验证；
- 系统定时任务必须调用 `SafetyAuditLog.enforce_retention()` 和
  `ReviewQuarantineStore.cleanup_expired()`；没有进程运行时，期限配置不能自行删除
  磁盘文件。即使尚未清理，到期 REVIEW 记录也会拒绝读取。

装配时使用同一个强类型 `SafetyConfig` 和同一个 `SensitiveDetector`：
`SafetyWriteGate.from_config(detector, config, audit_hmac_key=..., quarantine_key=...)`。
两个 key 参数由应用启动层从端侧密钥存储或环境变量解析，代码不会从 YAML 读取密钥值。
`from_config()` 会在创建任何目录前拒绝两个 key 使用相同材料。
启用用户规则时改用
`SafetyWriteGate.from_user_rule_config(service, config, audit_hmac_key=..., quarantine_key=...)`，
它会额外拒绝用户规则主密钥与前两者复用。
`strict_permissions`、`fsync` 和 `fail_closed` 是不可关闭的安全下限；配置为
`false` 会在启动时拒绝。

启用前端用户规则管理接口时，`MEMORYHUB_USER_RULE_KEY` 应保存 32 字节随机值的
Base64 编码。服务启动阶段解码并校验长度；缺失或无效时，规则管理接口返回稳定
`503`，写入链的用户规则 provider 失败关闭，不能退化为“没有自定义规则”。matcher
不会由 GET/list 接口回显，数据库中只保存密文和带密钥指纹。`advanced_regex`
默认关闭；启用后还会经过保守的正则回溯风险门禁，但 Python `re` 没有单次硬超时，
因此只应对受信任的本地管理端开放；普通用户优先使用 `literal`。

该密钥必须独立于审计 HMAC key 和 REVIEW 隔离 key；默认由同一端侧私有密钥文件
管理，也可由设备凭据设施注入，不能提交到 `.env`、YAML 或版本库。当前
`create_app()` 默认把规则表建在
`storage.db_path`；只有配置、密钥和 `user_rule_identity_resolver` 都有效且应用进入
startup 时才初始化，不会在模块 import 阶段创建数据库。resolver 必须从认证会话
返回用户 ID，不能把客户端 header 原样当作认证结果。

---

## 配置优先级

```
环境变量 > config.yaml > 默认值
```

1. 环境变量（最高优先级）
2. `config.yaml` 文件
3. 代码中的默认值

---

## 常见配置场景

### 场景 1：本地开发（Ollama）

```yaml
llm:
  provider: "ollama"
  api_base: "http://localhost:11434/v1"
  model: "qwen2:1.5b"

embedding:
  provider: "mock"

debug: true
```

### 场景 2：生产环境（OpenAI + 麒麟 SDK）

```yaml
runtime:
  mode: production
  allow_fallback: false

llm:
  provider: "openai"
  api_base: "https://api.openai.com/v1"
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4o-mini"

embedding:
  provider: "kylin"
  dimension: 768
  model_name: "ensemble-embd_gte-base_uint8-text"

vector_engine:
  provider: "milvus"
  app_id: "<provided-by-deployment-platform>"
  dimension: 768

debug: false
```

### 场景 3：高性能检索

```yaml
retrieval:
  default_top_k: 10
  vector_weight: 0.7
  keyword_weight: 0.2
  metadata_weight: 0.1
  rerank_enabled: true
  cache_ttl_seconds: 600
