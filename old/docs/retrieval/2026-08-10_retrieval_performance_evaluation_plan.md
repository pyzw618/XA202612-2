# MemoryHub 检索性能与质量评测交付方案

> 文档状态：可执行方案（执行前须完成第 3 节 P0 前置任务）  
> 适用范围：比赛要求中的“知识检索召回率 ≥85%”与“知识检索响应时间 ≤500ms”  
> 最终验收环境：银河麒麟桌面操作系统 + 真实麒麟 Embedding SDK + 真实 Milvus  
> 非验收环境：Windows、非麒麟 Linux、Python Mock、`kylin_mock`、`milvus_mock`、FAISS fallback

---

## 1. 目标与结论口径

本方案用于生成一份可复现、可审计、可提交的正式检索评测报告。质量与性能必须在同一份冻结数据集、同一代码提交和同一真实麒麟环境上完成，Mock 结果只能证明测试链路可运行，不能作为比赛达标证据。

### 1.1 核心验收指标

| 指标 | 验收阈值 | 主测试口径 |
|---|---:|---|
| 知识检索 Recall@5 | ≥ 0.85 | `knowledge-only` 冻结测试集，宏平均，报告 95% CI |
| 稳态冷查询 P95 | ≤ 350ms | 模型和连接已预热，结果缓存与查询向量缓存均未命中 |
| 稳态冷查询 P99 | ≤ 500ms | 客户端 HTTP 端到端 wall-clock 延迟 |
| Embedding 错误率 | 0 | 正式计时阶段，不含预检和预热 |
| Milvus 错误率 | 0 | 正式计时阶段，不含预检和预热 |
| 超时率 | 0 | `client_e2e_ms > 500` 或明确 timeout 均计入 |
| 待同步积压 | 0 | 正式检索开始前与结束后均检查 |

### 1.2 辅助指标

- Recall@1、Recall@3、Recall@10；
- Precision@5、MRR、NDCG@5、NDCG@10；
- P50、Mean、P95、P99、Max、QPS；
- 超过 350ms 和 500ms 的请求比例；
- result cache 与 query-vector cache 命中率；
- `embedding_ms`、`hybrid_search_ms`、`lookup_ms`、`filter_ms`、`serialize_ms`；
- 按 workflow、case、template、难度、语言和 scope 分组的质量指标；
- CPU、内存、磁盘 IO 和进程资源峰值。

### 1.3 “响应时间”的正式定义

主验收值为 `client_e2e_ms`：从测试客户端发出 HTTP 请求开始，到收到并解析完整 HTTP 响应结束。服务端内部 `latency_ms` 与分段耗时只用于瓶颈定位，不能替代端到端验收值。

正式验收不得以全部查询预热后的结果缓存命中延迟代替完整检索链路延迟。

---

## 2. 评测分层

| 层级 | 环境和对象 | 目的 | 可否用于最终验收 |
|---|---|---|---|
| L0 | 指标函数、冻结数据集、评测器 | 验证 Recall/NDCG/分组统计与数据契约 | 仅质量工具验证 |
| L1 | Mock Embedding + `milvus_mock` | 验证插入、检索、缓存、错误和报告链路 | 否 |
| L2 | 真实麒麟 SDK + 真实 Milvus，直接调用 Retriever | 定位 Embedding、Milvus、回表等内部耗时 | 仅辅助 |
| L3 | 真实麒麟 SDK + 真实 Milvus + FastAPI HTTP | 最终端到端质量和性能验收 | 是 |

L1 必须先通过，L2 用于发现性能瓶颈，最终结论以 L3 为准。

---

## 3. 执行前 P0 前置任务

以下任务未完成前，不得开始正式验收。执行同学应先提交代码和测试，再冻结评测版本。

### P0-1：修正完整链路基准的缓存污染

当前 `evaluation/metrics/full_chain_benchmark.py` 会先查询全部测试语句，再重复相同语句计时，正式样本会变成结果缓存命中。

必须改为三个相互隔离的阶段：

1. `cold`：连接和模型已预热，但清空 result cache 与 query-vector cache；使用不重复查询；
2. `vector_hot`：只允许查询向量缓存命中，禁止结果缓存命中；
3. `result_hot`：允许结果缓存命中。

每个阶段必须独立清零：

- latency samples；
- metrics collector；
- embedding/Milvus/timeout/other error counters；
- result cache 和 query-vector cache；
- 正式请求序号。

主验收只读取 `cold` 阶段指标。

### P0-2：替换无效的合成 Recall ground truth

