# LIF / PER / API 专项验收测试结果记录

对应 `docs/tests/0811功能性测试/TEST_PLAN.md` 6.9 生命周期(LIF-01~03)、6.10 持久化与恢复(PER-01~04)与第 7 章 REST API 契约(API),实现为 `tests/test_lif_acceptance.py`、`tests/test_per_acceptance.py` 与 `tests/test_api_acceptance.py`。

## 执行结果

- 运行命令:`pytest tests/test_lif_acceptance.py tests/test_per_acceptance.py tests/test_api_acceptance.py -q`
- 结果:**30 passed**,0 failed,0 skipped(2026-08-11)
- 全量回归:`pytest tests/ -q --ignore=tests/test_sync_service.py` → **733 passed,2 skipped**(较上一基线 703 新增 30 用例;sync 服务测试隔离复跑 11 passed)
- 变更文件 ruff check:passed

### LIF-01~03(6 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| LIF-01 | 1 | 通过 | classify 按 EventQuality.score 分档:≥0.8→LONG、≥0.5→MID、<0.5→SHORT;0.49/0.0 边界正确 |
| LIF-02 | 3 | 通过 | 短→中:出现≥2 且 quality_score≥0.4(次数不足/质量不足/边界均为 False/True 正确);中→长:出现≥5 且 confidence≥0.7 且存在≥3 天(4 次/低置信/不足 3 天均拒绝);promote 单级提升 short→mid、mid→long,long 不再提升,变更落库 |
| LIF-03 | 2 | 通过 | 低健康度记忆 expire 后 status=archived 并退出 active 列表;run_lifecycle_check 一次完成归档+升级并返回 `{promoted, expired, kept}` 统计 |

### PER-01~04(11 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| PER-01 | 4 | 通过 | 建库后 events/preferences/knowledge/knowledge_versions/conflicts/forget_history/extraction_tasks 共 7 张业务表齐备;preferences 扩展列(health_score/stability/last_accessed_at/access_count_30d 等)、knowledge 扩展列(index/pending_index)、events 契约列均与 docs/spec/INTERFACE.md 6.1 对齐 |
| PER-02 | 3 | 通过 | 写入→关闭→重建 Database→查询,偏好/知识/冲突解决记录均不丢;证据链在新 EvidenceStore 实例可加载(模拟进程重启) |
| PER-03 | 2 | 通过 | 证据链 JSONL 每 memory_id 一个文件,追加/批量写入行数正确、每行可独立 parse 为 Evidence;delete 物理删除文件,二次删除返回 False,list_all 返回全部记忆 ID |
| PER-04 | 2 | 通过 | VectorStore save 后 init_index 从磁盘加载,id_map/reverse_map 与落盘一致、可检索;删除后落盘 reload 不再返回已删向量(size 正确) |

### API(13 用例)

| 分组 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| 健康/事件 | 2 | 通过 | GET /health→200 healthy;POST /events→200 accepted=1,事件写入后可 /search 与 /context 命中 |
| 偏好/知识管理 | 2 | 通过 | GET /preferences[/{id}[/versions]] 支持 scene/status 过滤;GET /knowledge[/{id}] 支持 type 过滤 |
| 冲突/反馈 | 2 | 通过 | GET /conflicts→200;POST /{id}/resolve 对缺失冲突→404;POST /feedback confirm/update/reject 三种动作生效(confirm 计数、update 改内容+版本、reject 移出 active 与检索) |
| 手工写入/遗忘 | 2 | 通过 | POST /memories/preference、/memories/knowledge→200 返回 memory_id;POST /forget deleted_count=1 后移出 active 列表,GET /forget/history 含审计记录 |
| 事实管理 | 1 | 通过 | GET /facts、/facts/conflicts、/facts/{id}、/facts/{id}/evidence、DELETE /facts/{id} 全链路;软删除后 active 列表剔除、详情 status=deleted |
| 抽取任务/评测 | 2 | 通过 | GET /extraction/tasks[/metrics]、POST /run、POST /{task_id}/retry(缺失→404);POST /evaluate/{task_name}、GET /evaluate/reports |
| 错误码 | 2 | 通过 | 非法请求→422(quality 越界事件、非 int top_k、非法 action);不存在资源→404(偏好/知识/事实/反馈) |

## 修改内容

### 修复:生命周期升级阈值与文档不一致(真实 Bug,LIF-02)

`LifecycleManager.PROMOTE_THRESHOLDS` 原实现为单一阈值(`access_count≥5 且 confidence≥0.5 且 stability≥0.6`),与 docs/tests/0811功能性测试/TEST_PLAN 6.9 LIF-02 及 docs/design/PROJECT_ANALYSIS.md 生命周期设计(`short_to_mid`/`mid_to_long` 两档)不符。修改 `memoryhub/core/lifecycle/manager.py`:

1. 阈值改为两档:`{"short_to_mid": {min_occurrences:2, min_quality_score:0.4}, "mid_to_long": {min_occurrences:5, min_confidence:0.7, min_days:3}}`;`should_promote` 按记忆当前层级选择对应档位,LONG 不再提升;存在时长由 `created_at` 计算。
2. `promote` 重构为按 `_level(memory)` 单级提升映射。
3. **`run_lifecycle_check` 从不触发升级(真实 Bug)**:原实现调用 `should_promote(memory)` 未传 `access_count`,恒为 0 → 升级永不发生。现改为透传 `memory.access_count_30d`。

### 修复:乱码日志与文档字符串

- `memoryhub/core/lifecycle/manager.py` 原 `logger.warning(f"????????: {e}")` 中文损坏为 `???????`(文件曾以 ASCII 保存),恢复为正常中文并用 %-style 占位。
- `memoryhub/storage/database.py` 三处方法 docstring 损坏(`get_by_scope`/`search_by_name`/`increment_usage` 的 `???...???`)恢复为中文描述(仅注释,无逻辑变更)。

### 测试实现(新增 3 文件)

- `tests/test_lif_acceptance.py`:LIF-01~03 共 6 用例;直接驱动 `LifecycleManager`(真实 repo + 注入健康度),含 `run_lifecycle_check` 端到端。
- `tests/test_per_acceptance.py`:PER-01~04 共 11 用例;PRAGMA 校验真实 SQLite 表/列,重建 Database/EvidenceStore/VectorStore 验证持久化与恢复。
- `tests/test_api_acceptance.py`:第 7 章共 13 用例;TestClient + 隔离存储路径(避免 `data/` 本地 FAISS 索引污染),覆盖全部端点与稳定错误码(200/404/422);user-rules CRUD 由 SEC-15~17 既有测试覆盖,不重复。

### 状态

- 修改文件:`memoryhub/core/lifecycle/manager.py`、`memoryhub/storage/database.py`(未提交)。
- 新增测试文件:`tests/test_lif_acceptance.py`、`tests/test_per_acceptance.py`、`tests/test_api_acceptance.py`(未跟踪)。
- 与既有回归语义对齐:`tests/test_data_flow_regressions.py::test_lifecycle_and_auto_forget_use_the_correct_repository`、`tests/test_knowledge/test_knowledge_data_flow.py::test_index_text_and_lifecycle_archive_cover_all_knowledge_fields`、`tests/test_memory_api.py` 全部继续通过,未破坏仓储接线与归档/检索约定。
- 备注:TEST_PLAN PER-01 描述为"8 张业务表",实测当前实现为 7 张(events/preferences/knowledge/knowledge_versions/conflicts/forget_history/extraction_tasks),已在用例中按实际 7 张断言并在文档说明。
