# MemoryHub vNext 部署与运维手册

版本：`vnext/v1`

任务：`S6-04`（补充完善阶段；保留 S5-09 的部署基线）

## 环境要求

- Python ≥ 3.11
- 虚拟环境（推荐 `.venv`）
- SQLite（自带，无需额外安装）
- 生产环境：银河麒麟 V11 / openKylin 2.x + Milvus 麒麟 C SDK + `libkylin-coreai-embedding.so`
- 开发/验证环境：Windows 10/11，Mock Embedding / Milvus Mock / FAISS 降级

## 安装

```powershell
# 1. 创建虚拟环境
python -m venv .venv

# 2. 安装生产依赖（Windows PowerShell）
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 或开发模式（含 CLI/MCP 入口）
.\.venv\Scripts\python.exe -m pip install -e .
```

## 配置

```powershell
# 复制示例配置并修改
cp config.example.yaml config.yaml
cp .env.example .env
```

核心配置节：

| 节 | 关键字段 |
|---|---|
| `runtime` | `mode`（production/development/test）、`allow_fallback` |
| `storage` | `db_path`、`vector_index_path`、`evidence_path` |
| `embedding` | `provider`（kylin/mock/kylin_mock/auto）、`dimension` |
| `vector_engine` | `provider`（milvus/faiss/milvus_mock）、`host`、`port`、`collection` |
| `safety` | `rule_set_id`、`policy`、`auto_mask`、`audit`、`quarantine` |
| `vnext` | `mode`（legacy/shadow/dual-read/canary/vnext）、`canary_percent` |

生产模式强制：`embedding.provider=kylin`、`vector_engine.provider=milvus`、`allow_fallback=false`。

## 启动服务

```powershell
# 自动脚本（Windows）
powershell -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1

# 手动启动
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8099

# 验证
.\.venv\Scripts\python.exe -c "from memoryhub_client import MemoryHubClient; print(MemoryHubClient().health())"
```

## CLI 快速验证

```powershell
# 安装后 CLI 全局可用；PATH 形式为：memoryhub --help
.\.venv\Scripts\memoryhub.exe --help

# 搜索；PATH 形式为：memoryhub search "周报格式" --json
.\.venv\Scripts\memoryhub.exe search "周报格式" --json

# 写入规范事件
.\.venv\Scripts\memoryhub.exe event examples/vnext_demo/event_start_report.json

# 恢复任务
.\.venv\Scripts\memoryhub.exe resume task_report_demo

# 遗忘预览（安全默认）
.\.venv\Scripts\memoryhub.exe forget "删除周报格式偏好" --preview
```

## 固定验收演示

演示不需要启动服务；所有 SQLite 和脱敏报告均写入显式输出目录：

```powershell
$demoOut = Join-Path $env:TEMP "memoryhub-vnext-demo"
& .\.venv\Scripts\python.exe -m examples.vnext_demo.run_demo --scenario all --output-dir $demoOut
Get-ChildItem -LiteralPath $demoOut -Filter "*.json"
```

应看到 `formation.json`、`evidence.json`、`scope.json`、`retrieval.json`、
`resume.json`、`forget.json` 和 `all.json`；报告默认不含原始 query、正文或 Evidence 正文。

## MCP 接入

```powershell
# 启动 MCP 服务器（stdio）
python -m memoryhub_mcp
```

客户端通过 JSON-RPC 2.0 调用工具：

- `memoryhub_health`
- `memoryhub_search`
- `memoryhub_get_context`
- `memoryhub_write_event`
- `memoryhub_resume_task`
- `memoryhub_remember`
- `memoryhub_forget`
- `memoryhub_feedback`

## 切换模式

| 模式 | 说明 | 命令/配置 |
|---|---|---|
| `legacy` | 旧链路提供结果，vNext 关闭 | `vnext.mode=legacy` |
| `shadow` | vNext Formation/Router 运行但不影响业务结果 | `vnext.mode=shadow` |
| `dual-read` | Authority 单写；新旧检索同时读，只返回旧结果 | `vnext.mode=dual-read` |
| `canary-5/25/50` | 按百分比返回 vNext | `vnext.mode=canary`, `canary_percent=5/25/50` |
| `vnext-100` | 全量返回 vNext | `vnext.mode=vnext` |

切流只允许 `legacy → canary-5 → canary-25 → canary-50 → vnext-100`；回滚可切回 legacy 或更低级别。

## 检查清单

- [ ] 配置文件与 `.env` 已复制并填写占位密钥
- [ ] 健康检查通过
- [ ] CLI `memoryhub status` 返回服务可用
- [ ] MCP `memoryhub_health` 返回 reachable
- [ ] 当前模式与预期一致：`GET /api/memory/system/config`
