# 千问 Agent 接入与验证

当前最小实现提供四个可运行接口：

- `GET /api/memory/health`
- `POST /api/memory/events`
- `POST /api/memory/search`
- `POST /api/memory/context`

Agent 使用 LangChain `create_agent` 构建的 LangGraph 工具循环，模型通过阿里云百炼
OpenAI-compatible API 调用千问。Agent 执行前读取记忆上下文，执行后把用户消息、
工具名、参数、原始结果、顺序和最终回答写入 MemoryHub。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,agent]"
```

## 配置

复制 `.env.example` 为 `.env`，只填写本机密钥：

```dotenv
DASHSCOPE_API_KEY=你的阿里云百炼_API_Key
QWEN_MODEL=qwen-plus
```

`.env` 已被 Git 忽略，禁止把真实密钥提交到仓库。

## 启动 MemoryHub

```powershell
.\.venv\Scripts\python.exe -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs` 查看接口文档。

## 运行真实 Agent

第一轮写入偏好并生成周报：

```powershell
.\.venv\Scripts\python.exe examples\run_qwen_agent.py `
  "读取本周资料生成周报，以后项目周报都使用 Markdown 三段式"
```

第二轮使用同一个用户再次执行：

```powershell
.\.venv\Scripts\python.exe examples\run_qwen_agent.py `
  "按上次的方式生成本周项目周报"
```

生成的报告位于 `examples/demo_workspace/outputs/`。第二次运行返回的
`memory_context` 应包含第一轮保存的 Markdown 三段式偏好。

## 安全边界

演示工具只能读取 `examples/demo_workspace` 下的文本、Markdown 和 JSON 文件，
并且只能向该目录的 `outputs` 子目录写 Markdown 文件。它不会执行 shell 命令，
也不会读取工作区外的文件。
