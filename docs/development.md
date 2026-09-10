# 开发指南

## 1. 开发环境

```bash
# Python 3.11+（必须；项目使用 3.10+ 语法与 dataclass 契约）
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # 或 pip install -e ".[dev]"（同时注册 memoryhub CLI 入口）
```

启动服务与验证见 [../README.md](../README.md#快速开始)。开发模式（mock embedding + FAISS）无需任何麒麟/Milvus 依赖。

## 2. 测试

```bash
pytest                                 # 全量（133 个测试文件；asyncio_mode=auto，testpaths=tests）
pytest tests/test_vnext_contracts.py   # 单文件
pytest tests/ -k "safety"              # 关键字过滤
```

测试家族速查：

| 家族 | 文件 | 守护内容 |
|---|---|---|
| vNext 契约/场景 | `test_vnext_*`（60+ 个） | 数据契约、形成/检索/反馈/演化、灰度、Trace、看板、golden fixtures（`tests/fixtures/vnext/`） |
| 验收测试 | `test_{evt,pre,knw,fct,for,ret,sec,lif,per,api}_acceptance.py` | 赛题功能逐项验收（对应历史 TEST_PLAN，快照归档于 `old/docs/0811功能性测试/`） |
| 安全 | `test_safety_*`、`test_user_*` | 规则库、门禁、审计链、隔离区、用户规则、租户隔离 |
| 写入边界 | `test_no_production_write_bypass.py`、`test_core_memory_unification.py`、`test_memory_write_contract_schema.py` | **Authority 单写者不被绕过**（新增写路径必须通过它） |
| 数据流回归 | `test_data_flow_*`、`test_remaining_data_flow_regressions.py` | 历史缺陷回归 |
| 检索/向量引擎 | `test_retrieval*`、`test_milvus_*`、`tests/test_vector_engine/`、`tests/test_retrieval/` | 混合检索、FAISS/Milvus(mock)、稀疏向量、app_id 迁移 |
| 知识/偏好 | `tests/test_knowledge/`、`test_preference_*`、`test_tool_preference_miner.py` | 抽取链路（含 mock LLM 管线演示脚本 `run_*_pipeline.py`） |
| 文档一致性 | `test_vnext_docs.py`、`test_vnext_architecture_adr.py`、`test_vnext_demo.py` | **文档存在性与关键命令有效性**（见 §5） |
| 客户端 | `desktop-client/tests/ApiClientTest.cpp`（ctest） | Qt ApiClient |

> 注意：部分宿主机上 pytest 默认临时目录可能受权限限制；测试产生的本地数据库（`evaluation/results/*.db` 等）不要提交（.gitignore 已覆盖）。

## 3. 代码规范

- **ruff**：`line-length=100`，`target-version=py311`，规则 `E,F,I,W`（含 import 排序）。提交前对改动文件执行 `ruff check <files>`。
- **black**：默认参数格式化。
- **mypy**：类型检查（渐进式，不强制全仓通过）。
- 命名与注释风格跟随现有模块：中文 docstring 说明意图，代码标识符英文。
- 仓库当前未配置 CI；**推送前请本地跑受影响测试 + ruff**。

## 4. 项目结构约定

### 分层职责（详见 [architecture.md](architecture.md)）

| 目录 | 职责 | 新增代码放哪里 |
|---|---|---|
| `memoryhub/adapter/` | REST 路由 + Pydantic DTO | 新端点、新请求/响应模型 |
| `memoryhub/application/` | vNext 应用服务（编排） | 新用例/编排逻辑 |
| `memoryhub/domain/` | vNext 领域契约 | 新领域词汇、状态机 |
| `memoryhub/core/` | 领域实现（抽取/冲突/安全/生命周期） | 领域算法 |
| `memoryhub/retrieval/` | 检索通道与融合 | 新通道、重排因子 |
| `memoryhub/storage/` | 仓储 + 投影 + 向量引擎 | 新表、新仓储 |
| `memoryhub/observability/` | Trace / 指标 / 审计 | 新观测点（**必须脱敏**） |

### 硬性边界（由测试守护，违反会挂测试）

1. **生产写入只能走 Canonical Write → Authority 单写者**；禁止在端点/服务里直接写长期记忆表或索引（`test_no_production_write_bypass.py`）。
2. **Trace/观测不得包含正文**：递归校验拒绝原始 query/content/payload 字段入库（`VNEXT_TRACE.md` 契约）。
3. **租户/scope/Policy/Forget 边界在读写两侧强制**；新端点必须传播 `X-MemoryHub-Tenant` 与用户 scope。
4. **配置新键**：加到 `config.py` dataclass（带校验）→ 同步 `config.example.yaml` 注释 → 同步 [configuration.md](configuration.md)；环境变量覆盖加在 `load_config()`。
5. **DTO 变更**：`schemas.py` / `vnext_schemas.py` 是唯一权威，改字段必须同步 [api.md](api.md)（schemas.py 文件头有此约定）。

### 顶层桥接包（勿删）

`memoryhub_cli/`、`memoryhub_client/`、`memoryhub_mcp/` 三个顶层目录各含一个 `__init__.py`，把包路径重定向到 `agent-integration/` 下的规范实现。作用：源码检出（未 pip install）时 `python -m memoryhub_cli.cli`、`from memoryhub_client import ...` 直接可用；`pyproject.toml` 的 `package-dir` 与安装入口也依赖此布局。接入层代码只在 `agent-integration/` 下修改。

## 5. 文档维护约定

- `docs/` **只放当前有效的文档**；描述"过程/历史/计划执行记录"的文档一律进 `old/`（只读归档，不得作为现状依据，也不再维护）。
- 六个 vNext 运维规格（`docs/vnext/spec/VNEXT_{DEPLOYMENT,BACKUP_RECOVERY,FAULT_HANDLING,MIGRATION,ROLLOUT,ACCEPTANCE}.md`）与 `agent-integration/README.md` 由 `tests/test_vnext_docs.py` 守护：**文件必须存在、非空，且 DEPLOYMENT 中的关键命令（`memoryhub --help`、`memoryhub search`、`python -m memoryhub_mcp`、`vnext.mode`）必须保留**。移动/重命名这些文件必须同步改测试。
- `docs/vnext/design/ADR-vnext-memory-architecture.md` 由 `tests/test_vnext_architecture_adr.py` 守护（关键术语冻结），修订 ADR 需同步更新测试。
- 代码 docstring 引用文档时，使用**当前**路径（`docs/...`）；引用归档文档时使用 `old/docs/...` 前缀。

## 6. 桌面客户端开发（desktop-client/）

- Qt 5.15 Widgets + C++17 + CMake；页面模式：`BasePage` 派生 + `ApiClient`（同步 `QEventLoop` 等待，20s 超时）+ `j::` JSON 工具函数。
- Linux/麒麟构建：`bash build-linux.sh`；Windows 构建：`powershell -ExecutionPolicy Bypass -File build-win.ps1`（脚本内部用 ASCII junction 规避中文路径对 moc/链接器的破坏，勿直接在中文路径下跑 CMake+NMake）。
- 新增页面：`src/pages/` 加 .h/.cpp → 注册进 `CMakeLists.txt` → 侧边栏挂载（`MainWindow.cpp`）→ 图标进 `resources/icons/` + `resources/app.qrc`。
- 测试：`cd desktop-client && ctest --test-dir build -V`。

## 7. Agent 接入层开发（agent-integration/）

- 架构：CLI 是底层母语（`memoryhub_cli/cli.py`，argparse 子命令），SDK（`memoryhub_client/client.py`，httpx 同步）承载全部 REST 逻辑，MCP（`memoryhub_mcp/`，stdio JSON-RPC）与 OpenCode 插件（`plugin/opencode/`，Node）都是薄壳。
- 新增能力顺序：后端路由（adapter）→ SDK 方法 → CLI 子命令 → MCP 工具/插件 tool → 更新 `agent-integration/README.md` 与 `docs/api.md`。
- 接入层测试：`agent-integration/tests/`（pytest + `test_plugin_events.mjs` 用 node 运行）。

## 8. 常用命令速查

```bash
# 后端
python -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8099
pytest && ruff check memoryhub tests

# 接入层
memoryhub --help && memoryhub status
python -m memoryhub_mcp            # stdio，Ctrl+C 退出
node agent-integration/plugin/opencode/install_plugin.mjs

# 演示与评测
python -m examples.vnext_demo.run_demo --scenario all --output-dir examples/vnext_demo/output
python evaluation/runners/run_retrieval_eval.py

# 桌面端
cd desktop-client && bash build-linux.sh && ./build/memoryhub-client

# 打包
bash packaging/linux/build-deb.sh
```
