# 评测体系

> 对应赛题要求（7）「量化评测机制」：通过标准化数据集验证偏好提取准确率、知识检索召回率等核心指标。
> 目录：`evaluation/`（数据集 / 指标 / 驱动脚本 / 验收结果）+ `examples/vnext_demo/`（固定演示）。

## 1. 指标目标

| 指标 | 目标 | 赛题依据 |
|---|---|---|
| 知识检索召回率 R@5 | ≥ 0.85 | 评分表硬指标 |
| 检索延迟 | P95 ≤ 350ms，P99 ≤ 500ms | 赛题要求（4） |
| 偏好提取准确率 / 冲突处理正确率 | 量化基线 + 持续回归 | 赛题要求（2）（3） |
| vNext 形成/检索/反馈 | 与 legacy 对照不回退 | 内部质量门禁 |

## 2. 数据集（evaluation/datasets/）

| 文件 | 内容 |
|---|---|
| `memoryhub_knowledge_retrieval_v1_dev.json` / `_test.json` | 知识检索 dev / test 集（人工标注，test 用于验收） |
| `memoryhub_golden_retrieval_v1.json` | 检索 golden 集 |
| `memoryhub_retrieval_latency_v1.json` | 延迟评测查询集 |
| `showcase/datasets/preference_golden_v1.json` | 偏好提取 golden 集（展示一键评测） |
| `showcase/datasets/conflict_golden_v1.json` | 冲突处理 golden 集（展示一键评测） |
| `vnext_formation_eval.json` / `vnext_formation_p1_pairs.json` | vNext 形成链评测集（P0/P1 场景对） |
| `showcase/datasets/vnext_retrieval_eval.json` | vNext 检索场景评测集（展示一键评测） |
| `sources_golden/`（7 个域） | 多源接入 golden 样例：办公 / 开发 / 个人 A / 个人 B / 系统 / 通信 / 金融 |
| `memoryhub_retrieval_dataset_schema_v1.json` | 数据集 Schema（校验用） |
| `memoryhub_retrieval_annotation_guideline_v1.md` / `_records_v1.jsonl` | 标注指南与标注记录（可复核） |
| `SHA256SUMS.txt` | 数据集完整性校验 |

另有 `tests/eval_dataset.py` + `tests/eval_dataset.json`：程序化构造的多域评测集（100 条记忆 / 20 个带 ground-truth 查询，难度分层：精确匹配、语义相近、干扰、跨域），被多个评测驱动复用。

数据集完整性校验：

```bash
python evaluation/validate_retrieval_dataset.py
```

## 3. 指标实现（evaluation/metrics/）

| 模块 | 指标 |
|---|---|
| `retrieval_eval.py` | Recall@K / MRR / NDCG / Precision（含分组与隔离维度） |
| `vnext_retrieval_eval.py` | vNext 检索场景评测（含与 legacy 对照） |
| `latency_benchmark.py` | P50 / P95 / P99 延迟 |
| `formation_eval.py` | 形成链质量（候选/固化/幂等） |
| `preference_eval.py` | 偏好提取准确率 |
| `conflict_eval.py` | 冲突处理正确率 |
| `full_chain_benchmark.py` | 全链路基准（写入 → 检索端到端） |

## 4. 评测驱动（evaluation/showcase/ 与 evaluation/runners/）

| 命令 | 用途 |
|---|---|
| `python evaluation/showcase/run.py` | 四项展示评测（固定数据集，标记为演示证据） |
| `python evaluation/runners/run_retrieval_eval.py` | 检索质量评测（dev/test 数据集，mock 或 HTTP 后端） |
| `python evaluation/runners/run_latency_eval.py` | 延迟基准 |
| `python evaluation/runners/run_kylin_http_retrieval_evaluation.py` | 麒麟真机 HTTP 检索评测 |
| `python evaluation/runners/run_milvus_kylin_benchmark.py` | Milvus + 麒麟 SDK 真实基准（真机） |
| `python evaluation/runners/run_milvus_mock_benchmark.py` | Milvus mock 基准（开发机） |
| `python evaluation/runners/run_vnext_baseline.py` | vNext 基线固化 |
| `python evaluation/runners/run_vnext_eval.py` | vNext 形成/检索评测 |
| `python evaluation/runners/run_vnext_comparison.py` | vNext vs legacy 对照报告 |
| `python evaluation/runners/run_vnext_shadow.py` | Shadow 双读差异报告（脱敏，只观察） |
| `python evaluation/runners/run_vnext_rollout.py` | 灰度切流/回滚确定性演练 |
| `python evaluation/runners/run_reliability_eval.py` | 可靠性评测（故障注入维度） |

## 5. 验收结果（evaluation/results/）

以下为**正式验收证据**（被规格文档引用，勿删）：

| 文件 | 内容 |
|---|---|
| `final_acceptance_report.md` | 最终验收报告 |
| `vnext_benchmark.json` | vNext 四层可复现基准结果 |
| `vnext_baseline/baseline.json` + `dataset_validation.json` | vNext 基线与数据集校验 |
| `vnext_final/comparison.json` | vNext vs legacy 最终对照 |
| `vnext_shadow/shadow.json` + `rollout.json` | Shadow 双读与灰度演练产物（脱敏） |
| `vnext_migration/dry_run.json` | 迁移只读扫描报告 |
| `vnext_reliability_report.json` | 可靠性评测报告 |
| `latency_report.json` / `.md` | 延迟基准报告 |
| `retrieval_environment_manifest.json` | 检索评测环境指纹 |
| `dataset_validation_report.json` | 数据集校验报告 |
| `dev_eval*.md` / `test_eval_report.md` / `golden_eval_report.md` / `http_eval.*` | 各轮检索评测报告（dev/test/golden/HTTP） |

> `results/` 下的一次性中间产物（mock 运行、重复轮次 JSON）已在 2026-09 清理；再生成时请只提交被报告引用的文件。

## 6. 固定验收演示（examples/vnext_demo/）

六类固定场景 + 一键全量（确定性 fixture + FastAPI TestClient，无需启动服务/外部模型/Milvus）：

```bash
python -m examples.vnext_demo.run_demo --scenario all --output-dir examples/vnext_demo/output
python -m examples.vnext_demo.run_demo --scenario formation --output-dir <dir>   # 单场景
```

| 场景 | 覆盖闭环 |
|---|---|
| `formation` | 事件 → Working → Episode → Candidate（默认不固化 Authority） |
| `evidence` | 两个独立任务的证据累积并固化为 Long-Term Authority |
| `scope` | Global 与 Project Scope 共存，Project 值优先 |
| `retrieval` | Intent、通道、Authority 检查、Scope、Budget 的脱敏解释 |
| `resume` | 关闭并重开 SQLite 后恢复 Goal / Constraints / Pending Steps |
| `forget` | Authority 先阻断，验证 residual retrieval 为 0 |

每个场景只产出脱敏的 `<scenario>.json`；`all` 额外产出 `all.json`。详见 [examples/vnext_demo/README.md](../examples/vnext_demo/README.md)；该演示由 `tests/test_vnext_demo.py` 守护。

## 7. 评测与测试的关系

- `tests/test_evaluation.py`、`tests/test_vnext_*eval*.py`、`tests/test_full_chain_benchmark.py` 等以**确定性小样本**守护评测代码本身的正确性；
- 真机指标（麒麟 + Milvus）通过 §4 的驱动脚本在目标环境执行，结果归档到 `results/`；
- 验收口径以 [vnext/spec/VNEXT_ACCEPTANCE.md](vnext/spec/VNEXT_ACCEPTANCE.md) 为准。
