# MemoryHub × opencode 集成

把 Kylin-MemoryHub 记忆模块接入 opencode 的两条链路：

- **MCP Server**（`mcp-server/`）：LLM 按需调用 `memoryhub_search`、`memoryhub_write_event`、
  `memoryhub_forget` 等 12 个工具读写记忆。
- **Plugin**（`plugin/`）：监听 `session.idle`，自动把 opencode 会话的工具轨迹沉淀为
  MemoryHub `MemoryEvent`，由记忆引擎抽取偏好/知识/事实。

两者都通过 HTTP 访问同一个 MemoryHub REST 服务（`memoryhub/adapter/api.py`）。

## 快速开始

```bash
# 1. 启动 MemoryHub REST（dev 模式：mock embedding + faiss）
python opencode-integration/scripts/start_memoryhub_server.py --port 8099
# 首次启动自动创建持久安全密钥，后续重启无需配置密钥

# 2. 接入 MCP Server：把 examples/opencode.json 的 mcp 段合并进项目 opencode.json

# 3. 接入 Plugin（复制到 .opencode/plugins/ 并导出环境变量后重启 opencode）
node opencode-integration/scripts/install_plugin.mjs
export MEMORYHUB_API_URL=http://127.0.0.1:8099
export MEMORYHUB_USER_ID=opencode
```

## 文档

- 接口对接清单、功能说明、配置与已知问题：**`docs/INTEGRATION.md`**

## 测试

```bash
D:/Anaconda/envs/py12/python.exe -m pytest opencode-integration/tests/test_mcp_server.py -v
node opencode-integration/tests/test_plugin_event_builder.mjs
```
