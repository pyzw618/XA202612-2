# MemoryHub vNext 备份与恢复手册

版本：`vnext/v1`

任务：`S5-09`

## 备份对象

| 对象 | 路径 | 说明 |
|---|---|---|
| SQLite 事实源 | `data/memoryhub.db` | 唯一 Authority Store |
| 向量索引 | `data/vector_index.faiss` | 可重建投影 |
| 向量元数据 | `data/vector_index.meta.json` | 可重建投影 |
| 证据链 | `data/evidence/` | 审计与合规 |
| 安全密钥 | `<db_dir>/security/safety-keys.json` | 不可丢失 |
| 配置 | `config.yaml`、`.env` | 环境相关 |

## 在线备份（推荐）

```powershell
# 1. 停止服务或确保无写入窗口
powershell -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1

# 2. 原子拷贝数据库与索引
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = "backups/$timestamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item data/memoryhub.db $backupDir/
Copy-Item data/vector_index.faiss $backupDir/ -ErrorAction SilentlyContinue
Copy-Item data/vector_index.meta.json $backupDir/ -ErrorAction SilentlyContinue
Copy-Item config.yaml $backupDir/ -ErrorAction SilentlyContinue
Copy-Item .env $backupDir/ -ErrorAction SilentlyContinue

# 3. 记录备份 hash
$hash = Get-FileHash $backupDir/memoryhub.db -Algorithm SHA256 | Select-Object -ExpandProperty Hash
Write-Host "backup_hash=$hash backup_dir=$backupDir"
```

## 恢复流程

```powershell
# 1. 停止服务
powershell -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1

# 2. 恢复数据库与配置（示例恢复到 20260825-120000）
$backupDir = "backups/20260825-120000"
Copy-Item $backupDir/memoryhub.db data/memoryhub.db
Copy-Item $backupDir/vector_index.faiss data/ -ErrorAction SilentlyContinue
Copy-Item $backupDir/vector_index.meta.json data/ -ErrorAction SilentlyContinue

# 3. 可选：从 Authority 重建投影
.\.venv\Scripts\python.exe scripts/rebuild_projections.py --db data/memoryhub.db --dry-run
.\.venv\Scripts\python.exe scripts/rebuild_projections.py --db data/memoryhub.db

# 4. 启动服务并验证
powershell -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1
.\.venv\Scripts\python.exe - <<'PY'
from memoryhub_client import MemoryHubClient
print(MemoryHubClient().health())
PY
```

## 迁移回滚

vNext 迁移写入的是 Authority 兼容元数据，不回滚已经正确提交的旧事实。回滚步骤：

```powershell
# 1. 使用迁移前备份恢复数据库（若迁移尚未关闭旧写入）
Copy-Item backups/pre-migration/memoryhub.db data/memoryhub.db

# 2. 切换读取路径到 legacy
# 在 config.yaml 中设置 vnext.mode=legacy 并重启服务

# 3. 验证残留检索为 0
memoryhub forget "__validate_residual__" --preview
```

## 索引损坏恢复

```powershell
# 删除损坏的向量索引（Authority 事实仍在 SQLite）
Remove-Item data/vector_index.faiss -ErrorAction SilentlyContinue
Remove-Item data/vector_index.meta.json -ErrorAction SilentlyContinue

# 从 Authority 重建
.\.venv\Scripts\python.exe scripts/rebuild_projections.py --db data/memoryhub.db

# 验证
.\.venv\Scripts\python.exe scripts/repair_projections.py --db data/memoryhub.db --dry-run
```

## 灾难恢复优先级

1. 恢复 SQLite 事实源（最高优先级）
2. 恢复安全密钥（否则审计链无法验证）
3. 从 Authority 重建向量/BM25/Cache 投影
4. 重放 Projection Outbox 中的 pending/failed 条目
5. 验证租户隔离与 Forget 残留
