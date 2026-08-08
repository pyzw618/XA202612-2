# 真实 Agent 事件清洗示例

项目提供一条可重复运行的旧版 OS Agent 事件。输入包含多余空白、旧字段、
空元数据、调试字段、三次工具调用和测试手机号，流水线依次执行：

```text
raw JSON
  -> DataCleaner
  -> DataNormalizer
  -> QualityScorer
  -> SensitiveDetector.process
  -> MemoryEvent 1.1
```

运行：

```powershell
.\.venv\Scripts\python.exe examples\run_ingestion_demo.py
```

同时生成可检查的 JSON 文件：

```powershell
.\.venv\Scripts\python.exe examples\run_ingestion_demo.py `
  --output examples\cleaned_agent_event.json
```

输入文件是 `examples/raw_agent_event.json`，项目生成的规范结果是
`examples/cleaned_agent_event.json`。

示例验证以下转换：

| 原始输入 | 规范输出 |
|---|---|
| `source: os_agent` + 多个 `tool_calls` | `source_type: tool_result` |
| `task_id` | `session_id` |
| 带 `+08:00` 的 `timestamp` | UTC 秒精度 `occurred_at` |
| `content.answer` | `text` |
| `name/input/output/ok` | `tool_name/arguments/result/success` |
| `weekly_report` | `office.weekly_report` |
| 顶层 `debug`、`_debug_dump` | 删除 |
| `null` 元数据 | 删除 |
| 手机号 | `[REDACTED_PHONE]`，并记录 `redactions: [phone]` |

`pipeline.findings` 只输出规则名、风险等级、字段路径和动作，不回显敏感原文。
最终 `event` 会再次通过 Pydantic `MemoryEvent` 校验，确保示例不是手写伪造结构。
