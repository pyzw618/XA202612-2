# MemoryHub vNext 故障处理手册

版本：`vnext/v1`

任务：`S5-09`

## 自动停止扩流条件

发生以下任一事件，立即将读路径切回 `legacy`：

- Policy Leakage > 0
- 跨租户结果 > 0
- Forget 残留检索 > 0
- DELETED/SUPERSEDED 进入 Context
- 任务恢复丢失硬约束
- P95/P99 超出约定预算且无安全降级路径
- 新旧结果差异中出现未解释的 Scope/版本倒退
- Outbox Dead Letter 持续增长或 Projection Lag 超过阈值

## 常见故障与处理

### 服务无法启动

```powershell
# 1. 检查配置与生产门禁
.\.venv\Scripts\python.exe -c "from memoryhub.config import load_config; load_config()"

# 2. 检查数据库可访问
.\.venv\Scripts\python.exe - <<'PY'
from memoryhub.storage.database import Database
Database().engine.connect()
print('db ok')
PY

# 3. 查看日志
Get-Content logs/memoryhub.log -Tail 50
```

### Embedding/Milvus 超时

```powershell
# 生产环境检查 SDK
.\.venv\Scripts\python.exe scripts/check_kylin_embedding_runtime.py
.\.venv\Scripts\python.exe scripts/run_milvus_real_smoke_test.py

# 若非生产且允许 fallback，切换 mock
# config.yaml: embedding.provider=mock, vector_engine.provider=milvus_mock
```

### Policy 泄漏

```powershell
# 运行安全回归
.\.venv\Scripts\python.exe -m pytest tests/test_safety_pipeline.py tests/test_user_isolation.py -q

# 检查隔离区
memoryhub review conflicts
```

### 重复投递 / Outbox 死信

```powershell
# 查看 pending/failed 投影
memoryhub projection list --status failed

# 重放指定 outbox
memoryhub projection replay <outbox-id>

# 或运行修复 worker
.\.venv\Scripts\python.exe scripts/repair_projections.py --db data/memoryhub.db --run-worker
```

### 索引损坏 / 数据不一致

```powershell
# 1. 漂移对账
.\.venv\Scripts\python.exe -m pytest tests/test_projection_outbox.py -q

# 2. 修复投影
.\.venv\Scripts\python.exe scripts/repair_projections.py --db data/memoryhub.db --dry-run
.\.venv\Scripts\python.exe scripts/repair_projections.py --db data/memoryhub.db --run-worker

# 3. 全量重建（最后手段）
.\.venv\Scripts\python.exe scripts/rebuild_projections.py --db data/memoryhub.db --dry-run
.\.venv\Scripts\python.exe scripts/rebuild_projections.py --db data/memoryhub.db
```

### Forget 残留

```powershell
# 验证残留为 0
.\.venv\Scripts\python.exe -m pytest tests/test_forget_semantic.py -q

# 手动触发 Forget 验证
memoryhub forget "验证残留" --preview
```

## 应急回滚脚本

```powershell
# 一键切回 legacy 读取
.\.venv\Scripts\python.exe - <<'PY'
from pathlib import Path
p = Path('config.yaml')
text = p.read_text(encoding='utf-8')
text = text.replace('vnext.mode: vnext', 'vnext.mode: legacy')
text = text.replace('vnext.mode: canary', 'vnext.mode: legacy')
p.write_text(text, encoding='utf-8')
print('rollback to legacy read')
PY

# 重启服务
powershell -ExecutionPolicy Bypass -File .\scripts\stop-memoryhub-service.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-memoryhub-service.ps1
```

## 联络与升级

- 发现安全/隐私零容忍故障：立即停止扩流并回滚读路径
- 记录 trace_id、request_id 和审计 ID
- 依据 `docs/vnext/spec/VNEXT_TRACE.md` 和 `EVIDENCE.md` 形成事件报告
