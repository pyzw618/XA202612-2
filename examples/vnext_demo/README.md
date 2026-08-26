# MemoryHub vNext 固定可重放演示

版本：`vnext/v1` · 阶段：`S6-04`

脚本使用确定性 fixture 和本地 FastAPI TestClient，不需要启动服务、外部模型或
Milvus。六类场景覆盖完整闭环：

1. `formation`：事件 → Working → Episode → Candidate，默认不固化 Authority；
2. `evidence`：两个独立任务的证据累积并固化为 Long-Term Authority；
3. `scope`：Global 与 Project Scope 共存，Project 值优先；
4. `retrieval`：展示 Intent、通道、Authority 检查、Scope、Budget 的红脱敏解释；
5. `resume`：关闭并重新打开 SQLite 后恢复 Goal、Constraints、Pending Steps；
6. `forget`：Authority 先阻断，验证 residual retrieval 为 0。

## 快速重放

PowerShell：

```powershell
$demoOut = Join-Path $env:TEMP "memoryhub-vnext-demo"
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario formation --output-dir $demoOut
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario evidence --output-dir $demoOut
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario scope --output-dir $demoOut
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario retrieval --output-dir $demoOut
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario resume --output-dir $demoOut
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario forget --output-dir $demoOut
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario all --output-dir $demoOut
```

Linux/macOS：

```bash
demo_out="${TMPDIR:-/tmp}/memoryhub-vnext-demo"
python -m examples.vnext_demo.run_demo --scenario all --output-dir "$demo_out"
```

不指定 `--output-dir` 时，脚本使用系统临时目录；不会写入本目录的默认源码路径。
每次运行都会重置指定目录内由 demo 自己管理的 `demo.db`，保证重放从空库开始。

## 输出契约

每个场景生成 `<scenario>.json`；`all` 额外生成 `all.json`，其中列出六个场景和
对应文件名。SQLite 数据库和全部报告都写入 `--output-dir`。报告默认只包含 ID、
hash、分类、计数、解释和状态元数据，不包含原始 query、事件正文或 Evidence 正文。

## 数据

`event_start_report.json`、`event_use_docx.json`、`event_repeat_docx.json`、
`event_markdown_global.json` 均为通用脱敏占位 fixture，不包含真实业务内容或密钥。
