# 知识检索召回率：实测根因与优化路径

> 环境：银河麒麟 V11，`embedding=kylin/768`（`ensemble-embd_gte-base_uint8-text`），
> `vector_engine=milvus`，`runtime_mode=production`，检索链路 `MilvusHybridRetriever`。
> 数据集：`evaluation/datasets/memoryhub_graded_retrieval_v2.1_dev.json`（600 记忆 / 120 查询）。
> 全部数字为 HTTP 端到端实测，每次响应均校验 `served=vnext`。

## 1. 结果

| 配置 | scoped Recall@5 | MRR | NDCG@5 |
|---|---:|---:|---:|
| 初始（旧语料 + C 侧等权融合） | 0.6042 | 0.3921 | — |
| 语料修正后（C 侧等权融合） | 0.6458 | 0.4872 | — |
| Python 侧加权融合 0.6/0.3 | 0.6458 | 0.4611 | 0.6911 |
| Python 侧加权融合 0.3/0.7 | 0.6667 | 0.4567 | 0.7238 |
| **纯稠密通道（`vector_weight=1.0`）** | **0.7292** | 0.4750 | 0.7099 |
| 纯词面通道（`keyword_weight=1.0`） | 0.6667 | 0.4479 | 0.7167 |

目标 ≥0.85，**当前最好 0.7292，未达标**。

## 2. 已验证的结论

**(a) 语料模板化会显著压低召回（已修）。** 旧语料 600 条记忆共用固定句式
（如每条 workflow 都带"适用于{label}场景，执行时需遵循{label}相关规范"），
embedding 无法区分，且干扰项的措辞比正例更贴合查询（正例一度排名垫底）。
重做语料（措辞随记录变化、干扰项不复述主题词）后召回 0.6042 → 0.6458。

**(b) C 侧 RRF 等权融合会损耗信号。** `vector_engine_hybrid_search(...)` 的
稠密/稀疏权重写死在 C 侧，且 C API 不接受权重参数。已实现 Python 侧
`MilvusHybridRetriever._weighted_fuse`，按 `retrieval.vector_weight` /
`retrieval.keyword_weight` 加权融合，绕开该限制。

**(c) 启发式重排器有害（已回滚）。** 接线现役 `Reranker` 后召回由 0.6458
降到 0.5625：其"相关性"是词面 Jaccard，而干扰项名字里就含主题词，token
重叠常高于正例，放大的正是错误信号。顺带修复了它一个真实缺陷——相关性打分
原用空格分词，中文整条查询只得 1 个 token，对中文完全失效。

**(d) 候选窗口不是瓶颈。** `candidate_multiplier` 由 4 提到 60
（`fetch_k` 100 → 300）后召回不变。

**(e) 单通道优于融合。** 无论 0.6/0.3、0.3/0.7 还是 0.5/0.5，融合结果
（0.6458–0.6667）都低于**任一单通道的最好值**（稠密 0.7292）。这是 RRF 的
典型失效模式：两路信号强度相当且都不高时，融合劣于最强单路。

## 3. 尚未验证的路径

| 路径 | 预期收益 | 代价 |
|---|---|---|
| 语义重排器（LLM / cross-encoder） | 高（直击排序质量） | LLM 调用 +1~2s，**与 ≤500ms 的延迟指标互斥**；cross-encoder 需引入模型 |
| 向量引擎支持标量下推 | 中 | 需 C/SDK 侧改动，超出本仓范围 |
| 更换中文优化 embedding | 中高 | 模型由麒麟 SDK 提供，非本项目可选 |
| 降低语料干扰项密度 | 中 | 属数据集调参，7 个近似重复项/任务偏高于真实分布，但改动需与评测口径一并说明 |

## 4. 最终解法：修好生产路径上真正生效的那个重排器

上面的路径表**全部没有命中真因**。真正的问题是调用链认知错误：请求由 vNext
`RetrievalService` 服务（`served=vnext`），其通道为
`vector`（包 `MilvusHybridRetriever`）/ `keyword` / `metadata` / `working` /
`episode` / `authority`，融合后再由 **`VNextReranker` 做最终重排**。

而 `VNextReranker._compute_relevance` 用的是 `query.lower().split()` ——
**按空格分词**。中文没有空格，查询与候选都只得 1 个 token，结果非 0 即 1。
占权重的 0.20 的"相关性"因此对中文恒为常量，最终排序完全由被 RRF 压平的
融合分数决定，**重排形同虚设**。

修复方式：`VNextReranker` 改用 jieba 分词（复用 `keyword_search._tokenize`），
并把相关性从 Jaccard 改为**覆盖率**（`|q∩d|/|q|`）——Jaccard 按并集归一化会
惩罚带 steps/template 的知识记忆，实测接线会掉分。

| | 修复前 | 修复后 |
|---|---:|---:|
| scoped Recall@5 | 0.7292 | **0.9167** |
| exact / paraphrase / cross_scope | 0.667 / 0.667 / 1.00 | **1.00 / 1.00 / 1.00** |
| semantic | 0.583 | 0.667 |
| 延迟 cold_c1 P95 | 81.89ms | 75.27ms |

延迟无变化（重排只做词面比较，约百次分词）。

## 5. 遗留

`semantic` 档（0.667）仍是短板：查询与目标**无词面交集**时覆盖率全为 0，
只能退回稠密通道。这是词面重排的固有边界，进一步改善需要语义重排器，
其代价（+1~2s）与 ≤500ms 的延迟指标互斥，属产品取舍。

## 6. 方法论教训

本轮五次判断被实测推翻（认为稠密是噪声、认为候选窗口是瓶颈、两次语料修正、
一次重排器接线），根因是**对调用链的假设未经核实**——改了 `MilvusHybridRetriever`
却不知它只是 vNext 的一个通道，最终排序其实发生在 `VNextReranker`。
先确认"哪段代码真正决定结果"，再动手。
