# Kylin MemoryHub 竞赛演示系统

当前开发分支：`feat/moyaohua-memoryhub-demo`

Kylin MemoryHub 是一个面向 Agent 的本地记忆中枢。本分支在原有 Python 记忆核心之上增加了 React 对话工作台和 Agent 适配接口，用于演示一段多轮对话中记忆的形成、检索、引用、冲突处理和遗忘过程。

## 当前可以演示什么

- 在同一个会话中逐轮执行 10 轮测试对话。
- 从原始对话中抽取偏好、工作流、模板和事实候选。
- 在后续轮次中真实查询后端，展示候选记忆和本轮实际引用的记忆。
- 展示工具名、参数、状态、耗时和脱敏后的工具返回结果。
- 对事实候选执行 `Propose / Commit / Reject` 两阶段处理。
- 预览精准遗忘候选，确认后由 Agent 适配层执行软删除。
- 导入 `conversation-replay/1.0` JSON，或者直接导入 `{ events: MemoryEvent[] }`。

目前主 Agent 仍采用确定性规则编排，尚未接入真实大模型。对话回复和外部工具轨迹来自 JSON；记忆抽取、事件写入、检索和事实候选处理由后端真实执行。

## 技术栈

| 部分 | 技术 |
| --- | --- |
| 前端 | React 19、TypeScript、vinext/Vite |
| 后端 | Python 3.11+、FastAPI、Pydantic |
| 结构化存储 | SQLite、SQLAlchemy |
| 检索 | BM25 + 向量检索 + 重排 |
| 向量实现 | FAISS；开发环境默认使用 Mock Embedding |
| Agent 接入 | `/api/agent/*` 适配接口 |

## 项目结构

```text
XA202612-2/
├─ frontend/                         # React 对话工作台
│  ├─ app/page.tsx                   # 主页面与管理页面
│  ├─ app/api.ts                     # 前端 API transport
│  ├─ app/replay.ts                  # JSON 校验、重建与脱敏
│  └─ public/examples/
│     └─ memory-system-long-replay.json
├─ memoryhub/
│  ├─ app.py                         # FastAPI 应用入口
│  ├─ adapter/api.py                 # 记忆读取与管理 API
│  ├─ adapter/agent_api.py           # 回放、逐轮执行和用户裁决
│  ├─ core/processing.py             # 统一事件处理协调器
│  ├─ core/preference/               # 偏好记忆
│  ├─ core/knowledge/                # 工作流与模板记忆
│  ├─ core/fact/                     # 事实候选与冲突处理
│  ├─ retrieval/                     # 混合检索
│  └─ storage/                       # SQLite 和向量存储
├─ tests/test_competition_api.py     # 竞赛演示链路测试
├─ config.yaml                       # 本地运行配置
└─ pyproject.toml                    # Python 项目配置
```

## 环境要求

- Git
- Python `>= 3.11`
- Node.js `>= 22.13.0`
- npm

Windows 下建议使用 PowerShell，并始终在仓库根目录执行后端命令。

## 1. 获取本分支

```powershell
git clone -b feat/moyaohua-memoryhub-demo https://github.com/pyzw618/XA202612-2.git
cd XA202612-2
```

已经克隆过仓库时：

```powershell
git fetch origin
git switch feat/moyaohua-memoryhub-demo
git pull --ff-only
```

## 2. 启动后端

### Windows PowerShell

首次运行时创建虚拟环境并安装依赖：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

如果 PowerShell 不允许执行激活脚本，可以不激活虚拟环境，直接使用：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

启动 FastAPI：

```powershell
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --reload --host 127.0.0.1 --port 8000
```

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m uvicorn memoryhub.app:app --reload --host 127.0.0.1 --port 8000
```

后端启动后访问：

- Swagger API 文档：<http://127.0.0.1:8000/docs>
- 服务健康检查：<http://127.0.0.1:8000/api/health>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>

开发演示默认使用 `config.yaml` 和 Mock Embedding，不需要配置大模型 API Key。运行数据会写入 `data/` 目录。

## 3. 启动前端

保持后端终端运行，再打开一个新的 PowerShell：

```powershell
cd frontend
npm ci
npm run dev
```

浏览器打开：<http://127.0.0.1:3000>

前端默认连接 `http://127.0.0.1:8000`。如果后端地址不同，在启动前端前设置：

```powershell
$env:NEXT_PUBLIC_MEMORYHUB_API="http://127.0.0.1:8000"
npm run dev
```

## Electron 桌面客户端

