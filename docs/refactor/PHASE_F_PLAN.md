# Phase F 规划：评测闭环（偏好/冲突评测器 + 数据集 + API）

> 状态：**已规划，暂缓实施**（2026-08-18 决策：先跳过 F，记录规划供后续拾起）
> 依据：`docs/refactor/REFACTOR_PLAN_V2.md` §4.7（量化评测机制，赛题要求 7）
> 关联：`evaluation/metrics/preference_eval.py`、`conflict_eval.py`（当前均为 `NotImplementedError` 空壳）

## 背景与目标

评分表 4 项硬指标中：

| 指标 | 现状 | 目标 |
|---|---|---|
| 检索延迟 ≤500ms | ✅ 已达标（P99≈152ms，FAISS+ollama 环境） | 真实麒麟+Milvus 复验 |
| 知识检索召回 ≥85% | ⚠️ 有基线 R@5=0.555（`evaluation/results/`） | 0.85（需真实模型，见"后续"） |
| 偏好提取准确率 ≥85% | ❌ **评测器空壳**（`preference_eval.py` NotImplementedError） | ≥0.85 |
| 冲突处理正确率 ≥88% | ❌ **评测器空壳**（`conflict_eval.py` NotImplementedError） | ≥0.88 |

Phase F 目标：**填实两个空壳评测器 + 黄金数据集 + API 接入**，让"偏好准确率/冲突正确率"有可测基线与闭环。检索召回攻坚（embedding 升级等）需真实环境，另行排期。

## 规划内容

### F1 偏好评测器（`evaluation/metrics/preference_eval.py` 填实）
- `PreferenceEvaluator`：
  - `evaluate_single(sample)`：`input_text`+`scene` 构造成 `MemoryEvent` → `extractor.extract(event)` → 取首选偏好，与 `expected_type`/`expected_output` 比对（type 匹配 + output 子串/归一化相等）→ `correct`。
  - `compute_metrics(results)`：`accuracy`/`precision`/`recall`/`f1`/`avg_latency_ms`。
  - `run(dataset_path)`：加载 JSON → 逐条评测 → `EvalReport(task_name="preference_extraction")`。
- 数据集格式：`[{sample_id, input_text, expected_output, expected_type, scene}]`。

### F2 冲突评测器（`evaluation/metrics/conflict_eval.py` 填实）
- 基于 `PreferenceUpdater.ConflictDetector` + `ConflictResolver.auto_resolve`：
  - `evaluate_resolution`：old/new `PreferenceMemory` → `auto_resolve` 决策 → 映射 `override/merge/coexist/pending` 与 `expected_decision` 比对 → `resolution_accuracy`。
  - `evaluate_detection`：`check_preference` 判冲突 vs `expected_conflict` → `detection_accuracy` + `false_positive_rate`。
  - `run(dataset_path)`：`EvalReport(task_name="conflict")`，`accuracy=resolution_accuracy`。
- 数据集格式：`[{sample_id, old_preference, new_preference, expected_decision, scene, expected_conflict?}]`。

### F3 黄金数据集（`evaluation/datasets/`）
- `preference_golden_v1.json`：≥20 条，覆盖规则可提取的偏好（格式/语言/安全策略），确保无 LLM 也能跑出基线。
- `conflict_golden_v1.json`：≥20 条，覆盖 override/merge/coexist/pending + 检测正负例。

### F4 API 接入（`memoryhub/adapter/api.py` `/evaluate/{task_name}`）
- 加 `task == "preference"` 与 `task == "conflict"` 分支（当前返回 501），带 FileNotFound/ValueError 处理，与 retrieval 分支一致。

### F5 测试（`tests/test_evaluation.py`，新增）
- `compute_metrics` 已知结果准确率；内联小数据集 `run` 返回 `EvalReport`；冲突 resolution 确定性场景；可选 API 层测试。

## 关键文件

| 文件 | 动作 |
|---|---|
| `evaluation/metrics/preference_eval.py` | 填实 3 方法 |
| `evaluation/metrics/conflict_eval.py` | 填实 3 方法 |
| `evaluation/datasets/preference_golden_v1.json` | 新增 |
| `evaluation/datasets/conflict_golden_v1.json` | 新增 |
| `memoryhub/adapter/api.py` | evaluate 加分支 |
| `tests/test_evaluation.py` | 新增 |

## 验证方式（拾起时执行）

```
/d/Anaconda/envs/mhub311/python.exe -m pytest -q --tb=line tests/test_evaluation.py tests/test_api_acceptance.py tests/test_core_memory_unification.py
# 全量回归：失败集与基线一致
# 手工：POST /evaluate/preference?dataset_path=evaluation/datasets/preference_golden_v1.json → EvalReport(accuracy>0)
```

## 后续（不在本阶段）

- 检索召回攻坚：embedding 升级 `bge-large-zh`、cross-encoder 精排、query rewrite（需真实麒麟/Milvus + 冻结 golden 数据集重跑 R@5）。
- 大规模数据集（N≥200）与 Bootstrap CI。
