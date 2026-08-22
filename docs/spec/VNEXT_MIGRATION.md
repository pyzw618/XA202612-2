# MemoryHub vNext 迁移与回滚契约

版本：`vnext/v1`

冻结任务：`S0-05`
dry-run 实现：`scripts/migrate_vnext.py`

## S0-05 范围

当前仓库使用 SQLAlchemy `Base.metadata.create_all()` 加上
`Database._ensure_compatible_schema()` 的加法式 SQLite 兼容迁移，没有统一
Alembic 版本链。S0-05 先提供只读规划器，不在迁移预演时 bootstrap 数据库、
建表、更新行、删除行或写入旧表。

```powershell
python scripts/migrate_vnext.py --dry-run --report evaluation/results/vnext_migration/dry_run.json
```

可用 `--db` 指定数据库，默认 `data/memoryhub.db`。数据库不存在时仍生成
空计划并标记 `missing_database=true`，不伪造迁移成功。

## 报告内容

报告必须包含：

- `count`：源记录、按来源和计划动作的数量；
- `hash`：记录 hash 列表和稳定 `input_hash`，不包含正文；
- `tenant`：tenant 计数；缺少 tenant 的旧数据进入 `UNKNOWN`/REVIEW；
- `scope`：Scope 计数；无法显式映射的记录进入 `REVIEW:UNRESOLVED`；
- `invalid`：缺失 ID/user 或结构非法的数量和原因；
- `review`：缺 Evidence、tenant、Scope 等存疑记录和原因；
- `validation`：只读扫描、无不可逆删除、不得把存疑数据提升为
  `LONG_TERM + ACTIVE + GLOBAL`；
- `compatibility`：apply 延后到 S5-06、Projection 重建和回滚策略。

报告和 Trace 只保存 ID、hash、分类和计数，不复制长期正文或敏感 Evidence。

## 旧值映射与存疑处理

1. 有明确 Project/应用 Scope、tenant、版本和 Evidence 的记录才允许进入
   后续 `LONG_TERM` 候选计划；S0-05 仍只生成计划，不提交 Authority。
2. 缺 tenant、Scope 或 Evidence 的记录进入 `REVIEW`，不得静默变成 Global
   Active。
3. 已删除记录只能规划为 `DELETED_TOMBSTONE`；不得因为重建 Projection 复活。
4. 旧 `short/mid/long`、Preference/Knowledge/Fact 通过
   `VNEXT_GLOSSARY.md` 的兼容映射解释，不能直接改名后宣称完成。

## Apply、兼容读取与回滚（S5-06 执行）

S5-06 才能在审核 dry-run 报告后增加 apply：

1. 固定输入 hash、数据库快照/备份和环境 manifest；
2. 先写 vNext Authority/Envelope 和迁移 checkpoint，再按版本构建
   Projection Outbox；
3. 每批校验 count/hash/tenant/scope/evidence，失败批次进入 REVIEW；
4. 旧读路径保持兼容窗口，Authority 单写；
5. 出现校验不一致时停止批次，使用兼容读取和 checkpoint 回滚，不直接删除
   原表或新 Authority；
6. Authority 校验通过后才能重建 Vector/BM25/Cache，使用新索引别名和回滚窗口。

回滚只撤销本次迁移产生的 Authority/Projection 记录或切换读别名，不回滚
用户已经正确提交的旧 Authority 事实；Forget Tombstone 永远优先于旧 UPSERT。
