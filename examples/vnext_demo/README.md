# MemoryHub vNext 固定可重放演示

版本：`vnext/v1`

任务：`S5-10`

本目录包含一组脱敏、固定、可重放的演示脚本，展示 vNext 核心闭环：

1. 形成：事件 → Working → Episode → Candidate
2. 证据累积：多个独立任务推动 Candidate 固化
3. Scope 覆盖：Global Markdown 与 Project-A DOCX 共存
4. 检索解释：Intent、通道、分数、Scope、Budget
5. 任务恢复：服务重启后恢复 Goal/约束/待办
6. Forget 验证：删除后残留检索为 0

## 前置条件

- 服务已启动：`powershell -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1`
- CLI 可用：`memoryhub --help`
- 当前模式为 `legacy` 或 `vnext`（演示使用 vNext 统一入口）

## 快速重放

```powershell
# 1. 场景 1：项目报告偏好逐步形成
.\.venv\Scripts\python.exe examples/vnext_demo/run_demo.py --scenario formation

# 2. 场景 2：检索解释与 Scope 覆盖
.\.venv\Scripts\python.exe examples/vnext_demo/run_demo.py --scenario retrieval

# 3. 场景 3：任务恢复
.\.venv\Scripts\python.exe examples/vnext_demo/run_demo.py --scenario resume

# 4. 场景 4：Forget 验证
.\.venv\Scripts\python.exe examples/vnext_demo/run_demo.py --scenario forget

# 5. 全部
.\.venv\Scripts\python.exe examples/vnext_demo/run_demo.py --scenario all
```

## 输出

每个场景输出 `examples/vnext_demo/output/<scenario>.json`，仅包含 ID、hash、分类、计数、Trace 摘要和审计元数据，不包含原文或敏感 Evidence。

## 数据

- `event_start_report.json`：用户开始制作报告并给出格式约束
- `event_use_docx.json`：用户说“这次请用 DOCX”
- `event_repeat_docx.json`：另一个独立任务再次明确 DOCX
- `event_markdown_global.json`：用户设置全局 Markdown 偏好

所有正文均已脱敏，使用通用占位符。
