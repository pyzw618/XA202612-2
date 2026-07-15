# Kylin-MemoryHub 配置说明

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

YAML 配置优先级高于环境变量。

---

## 配置项详解

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

- **麒麟 SDK**（生产推荐）
  ```yaml
  embedding:
    provider: "kylin"
    dimension: 1024
    model_name: "kylin-embedding-v1"
  ```

- **Mock**（开发测试）
  ```yaml
  embedding:
    provider: "mock"
    dimension: 1024
  ```

### 检索配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `RETRIEVAL_TOP_K` | `retrieval.default_top_k` | `5` | 返回结果数 |
| `VECTOR_WEIGHT` | `retrieval.vector_weight` | `0.6` | 向量检索权重 |
| `KEYWORD_WEIGHT` | `retrieval.keyword_weight` | `0.3` | BM25 权重 |
| `METADATA_WEIGHT` | `retrieval.metadata_weight` | `0.1` | 元数据权重 |

**权重调整建议：**

- 语义搜索为主：`vector_weight: 0.8`
- 精确匹配为主：`keyword_weight: 0.6`
- 均衡模式：默认值

### 存储配置

| 环境变量 | YAML 路径 | 默认值 | 说明 |
|---------|----------|-------|------|
| `DB_PATH` | `storage.db_path` | `data/memoryhub.db` | SQLite 路径 |
| `VECTOR_INDEX_PATH` | `storage.vector_index_path` | `data/vector_index` | FAISS 索引路径 |
| `EVIDENCE_PATH` | `storage.evidence_path` | `data/evidence` | 证据链路径 |

### 安全配置

```yaml
safety:
  # 敏感信息正则规则
  sensitive_patterns:
    - '(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+'
    - '\b\d{18}\b'
    - '\b1[3-9]\d{9}\b'
  
  # 自动脱敏（将敏感信息替换为 ***）
  auto_mask: true
  
  # 检测到敏感信息时拒绝入库
  reject_on_detect: false
```

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

### 场景 2：生产环境（OpenAI）

```yaml
llm:
  provider: "openai"
  api_base: "https://api.openai.com/v1"
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4o-mini"

embedding:
  provider: "kylin"
  model_name: "kylin-embedding-v1"

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
