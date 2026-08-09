# Kylin MemoryHub

端侧 Agent 记忆系统的 React + Electron 演示项目。

本项目由两个独立部分组成：

- frontend：React 对话工作台和 Electron 桌面客户端。
- memoryhub：Python/FastAPI 本地记忆服务，负责事件处理、偏好、知识、事实、检索、冲突和遗忘。

Electron 只负责窗口和桌面交互，不拥有后端生命周期。关闭前端窗口后，后端服务可以继续运行。

## 1. 环境要求

- Windows 10/11 或银河麒麟 Linux
- Git
- Python 3.11+
- Node.js 22+
- npm

第一次使用时，请在仓库根目录执行命令。Windows 如果 PowerShell 禁止执行 npm 脚本，可以使用 npm.cmd。

## 2. 获取代码

~~~powershell
git clone -b frontend-React-version https://github.com/pyzw618/XA202612-2.git
cd XA202612-2
~~~

如果仓库还没有这个分支，先使用默认分支，再切换到实际存在的分支：

~~~powershell
git branch -a
git checkout <实际分支名>
~~~

## 3. 安装后端环境

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

如果项目中没有 requirements.txt，按照 pyproject.toml 安装：

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e .
~~~

## 4. 安装前端依赖

~~~powershell
cd frontend
npm.cmd install
cd ..
~~~

## 5. 启动后端

在仓库根目录打开第一个 PowerShell 窗口：

~~~powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1
~~~

后端默认监听 http://127.0.0.1:8000。

打开下面地址可以查看 FastAPI 接口文档：

~~~text
http://127.0.0.1:8000/docs
~~~

后端停止命令：

~~~powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1
~~~

## 6. 启动 React 网页版

如果只调试网页，在第二个 PowerShell 窗口执行：

~~~powershell
cd frontend
npm.cmd run dev
~~~

浏览器打开：

~~~text
http://127.0.0.1:3000
~~~

这里的 3000 是 React 开发服务器端口。它只负责提供页面资源，记忆数据仍由 8000 端口的后端处理。

## 7. 启动 Electron 桌面版

开发阶段推荐使用：

~~~powershell
cd frontend
npm.cmd run desktop:dev
~~~

这条命令会自动启动 React 开发服务，然后打开独立的 MemoryHub 桌面窗口。

桌面版和浏览器版使用相同的 React 页面和后端 API，区别在于 Electron 提供了独立窗口、桌面快捷方式、托盘和后续系统集成能力。

## 8. 生成桌面程序和快捷方式

先编译 React 并生成 Windows 桌面目录：

~~~powershell
cd frontend
npm.cmd run desktop:build
~~~

正常情况下，程序位于：

~~~text
frontend\desktop-dist\win-unpacked\MemoryHub.exe
~~~

然后回到仓库根目录，自动创建桌面快捷方式：

~~~powershell
cd ..
powershell.exe -ExecutionPolicy Bypass -File .\scripts\create-memoryhub-shortcut.ps1
~~~

脚本会在 Windows 桌面创建 MemoryHub.lnk。以后双击这个快捷方式即可打开桌面程序。

如果需要安装包：

~~~powershell
cd frontend
npm.cmd run desktop:dist
~~~

安装包会输出到 frontend\desktop-dist\。

注意：桌面程序依赖本地后端。首次双击前，应先启动后端服务；关闭 Electron 不会自动删除或清空后端数据。

## 9. 快捷方式打不开或显示默认 HTML 样式

按下面顺序检查：

1. 确认快捷方式目标是当前仓库中的 MemoryHub.exe。
2. 关闭旧的 MemoryHub 窗口后重新打开。
3. 重新执行 npm.cmd run desktop:build。
4. 再执行 create-memoryhub-shortcut.ps1，让快捷方式指向最新程序。
5. 检查 http://127.0.0.1:8000/docs 是否可以访问。

如果页面内容存在但布局完全消失，通常是 CSS 静态资源没有进入打包目录；检查 dist\client\assets 是否包含 .css 文件。

## 10. 使用内置回放案例

主页面支持导入 JSON 对话。内置案例位于：

~~~text
frontend\public\examples\memory-system-long-replay.json
~~~

导入后可以逐轮执行，观察：

- 多轮聊天记录
- Agent 工具调用
- 检索候选记忆
- 本轮实际引用的记忆
- 新写入的偏好、知识和事实候选
- 事实 Propose / Commit / Reject
- 精准遗忘预览和历史记录

导入 JSON 本身不会自动批量写入数据库。只有点击执行某一轮时，才会调用后端处理流程。

## 11. 前后端职责

~~~text
Electron
  └─ React 页面
       └─ HTTP JSON API
            └─ FastAPI / Agent 适配层
                 └─ 记忆处理、SQLite、BM25、向量索引
~~~

React 负责页面、状态和用户操作；Agent 负责决定何时调用工具；MemoryHub 负责真正的记忆读写、冲突处理和遗忘。前端不要直接修改核心记忆数据库。

