# Evaluation 目录说明

| 目录 | 用途 |
|---|---|
| `showcase/` | 面向展示的一键四项评测，以及它依赖的固定数据集 |
| `runners/` | 专项检索、延迟、Milvus、vNext、可靠性评测入口 |
| `datasets/` | 专项/大规模检索数据集、标注规范与校验清单 |
| `metrics/` | 可复用的指标计算与评测器实现 |
| `results/` | 已归档的评测报告与运行产物 |

展示评测：

```powershell
.\.venv\Scripts\python.exe evaluation\showcase\run.py
```

它会明确标识 mock 检索结果为 `DEMONSTRATION_ONLY`；正式麒麟 + Milvus 验收应使用
`runners/` 中的真实环境专项脚本。
