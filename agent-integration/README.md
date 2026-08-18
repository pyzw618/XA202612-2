# Agent Integration

统一的 MemoryHub Agent 接入层。CLI 是底层母语，MCP 和 opencode Plugin 都是薄壳。

```powershell
python -m pip install -e .
memoryhub --help
python -m memoryhub_mcp
```

opencode 默认安装 Plugin：

```powershell
node agent-integration/plugin/opencode/install_plugin.mjs
```

入口、REST 映射和迁移说明见 [docs/CONTRACT.md](docs/CONTRACT.md)，实现细节见 [docs/TECHNICAL.md](docs/TECHNICAL.md)。

旧的 `opencode-integration/` 和 `claudecode-integration/` 目录仍保留兼容脚本；新接入不要复制其中的 MCP server。