当前完整链路基准把同主题下的所有记忆都标为 relevant。在 10,000 条记忆、10 个主题时，每个查询约有 1,000 个 relevant，Recall@5 理论上限只有 0.5%。

必须改为：

- 正式质量评测读取冻结人工标注数据集；
- 每条查询包含 1～5 个直接相关目标；
- 合成主题数据只用于容量、延迟和稳定性，不参与正式 Recall 判定；
- 如需 NDCG，使用 0～3 级相关性标注，Recall 的 relevant 集合只包含等级 ≥2 的结果。

### P0-3：让真实基准覆盖 KnowledgeMemory

正式数据必须包含 workflow、case、template，不能只生成 `PreferenceMemory`。建议知识类型分布：

- workflow：40%；
- case：30%；
- template：30%。

另外注入 preference、fact、旧版本、archived、deleted 和跨用户记录作为干扰项，但这些干扰项不计入 `knowledge-only Recall@5` 的 relevant 分母。

### P0-4：扩展 RetrievalEvaluator 数据契约

评测器必须从数据集构建完整 `SearchRequest`，至少传递：

- `user_id`；
- `query`；
- `context`；
- `project_id`；
- `top_k`；
- `memory_types`；
- `min_confidence`。

报告模型必须增加明确的 `ndcg_at_k` 字段，禁止继续把 NDCG 写入名为 `accuracy` 的字段。

### P0-5：提供真实 HTTP 端到端评测入口

新增或扩展脚本，使其能够：

- 启动或连接生产配置的 FastAPI 服务；
- 通过 `/api/memory/search` 发起请求；
- 记录客户端 wall-clock 延迟和 HTTP 状态；
- 记录服务端返回的 `latency_ms`；
- 将原始逐请求记录写入 JSONL；
- 最终生成机器可读 JSON 与 Markdown 报告。

建议入口：

```text
evaluation/run_kylin_http_retrieval_evaluation.py
```

### P0-6：修正失败与样本统计

- 失败请求不得从总体结论中静默删除；
- 延迟百分位可对成功请求统计，但必须同时报告失败率和超时率；
- 预热错误不能计入正式阶段分子；
- Recall 计算阶段不得污染延迟和缓存指标；
- `total_attempts`、成功数、失败数、超时数之和必须可核对。

---

## 4. 冻结评测数据集

### 4.1 规模

正式测试集建议至少包含：

- 10,000 条已索引记忆；
- 其中至少 500 条人工整理的核心知识记忆；
- 300～500 条独立质量查询；
- 每个主要分组至少 50 条查询；
- 延迟测试至少 10,000 次有效冷查询。

500 条记忆/100 条查询可作为开发集，不建议直接作为最终验收集。

### 4.2 数据划分

| 子集 | 用途 | 是否允许用于调参 |
|---|---|---|
| `dev` | 调整检索权重、阈值、索引参数 | 是 |
| `test` | 最终验收 | 否，冻结后不得修改 |
| `latency` | 构造不重复的性能查询 | 否，正式运行前冻结 |

禁止在 test 集上反复调参后仍将其称为独立测试集。

### 4.3 查询覆盖

至少覆盖：

- workflow、case、template；
- exact、semantic、hard-negative、cross-domain；
- 中文、英文、中英混合；
- 同义改写、口语表达、错别字、缩写；
- scope、project、user 隔离；
- 新旧版本、冲突版本、archived/deleted 过滤；
- 无相关结果查询；
- 混合偏好+知识上下文查询。

### 4.4 推荐数据格式

```json
{
  "metadata": {
    "dataset_id": "memoryhub-knowledge-retrieval-v1",
    "version": "1.0.0",
    "created_at": "2026-08-10T00:00:00Z",
    "annotation_guideline_version": "1.0",
    "split": "test"
  },
  "memories": [
    {
      "id": "know_001",
      "user_id": "user_001",
      "memory_type": "knowledge",
      "knowledge_type": "workflow",
      "name": "项目周报生成流程",
      "content": "按日历、文件、项目记录整理周报",
      "steps": ["查日历", "收集文件", "整理数据", "生成 Markdown"],
      "tools": ["calendar", "file_search", "document_writer"],
      "template_body": "",
      "scope": {
        "scene": "office",
        "task_type": "office.weekly_report",
        "app": "agent"
      },
      "project_id": "project_a",
      "status": "active"
    }
  ],
  "queries": [
    {
      "query_id": "q_001",
      "user_id": "user_001",
      "query_text": "按之前的方式生成这周周报",
      "context": {
        "scene": "office",
        "task_type": "office.weekly_report",
        "app": "agent"
      },
      "project_id": "project_a",
      "memory_types": ["knowledge"],
      "difficulty": "semantic",
      "language": "zh-CN",
      "relevance": {
        "know_001": 3,
        "know_017": 1
      }
    }
  ]
}
```

