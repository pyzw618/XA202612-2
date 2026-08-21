# EVT / PRE 专项验收测试结果记录

对应 `docs/tests/0811功能性测试/TEST_PLAN.md` 6.2 事件写入链路(EVT-01~08)与 6.3 偏好记忆(PRE-01~07),实现为 `tests/test_evt_acceptance.py` 与 `tests/test_pre_acceptance.py`。

## 执行结果

- 运行命令:`pytest tests/test_evt_acceptance.py tests/test_pre_acceptance.py -q`
- 结果:**43 passed**,0 failed,0 skipped(2026-08-11 全量复跑通过)
- 全量回归:`pytest tests/ -q` → **686 passed,2 skipped**
- 覆盖:EVT 8 项 19 用例 + PRE 7 项 24 用例,全部通过

### EVT-01~08(19 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| EVT-01 | 4 | 通过 | 缺必填/非法枚举/未知顶层字段/1.1 tool_result 缺 tool_calls 均被 schema 拒绝 |
| EVT-02 | 2 | 通过 | 1.0 tool_result payload 可读;新写入强制升级 1.1 |
| EVT-03 | 4 | 通过 | 4 因子公式(0.30/0.30/0.20/0.20)正确;accepted/review/rejected 三段判定;新鲜度随时间衰减 |
| EVT-04 | 3 | 通过 | 重复 event_id+同 hash 幂等确认不重存;相同 source_hash(不同 event_id)不重复持久化;不同事件均接受 |
| EVT-05 | 2 | 通过 | REJECT 不入库;MASK 仅存脱敏副本 |
| EVT-06 | 1 | 通过 | 同一安全事件仅触发一次偏好/知识/事实抽取 |
| EVT-07 | 3 | 通过 | 抽取失败幂等入队、重试成功、任务缺失死信 |
| EVT-08 | 1 | 通过 | 批量混合事件 accepted/rejected/event_ids 一致,质量拒绝可半成功 |

### PRE-01~07(24 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| PRE-01 | 5 | 通过 | 规则抽取映射 FORMAT_PREF/SAFETY_PREF(含全局判定);LLM 正确映射全部 7 类 PreferenceType |
| PRE-02 | 4 | 通过 | LLM 结构化输出;故障/坏 JSON/无客户端均优雅降级不崩溃 |
| PRE-03 | 6 | 通过 | 无证据基线 explicit 0.8 / implicit 0.5;来源权重 USER_BEHAVIOR>TOOL_RESULT;时间衰减;OVERRIDE 扣分;新证据驱动置信度变化且 event_id 去重 |
| PRE-04 | 2 | 通过 | 连续更新旧版 archived、version+1、parent/root 正确;不同偏好各自 root |
| PRE-05 | 2 | 通过 | 无场景偏好时降级命中 is_global=true;检索同时命中全局与场景偏好 |
| PRE-06 | 3 | 通过 | 每次抽取生成 Evidence(event_id/weight/decision);JSON 可读;冲突消解后 decision 已标记 |
| PRE-07 | 2 | 通过 | repo 检索按 user 隔离;updater 跨用户互不干扰(版本/root 独立) |

## 修改内容

### 修复:核心实现(7 处)

1. **`memoryhub/core/ingestion/service.py` — EVT-04 幂等去重缺口(真实 Bug)**
   原实现只按 event_id 去重,**相同 source_hash 但不同 event_id 会重复入库并重复触发抽取**。新增 `EventRepository.get_by_source_hash()` 跨批次查重 + 批内 `pending_hashes` 去重。语义矩阵:同 id+同 hash → 幂等确认(accepted,不重存);同 id+异 hash → rejected(内容冲突);同 hash 异 id → 幂等确认(不重存)。
2. **`memoryhub/core/ingestion/quality.py` — EVT-03 三态判定不可达(真实 Bug)**
   `_score_validity` 有 0.6 固定基分,使最低可能得分 ≈0.5,而 `MIN_QUALITY_SCORE=0.2`,`REJECTED/REVIEW` 是死代码。移除基分改为逐项累加(文本 0.5/event_type 0.3/payload 或 scene 0.2),新增 `REVIEW_QUALITY_SCORE=0.5` 三段判定,并加硬拒规则:无 text 且无 payload → REJECTED(避免污染长期记忆)。
3. **`memoryhub/core/preference/confidence.py` — 增量更新被旧实现覆盖(真实 Bug)**
   `update_confidence` 重复定义两次,第二个旧空实现(`return self.calculate(...)`)覆盖了带 `new_event` 增量逻辑的新版,导致"新增证据"不生效。删除重复定义;`update_confidence(pref, new_event)` 现在先按 event_id 去重追加 Evidence 再全量重算。
4. **`memoryhub/storage/database.py` — PRE-05 全局兜底缺失(真实 Bug)**
   `PreferenceRepository.get_active(user_id, scene)` 用 SQL 严格过滤 `scope_scene == scene`,全局偏好(`"*"`)永远进不了候选。改为 `scene == 传入 或 "*"`。
5. **`memoryhub/adapter/service.py` — `_scope_matches` 通配符失效(真实 Bug)**
   `* != office` 被当成不匹配,全局偏好即使进了候选也被检索过滤掉。改为 scene/task_type 为 `"*"` 时视为通配,不再短路。
6. **`memoryhub/core/preference/extractor.py` — 硬编码置信度**
   `extract()` 末尾统一调用 `confidence_calculator.calculate(pref)` 基于完整证据链初始化,替代规则/LLM 路径硬编码的 0.95/1.0/0.75。
7. **`memoryhub/core/preference/updater.py` — 置信度未接入生产链路**
   `add()`(new/coexist/pending 分支)与 `update()`(OVERRIDE)接入 `confidence_calculator`;`update()` 经 `_merge_evidences`(按 event_id 去重)继承旧证据链后重算;`merge()` 同样合并证据链,不再取 `max()`。

### 测试实现(新增 2 文件)

- `tests/test_evt_acceptance.py`:EVT-01~08 共 19 用例。
- `tests/test_pre_acceptance.py`:PRE-01~07 共 24 用例;含 `_FakeLLM`(顺序响应/故障注入)覆盖 7 类映射与降级路径。

### 状态

- `tests/test_evt_acceptance.py`、`tests/test_pre_acceptance.py` 为未跟踪新增文件(尚未提交)。
- 与既有回归测试语义对齐:重复事件按幂等确认计数(`duplicate.accepted == 1`),同 id 异 hash 计 rejected,未破坏既有约定。
