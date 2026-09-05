# 部署与运维

> 面向三种形态：开发机（任意 OS）、银河麒麟生产机（DEB 安装包）、银河麒麟手动部署。
> vNext 专项运维手册（权威）：[部署](vnext/spec/VNEXT_DEPLOYMENT.md) · [备份恢复](vnext/spec/VNEXT_BACKUP_RECOVERY.md) · [迁移回滚](vnext/spec/VNEXT_MIGRATION.md) · [灰度切流](vnext/spec/VNEXT_ROLLOUT.md) · [故障处理](vnext/spec/VNEXT_FAULT_HANDLING.md)。

## 1. 开发部署（Windows / Linux）

无需麒麟环境，使用 mock embedding + FAISS 即可跑通全链路：

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                 # 填入 LLM_API_KEY（可选）
python -m uvicorn memoryhub.app:app --host 127.0.0.1 --port 8099
curl http://127.0.0.1:8099/api/memory/health
```

或使用服务脚本（后台常驻 + PID 管理）：

```bash
scripts/start-memoryhub-service.sh     # Linux；读取 MEMORYHUB_PYTHON/HOST/PORT
scripts/stop-memoryhub-service.ps1     # Windows 停止
scripts/start-memoryhub-service.ps1    # Windows 启动
```

## 2. 生产运行时要求（银河麒麟）

| 项 | 契约 |
|---|---|
| 操作系统 | 银河麒麟桌面 V10 系（含 SP1+）/ V11，`x86_64` 或 `aarch64`（动态库须匹配架构） |
| Embedding | `kylin-coreai-embedding` C SDK（`libkylin-coreai-embedding.so`），DBus 后端服务，模型 `ensemble-embd_gte-base_uint8-text`，固定 **768 维** |
| 向量引擎 | Milvus（麒麟 C API，`libkysdk-vector-engine-client`），需部署平台提供的 `app_id` |
| 配置 | `runtime.mode=production` + `config.example.yaml` 为样板；双层门禁不满足即拒绝启动 |

完整契约（.so 搜索路径、DBus、超时与错误码、embedding profile 升级规则）：[reference/kylin-embedding-runtime-contract.md](reference/kylin-embedding-runtime-contract.md)。

**部署前自检**（在目标机上逐项执行）：

```bash
python scripts/verify_kylin_environment.py        # 麒麟环境逐项定位
python scripts/check_kylin_embedding_runtime.py   # 对照运行时契约 §6 逐项检查
python scripts/run_milvus_real_smoke_test.py      # Milvus 真实 SDK 烟测
```

环境准备细节（真机交接）：[reference/kylin/kylin-environment-handoff-checklist.md](reference/kylin/kylin-environment-handoff-checklist.md)。

## 3. DEB 打包与安装（推荐交付形态）

### 构建（在麒麟或兼容的 Debian 系构建机上）

```bash
sudo apt install -y python3 python3-venv python3-pip build-essential cmake \
  dpkg-dev qtbase5-dev qtbase5-dev-tools libqt5charts5-dev
bash packaging/linux/build-deb.sh
# 产物：packaging/linux/dist/kylin-memoryhub_<version>-<revision>_amd64.deb (+ .sha256)
# 版本号取自 pyproject.toml；可用 MEMORYHUB_PACKAGE_VERSION / MEMORYHUB_PACKAGE_REVISION 覆盖

# 构建机无法访问 PyPI 时，可复用上一版 DEB 中的 wheelhouse：
MEMORYHUB_WHEEL_CACHE=/path/to/wheelhouse bash packaging/linux/build-deb.sh
```

构建流程：生成 Python wheelhouse（离线依赖）→ 编译并测试 Qt 客户端 → 装配 DEB。目标机安装时**无需访问 PyPI**。

### 安装包内容

- MemoryHub Python 后端（`/opt/memoryhub/venv`）+ 离线 wheel 依赖
- Qt 桌面控制台
- `memoryhub` CLI 与 `memoryhub-mcp`
- 桌面会话自启动服务（兼容银河麒麟 KARE）
- OpenCode 插件、工具、命令与 `memory-awareness` 技能
- 首次登录按用户自动配置脚本
- 服务配置：`/etc/memoryhub/config.yaml`（监听固定 `127.0.0.1:8099`）

### 安装与验证

```bash
sha256sum -c kylin-memoryhub_<version>-<revision>_amd64.deb.sha256
sudo apt install ./kylin-memoryhub_<version>-<revision>_amd64.deb   # 或文件管理器双击安装
memoryhub-configure-opencode --current-user   # 写入 ~/.config/opencode/ 插件配置
memoryhub status                              # CLI 连通性验证
```

细节与故障排查见 [packaging/linux/README.md](../packaging/linux/README.md)；面向最终用户的图文手册见 `old/docs/银河麒麟安装与使用手册.md`（按 0.1.0-12 Release 编写）。

> 注意：麒麟处于「维护模式」时先退出维护模式再安装；安装后如 OpenCode 未生效，重新执行 `memoryhub-configure-opencode --current-user`。

## 4. 数据与备份

- **事实源**：`storage.db_path`（默认 `data/memoryhub.db`）——SQLite 单文件。
- **密钥**：`<db目录>/security/safety-keys.json`——**必须与数据库一起备份**，否则审计链校验与隔离区解密不可恢复。
- **派生数据**（可不备份，可重建）：向量索引、BM25 索引、缓存。重建：`python scripts/rebuild_projections.py`。
- 备份/恢复的规范流程（含校验与演练要求）：[vnext/spec/VNEXT_BACKUP_RECOVERY.md](vnext/spec/VNEXT_BACKUP_RECOVERY.md)。

## 5. 运维脚本一览（scripts/）

| 脚本 | 用途 |
|---|---|
| `start-memoryhub-service.{sh,ps1}` / `stop-memoryhub-service.ps1` | 服务启停 |
| `verify_kylin_environment.py` | 麒麟环境逐项检查 |
| `check_kylin_embedding_runtime.py` | Embedding 运行时契约自检（生产部署前置） |
| `run_milvus_real_smoke_test.py` | Milvus 真实 SDK 烟测 |
| `verify_management_api.py` | 管理面 API 验证 |
| `migrate_vnext.py` | legacy → vNext 迁移：先只读扫描，显式 `--apply` 才写入；自动备份 + 校验（租户/scope/版本/证据），不确定行进入 REVIEW，不删除、不复活已删记录 |
| `migrate_memory_provenance.py` | 记忆谱系数据迁移 |
| `rebuild_projections.py` | 从 SQLite 全量重建向量/关键词投影 |
| `repair_projections.py` | 投影修复（配合 `storage/repair.py` 与 `/admin/reconcile` 对账） |

## 6. 升级与回滚

1. **升级前**：备份 db + 密钥文件；`migrate_vnext.py` 只读扫描确认迁移面。
2. **灰度**：`vnext.mode` 按 legacy → shadow → dual-read → canary(5/25/50/100%) → vnext 推进，使用 `/api/memory/vnext/rollout/*` 接口登记观察与推进（零容忍门禁）。
3. **回滚**：`POST /rollout/rollback` 为只读开关，回滚窗口默认 60 分钟；回滚不产生第二个 Authority 写者。
4. **版本状态**：软件版本以 `pyproject.toml` 为准（当前 0.1.0）；发布产物见 GitHub Releases。