定义：

- 0：不相关；
- 1：主题相关但不能直接回答/执行；
- 2：相关且可部分满足请求；
- 3：直接相关，可完整回答或执行；
- Recall relevant 集合：等级 ≥2；
- NDCG：使用完整 0～3 级标注。

### 4.5 标注流程

1. 两名标注者独立标注候选池；
2. 两人场景使用 weighted Cohen's Kappa；多名标注者可使用 Krippendorff's Alpha；
3. 分歧由第三人裁决；
4. 保存脱敏后的标注记录和准则版本；
5. 冻结 test 集并生成 SHA-256；
6. 报告标注一致性，不得只报告最终裁决结果。

---

## 5. 延迟测试设计

### 5.1 阶段定义

| 阶段 | 模型/连接 | Query vector cache | Result cache | 用途 |
|---|---|---|---|---|
| startup | 冷 | 冷 | 冷 | 单列首次启动和首请求 |
| cold | 热 | 未命中 | 未命中 | 主验收 |
| vector_hot | 热 | 命中 | 未命中 | 向量缓存收益 |
| result_hot | 热 | 任意 | 命中 | 结果缓存收益 |

不得将三个阶段的数据合并计算一个 P99。

### 5.2 负载档位

至少执行以下档位：

| 档位 | 并发 | 说明 |
|---|---:|---|
| S1 | 1 | 比赛最低基线，必须达标 |
| S2 | 4 | 轻量并发 |
| S3 | 8 | 推荐工作负载 |
| S4 | 16 | 压力观察，不强制作为比赛门槛 |

每档至少执行 10,000 个正式请求或持续 10 分钟，取较晚结束者。记录实际 QPS、错误率和资源使用率。

### 5.3 预热规则

允许预热：

- 加载 Embedding 模型；
- 建立 SDK 会话；
- 建立 Milvus 连接；
- 预加载索引元数据。

不允许在 cold 阶段预热：

- 正式测试查询的结果缓存；
- 正式测试查询的向量缓存。

预热查询必须来自独立集合，不能与正式性能查询完全相同。

### 5.4 统计方法

- 使用单调时钟记录 wall-clock；
- 输出原始毫秒值，不只输出四舍五入结果；
- P50/P95/P99 使用统一百分位算法；
- 对 P95/P99 和 Recall@5 给出 bootstrap 95% CI；
- 至少完成 3 次独立正式运行；
- 主报告同时给出各轮结果和合并结果，不得只选最好的一轮。

---

## 6. 环境与版本记录

正式报告必须包含：

- 机器厂商与型号；
- CPU 型号、核心数、频率；
- 内存容量；
- 磁盘类型；
- 银河麒麟版本与内核版本；
- 电源/性能模式；
- Python 和依赖版本；
- 麒麟 Embedding SDK 路径、版本或文件 SHA-256；
- Embedding 模型名和实际向量维度；
- Vector Engine C API 路径、版本或文件 SHA-256；
- Milvus 版本、部署模式、索引类型和索引参数；
- MemoryHub Git commit；
- 工作区是否干净；
- 数据集 ID、版本、split 和 SHA-256；
- 测试命令、并发、缓存阶段和随机种子；
- 测试开始/结束时间。

环境预检：

```bash
python scripts/verify_kylin_environment.py
```

预检必须确认：

- `libkylin-coreai-embedding.so` 可加载；
- `libkysdk-vector-engine-client-capi.so` 可加载；
- Embedding 会话可初始化且输出 768 维；
- Milvus 可连接；
- `MEMORYHUB_VECTOR_ENGINE_APP_ID` 非空；
- production 配置禁止 Mock 和 fallback；
- 待同步积压为 0。

---

## 7. 执行流程

### 阶段 A：代码和数据准备

1. 完成第 3 节所有 P0 任务；
2. 为评测器、缓存分组、统计清零和数据加载增加自动测试；
3. 建立 dev/test/latency 数据集；
4. 完成人工标注、裁决和一致性统计；
5. 冻结 Git commit 与数据集 SHA-256；
6. 记录工作区状态。

完成条件：

- 所有正式命令的 `--help` 与本文一致；
- 数据集 schema 校验通过；
- 不存在空 relevant 集被默认为满分的情况；
- 评测报告不再把 NDCG 命名为 accuracy。

### 阶段 B：Mock 链路验证