读取型接口可以由前端调用，例如记忆查询、知识列表和会话事件读取。改变记忆状态的操作应通过 Agent action decision 进入后端。

## 12. PySide6 + QML 桌面客户端

项目同时提供独立的 PySide6 + QML 客户端。它与 React 浏览器版、Electron 版共用同一个 FastAPI 后端，但客户端关闭不会停止后端服务。

架构如下：

~~~text
QML 客户端 / React 浏览器 / Electron
              │ HTTP JSON
              ▼
       FastAPI 本地后端
       127.0.0.1:8010
              │
              ▼
     SQLite / FAISS / BM25 / 记忆处理
~~~

### 启动方式

桌面端推荐直接双击桌面的 `MemoryHub QML.lnk`。它会自动检查后端状态，后端未启动时先启动 FastAPI，再打开 QML 客户端。

手动启动：

~~~powershell
# 终端 1：启动后端
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8010

# 终端 2：启动 QML 客户端
$env:MEMORYHUB_BACKEND_URL="http://127.0.0.1:8010"
.\.venv\Scripts\python.exe -m memoryhub_qml
~~~

QML 客户端支持：

- 左侧功能菜单：偏好、事实、知识、冲突、遗忘、安全规则和评测等模块入口；
- 对话记录：加载 10 轮演示会话并逐轮执行；
- Agent 工具轨迹：显示工具参数、状态、耗时和脱敏结果；
- 记忆活动：查看候选记忆、实际引用记忆、本轮写入和事实候选；
- 事实 Propose / Commit / Reject 裁决，并将裁决交给 Agent 后端执行；
- 导入 `conversation-replay/1.0` JSON 文件。

QML 客户端代码位于：

~~~text
memoryhub_qml/__main__.py       客户端入口
memoryhub_qml/controller.py     回放状态和 API 控制器
memoryhub_qml/api.py            QNetworkAccessManager HTTP 封装
memoryhub_qml/replay.py         JSON 回放校验和脱敏
memoryhub_qml/models.py         QML 列表模型
memoryhub_qml/qml/Main.qml      主窗口和三栏布局
memoryhub_qml/qml/components/   工具卡、记忆卡、事实弹窗
~~~

后端地址可以通过 `MEMORYHUB_BACKEND_URL` 覆盖。银河麒麟部署时，客户端和后端仍然分开运行；QML 安装包需要在目标 Linux 和 CPU 架构上原生构建。

## 13. 主要代码位置

~~~text
frontend/app/page.tsx             React 主页面
frontend/app/api.ts               前端 API 封装
frontend/app/replay.ts            回放 JSON 校验和重建
frontend/electron/main.cjs        Electron 主进程
frontend/electron/preload.cjs     安全 IPC 桥接
frontend/electron/ui-server.cjs   打包版页面服务器

memoryhub/app.py                  FastAPI 应用入口
memoryhub/adapter/api.py          记忆查询和管理接口
memoryhub/adapter/agent_api.py    Agent 回放和裁决接口
memoryhub/core/processing.py      事件处理协调器
memoryhub/retrieval/              混合检索
memoryhub/storage/                SQLite 和索引存储
~~~

## 14. 常用接口

| 方法 | 接口 | 作用 |
| --- | --- | --- |
| POST | /api/agent/step | 执行一轮 Agent 对话 |
| POST | /api/agent/replay | 执行 JSON 回放 |
| POST | /api/memory/events | 写入标准事件 |
| GET | /api/memory/events/session/{session_id} | 读取会话事件 |
| POST | /api/memory/search | 检索记忆候选 |
| POST | /api/memory/facts/propose | 生成事实候选 |
| POST | /api/memory/facts/{proposal_id}/commit | 提交事实候选 |
| POST | /api/memory/forget/preview | 预览精准遗忘 |
| POST | /api/memory/forget | 执行软删除 |

详细参数以 Swagger 文档为准：http://127.0.0.1:8000/docs。

## 15. 检查和测试

后端测试：

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
~~~

前端检查：

~~~powershell
cd frontend
npm.cmd run lint
npm.cmd run build
~~~

## 16. 提交代码前的约定

- 不要把数据库文件、向量索引、密钥和 .env 提交到 GitHub。
- 不要把未脱敏的工具调用原文直接展示到前端。
- 修改 API 响应时尽量保持已有字段兼容。
- 涉及记忆状态变化时，优先通过 Agent action 接口完成。
- 提交前至少运行后端测试以及前端 lint/build。
- 如果修改了桌面启动流程，同时检查浏览器版和 Electron 版。

## 17. 当前限制

- 当前 Agent 默认以确定性规则编排，真实大模型接入沿用现有 Agent transport。
- 自动遗忘调度、完整评测执行和部分安全看板仍在完善。
- 银河麒麟版本需要在目标机器上重新安装 Python、Node 和 Linux Electron 构建依赖。
