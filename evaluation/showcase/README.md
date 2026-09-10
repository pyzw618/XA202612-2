# 一键展示评测

运行以下命令即可生成四项指标的 JSON 和 Markdown 报告：

```powershell
.\.venv\Scripts\python.exe evaluation\showcase\run.py
```

本目录是展示入口的完整最小集合：

- `run.py`：一键评测脚本；
- `datasets/`：偏好提取、冲突处理、vNext 检索三份固定评测数据；
- `../results/showcase/`：默认生成的报告位置。

报告会记录当前配置中的向量引擎和 Embedding 类型，并固定标识为
`DEMONSTRATION_ONLY`。其中的检索通道是确定性 mock，用于展示和回归；真实
麒麟 + Milvus 验收仍须运行生产冒烟与 HTTP 评测。