示例命令以脚本实际 `--help` 为准：

```bash
python evaluation/run_milvus_mock_benchmark.py \
  --memory_count 1000 \
  --query_count 100 \
  --iterations 3 \
  --top_k 5 \
  --output evaluation/results/mock_retrieval_benchmark.json
```

Mock 阶段只检查：

- 插入、查询和报告链路可运行；
- 指标字段齐全；
- 三种缓存阶段确实隔离；
- 请求数、成功数、失败数可核对；
- JSON、JSONL 和 Markdown 均可生成。

Mock 的 Recall 和延迟值不得写入最终达标结论。

### 阶段 C：真实麒麟内部链路诊断

```bash
export MEMORYHUB_VECTOR_ENGINE_APP_ID="<deployment-app-id>"

python evaluation/run_milvus_kylin_benchmark.py \
  --memory_count 10000 \
  --query_count 500 \
  --iterations 3 \
  --top_k 5 \
  --so_path /usr/lib/libkysdk-vector-engine-client-capi.so \
  --embedding_so_path /usr/lib/libkylin-coreai-embedding.so \
  --app_id "$MEMORYHUB_VECTOR_ENGINE_APP_ID" \
  --target_p95_ms 350 \
  --target_p99_ms 500 \
  --output evaluation/results/kylin_internal_benchmark.json
```

注意：当前脚本完成 P0 修改后方可用于 cold/vector_hot/result_hot 分组。修改前跑出的 P99 不能作为正式结论。

### 阶段 D：真实麒麟 HTTP 端到端验收

目标命令如下，具体参数应在 P0-5 实现后以 `--help` 固化：

```bash
python evaluation/run_kylin_http_retrieval_evaluation.py \
  --base-url http://127.0.0.1:8099 \
  --dataset evaluation/datasets/memoryhub_knowledge_retrieval_v1_test.json \
  --latency-dataset evaluation/datasets/memoryhub_retrieval_latency_v1.json \
  --phase cold \
  --concurrency 1,4,8,16 \
  --min-requests 10000 \
  --min-duration-seconds 600 \
  --runs 3 \
  --top-k 5 \
  --output-dir evaluation/results/kylin_http_v1
```

随后分别执行 `vector_hot` 和 `result_hot`，但只有 `cold` 参与 ≤500ms 主验收。

### 阶段 E：核对与签署

1. 校验数据集和环境 SHA-256；
2. 校验每轮请求数、成功数、失败数、超时数；
3. 检查 cold 阶段缓存命中率应为 0；
4. 检查 knowledge-only Recall@5；
5. 检查并发 1 的 cold P99；
6. 检查并发 4/8/16 的退化情况；
7. 检查错误率与 pending backlog；
8. 两名执行者复核命令、环境和结论；
9. 生成并提交脱敏后的最终 Markdown 报告。

---

## 8. 报告结构

### 8.1 机器可读汇总

```json
{
  "run": {
    "git_commit": "...",
    "dataset_id": "memoryhub-knowledge-retrieval-v1",
    "dataset_sha256": "...",
    "environment_sha256": "...",
    "started_at": "...",
    "finished_at": "..."
  },
  "quality": {
    "knowledge_only": {
      "query_count": 500,
      "recall_at_5": 0.0,
      "recall_at_5_ci95": [0.0, 0.0],
      "precision_at_5": 0.0,
      "mrr": 0.0,
      "ndcg_at_10": 0.0
    },
    "by_knowledge_type": {},
    "by_difficulty": {},
    "by_language": {}
  },
  "performance": {
    "cold": {
      "concurrency_1": {
        "count": 10000,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "p99_ms": 0.0,
        "max_ms": 0.0,
        "over_500ms_rate": 0.0,
        "qps": 0.0
      }
    },
    "vector_hot": {},
    "result_hot": {}
  },
  "errors": {
    "embedding": 0,
    "milvus": 0,
    "timeout": 0,
    "http": 0,
    "other": 0
  },
  "cache": {
    "cold_result_cache_hit_rate": 0.0,
    "cold_vector_cache_hit_rate": 0.0
  },
  "pending_backlog_before": 0,
  "pending_backlog_after": 0,
  "verdict": {
    "recall_pass": false,
    "p95_pass": false,
    "p99_pass": false,
    "errors_pass": false,
    "overall_pass": false
  }
}
```

### 8.2 Markdown 正式报告

正式报告必须包含：