Electron 只负责展示和管理，不拥有 MemoryHub 后端进程。关闭桌面窗口只会关闭客户端，Agent 使用的本地记忆服务仍然继续运行。

```text
OS Agent ───────────────┐
                       ├──> MemoryHub 常驻服务（FastAPI / SQLite / FAISS）
Electron 桌面客户端 ────┘
```

### Windows：独立启动后端服务

在仓库根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1
```

这个脚本会把后端作为独立隐藏进程启动。随后启动或关闭 Electron，都不会影响后端。

需要明确停止后端时运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1
```

### 启动 Electron 开发版

```powershell
cd frontend
npm ci
npm run desktop:dev
```

如果首次安装 Electron 运行时下载较慢，可以仅对当前终端设置镜像后重新安装：

```powershell
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
npm ci
```

如果 Web 前端已经运行在 `127.0.0.1:3000`，也可以只打开桌面窗口：

```powershell
npm run desktop:open
```

### 构建桌面安装包

```powershell
cd frontend
npm run desktop:build  # 生成未打包目录，便于测试
npm run desktop:dist   # 生成 Windows 安装包
```

Linux/银河麒麟安装包必须在对应 Linux 和 CPU 架构环境中构建。`packaging/linux/memoryhub.service` 提供了后端常驻 systemd 用户服务模板。

## 4. 运行内置演示

1. 确认页面右上角的状态点显示后端已连接。
2. 点击“加载演示”。系统会创建新的用户 ID、会话 ID 和事件 ID，避免读取以前运行留下的记忆。
3. 点击“执行当前轮”，观察右侧本轮的记忆写入、候选记忆和实际引用。
4. 点击“下一轮”，继续执行完整的 10 轮对话。
5. 在事实候选出现后打开详情，体验 `Propose / Commit / Reject` 流程。

内置 JSON 位于：

```text
frontend/public/examples/memory-system-long-replay.json
```

也可以点击“导入 JSON”选择自己的对话文件。导入后不会自动批量写库，只有逐轮点击“执行当前轮”时才会调用后端。

## 5. 常用接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/agent/step` | 执行一轮对话并处理记忆 |
| `POST` | `/api/agent/replay` | 校验或执行 JSON 回放 |
| `POST` | `/api/agent/actions/{action_id}/decision` | 接收事实、冲突或遗忘裁决 |
| `POST` | `/api/memory/events` | 写入标准化事件 |
| `GET` | `/api/memory/events/session/{session_id}` | 读取一个会话的事件 |
| `POST` | `/api/memory/search` | 查询候选记忆 |
| `GET` | `/api/memory/preferences` | 查询偏好记忆 |
| `GET` | `/api/memory/knowledge` | 查询工作流或模板 |
| `POST` | `/api/memory/facts/propose` | 生成事实候选，不写入活动事实 |
| `POST` | `/api/memory/facts/{proposal_id}/commit` | 幂等提交事实候选 |
| `POST` | `/api/memory/forget/preview` | 预览精准遗忘结果 |
| `POST` | `/api/memory/forget` | 确认执行软删除 |

具体请求和响应结构以 Swagger 文档为准。

## 6. 测试与检查

后端测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

只测试本分支新增的竞赛链路：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_competition_api.py -q
```

前端检查：

```powershell
cd frontend
npm run lint
npm run build
```

## 当前完成度与限制

已经打通：

- 多轮会话逐步执行与事件幂等写入。
- 偏好、工作流、模板、事实候选抽取。
- 混合检索和实际引用标记。
- 事实提议、提交、拒绝、冲突等待裁决。
- 精准遗忘预览、软删除和历史记录。
- 工具结果脱敏与前端展示。

仍需继续开发：

- 接入真实主 Agent 和大模型实时回复。
- 将 JSON 中的外部工具轨迹替换为真实工具执行。
- 完善 LLM 语义抽取和复杂事实理解。
- 完成自动遗忘调度、真实评测执行和安全看板。
- 增加生产环境鉴权、数据库迁移、并发与异常恢复。

## 给接力同学的约定

- 前端读取记忆可以直接调用 `/api/memory/*`。
- 改变记忆状态的操作应先提交给 `/api/agent/actions/*/decision`，由 Agent 适配层调用 MemoryHub，不要在页面中直接写库。
- 前端不要自行计算相关性、冲突关系或最终裁决，展示后端返回值即可。
- 后续接入真实 Agent 时，优先替换 `memoryhub/adapter/agent_api.py` 中的确定性编排，并保持现有响应结构，前端无需整体重写。
- 提交代码前至少运行后端竞赛链路测试，以及前端 lint/build。
