# MemoryHub PySide6 + QML 客户端

QML 客户端与 Electron 并行存在，只通过本地 HTTP 连接常驻 FastAPI 后端。关闭任一客户端都不会停止后端进程。

## Windows 启动

现在也可以直接双击桌面的 `MemoryHub QML.lnk`。快捷方式会自动检查 `127.0.0.1:8010/api/health`，后端未运行时先启动后端，再打开 QML 客户端。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[qml,dev]"

# 终端 1：独立启动后端
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8000

# 终端 2：启动 QML 客户端
.\.venv\Scripts\python.exe -m memoryhub_qml
```

也可覆盖后端地址：

```powershell
$env:MEMORYHUB_BACKEND_URL = "http://127.0.0.1:8010"
.\.venv\Scripts\python.exe -m memoryhub_qml
```

客户端支持导入 `conversation-replay/1.0` JSON、10 轮逐步执行、工具轨迹、候选/引用/写入记忆和事实裁决。它不会自行启动、关闭或重启后端。

## 打包

Windows 在 Windows 上运行：

```powershell
pyside6-deploy -c memoryhub_qml/pysidedeploy.spec
```

Qt 6.11 的 Windows 部署脚本在部分机器上无法正确处理包含中文的仓库绝对路径。若 `qmlimportscanner` 报找不到命令，请将仓库复制或克隆到纯英文路径（例如 `C:\dev\memoryhub`）后执行同一命令；源码启动和测试不受此限制。

银河麒麟安装包必须在目标 Linux 和对应 CPU 架构上原生构建；Windows `.exe` 不能直接复制到麒麟运行。后端继续由 Windows 服务脚本或麒麟 systemd 用户服务独立管理。

## 客户端选型对比指标

| 指标 | QML | Electron |
| --- | --- | --- |
| 冷启动 | 由客户端 `startupMs` 记录 | 使用桌面进程计时 |
| 空闲内存 | 使用任务管理器/`Get-Process` | 使用任务管理器/`Get-Process` |
| 接口延迟 | 右侧活动栏 `lastLatencyMs` | 回放活动栏延迟 |
| 后端生命周期 | 完全独立 | 完全独立 |