1. 一页结论摘要；
2. 验收标准与最终 PASS/FAIL；
3. 环境和版本；
4. 数据集与标注方法；
5. 质量指标及 95% CI；
6. cold/vector_hot/result_hot 分组性能；
7. 并发退化曲线；
8. 分段耗时；
9. 错误、超时和积压；
10. 失败查询样例与误召回分析；
11. 原始产物路径和 SHA-256；
12. 已知限制与复核人。

---

## 9. 产物与提交规则

原始结果可继续存放在被 Git 忽略的 `evaluation/results/`，但正式交付不能只依赖该目录。

### 必须提交到仓库

- `docs/evaluation/retrieval_evaluation_report.md`：脱敏后的正式报告；
- `docs/evaluation/retrieval_environment_manifest.json`：环境清单；
- `docs/evaluation/retrieval_artifact_checksums.txt`：数据集和原始产物 SHA-256；
- 数据集 schema、标注规范和可公开的冻结数据集；
- 生成报告所需脚本和测试。

### 可作为外部附件

- 原始逐请求 JSONL；
- 大体积资源监控文件；
- 完整服务日志；
- 含机器部署细节但不适合公开提交的内部环境附件。

所有交付物必须脱敏，不得包含 API Key、应用凭证、用户原文、真实账号或生产地址。

---

## 10. 最终 PASS/FAIL 规则

只有同时满足以下条件才能判定检索验收通过：

- 冻结 test 集的 knowledge-only Recall@5 ≥0.85；
- 并发 1、cold 阶段 HTTP 端到端 P95≤350ms；
- 并发 1、cold 阶段 HTTP 端到端 P99≤500ms；
- Embedding、Milvus、HTTP、timeout 错误均为0；
- 测试前后 pending backlog 均为0；
- 使用真实麒麟 SDK、真实 Milvus、production配置且没有 fallback；
- 数据集、环境、命令、Git commit和原始结果均可复核；
- 至少3次独立运行没有只挑选最佳结果。

并发 4/8/16 的结果用于展示容量和退化趋势；如果比赛另有并发要求，则将对应档位提升为硬门槛。

以下任一情况必须判定“证据不足”，不得写“达标”：

- 仅有 Mock/FAISS结果；
- 只报告 P95，不报告 P99；
- 只报告服务内部耗时，不报告 HTTP 端到端耗时；
- 正式延迟样本被结果缓存命中污染；
- Recall 来自主题合成 ground truth；
- 测试集在调参后未重新冻结；
- 报告缺少环境、commit或数据集校验值；
- 失败请求被排除且未报告错误率。

---

## 11. 执行分工建议

| 角色 | 工作 | 交付 |
|---|---|---|
| 评测开发 | 完成第3节 P0脚本与自动测试 | 可复现评测入口、测试记录 |
| 数据标注 | 构建并冻结 dev/test/latency 数据集 | 数据集、规范、一致性报告、SHA-256 |
| 麒麟环境 | 准备真实SDK、Milvus和生产配置 | 环境清单、预检结果 |
| 性能执行 | 执行3轮、多缓存阶段、多并发测试 | JSON、JSONL、资源监控、日志 |
| 质量复核 | 检查 Recall、失败查询和统计口径 | 复核记录 |
| 报告负责人 | 汇总脱敏正式报告 | Markdown报告、校验清单 |

---

## 12. 执行 Checklist

### 代码与数据

- [ ] 完成 P0-1～P0-6；
- [ ] 自动测试通过；
- [ ] `--help` 与本文命令一致；
- [ ] dev/test/latency 数据集已拆分；
- [ ] test 集已冻结并计算 SHA-256；
- [ ] 标注一致性和裁决记录完整。

### Mock 验证

- [ ] Mock 完整链路可运行；
- [ ] cold/vector_hot/result_hot 指标隔离；
- [ ] 请求、错误和缓存统计可核对；
- [ ] JSON、JSONL、Markdown产物齐全。

### 真实麒麟验收

- [ ] 环境预检全部通过；
- [ ] production模式无 Mock、FAISS或fallback；
- [ ] 真实 SDK 输出768维；
- [ ] Milvus连接及索引状态正常；
- [ ] 测试前 pending backlog=0；
- [ ] 3轮 cold 测试完成；
- [ ] vector_hot/result_hot对照完成；
- [ ] 并发1/4/8/16完成；
- [ ] 测试后 pending backlog=0。

### 报告

- [ ] Recall@5及95% CI已报告；
- [ ] HTTP端到端P95/P99已报告；
- [ ] 错误率、超时率和>500ms比例已报告；
- [ ] 环境、commit、数据集和命令完整；
- [ ] 原始产物SHA-256完整；
- [ ] 报告已脱敏；
- [ ] 两名复核人完成签字或确认。
