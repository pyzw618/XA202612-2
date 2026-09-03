# Phase D（聚焦）实施记录：ToolPreferenceMiner 工具选择偏好挖掘

> 日期：2026-08-18
> 分支：`dev-remem`
> 依据：`docs/REFACTOR_PLAN_V2.md` §4.2.1（赛题要求 2：工具选择偏好提取）
> 验证环境：`mhub311` conda（Python 3.11.15）

## 1. 实施项（全部完成）

| 项 | 内容 | 关键文件 |
|---|---|---|
| **D1 ToolPreferenceMiner** | `core/preference/tool_miner.py`：从事件 tool_calls 确定性统计（无 LLM）——同 `(scene, task_type)` 内某工具使用次数 ≥ `min_frequency=3` 且成功率 ≥ `min_success_rate=0.7` 且为最常用 → 产出 `PreferenceMemory(TOOL_PREFERENCE)`；`confidence=min(0.95, 0.6+0.1*use+0.2*rate)` 可解释；evidence 绑定每次调用 | `core/preference/tool_miner.py`（新增） |
| **D2 接入流转** | `MemoryConsolidator.consolidate_tool_preferences`：从中期情景（Phase E）取事件 → miner.mine → `PreferenceUpdater.add` 写入长期偏好（去重/版本） | `core/lifecycle/memory_consolidator.py`、`scheduler.py`、`app.py`、`management_api.py` |
| **D3 API** | 无需改端点：`preference_type=tool_preference` 经 `GET /preferences` 自然可见 | — |

## 2. 验证结果

- 新增测试 `tests/test_tool_preference_miner.py`（5 个）：
  1. 高频成功 → 产出 TOOL_PREFERENCE（text/payload/confidence）；
  2. 低频（<3）→ 不产出；
  3. 低成功率（1/3<0.7）→ 不产出；
  4. 跨任务各自产出（互不串）；
  5. `consolidate_tool_preferences` 从 episodes 挖掘并写入长期偏好（幂等）。
- 关键测试集：**57 passed**（miner + tiers + preference + api_acceptance + data_flow + lifecycle）。
- 全量：**870 passed / 16 failed / 7 skipped / 28 errors**；**失败集与基线逐条一致 → 无新增回归**。

## 3. 已打通的能力

```text
事件（工具调用） → 短期缓冲 → 中期情景 → MemoryConsolidator
  → ToolPreferenceMiner.mine (统计: 频率+成功率+最常用)
  → PreferenceMemory(TOOL_PREFERENCE) → GET /preferences 可见
```

解决赛题要求(2)"工具选择偏好提取不精准"——`TOOL_PREFERENCE` 从"零确定性提取"变为"确定性规则产出"。

## 4. 后续（D 补全，另行排期）

- 源适配层（工具/行为/配置三适配器）、手动配置版本化；
- 偏好 LLM prompt 注入 tool_calls（LLM 路径也能直接产工具偏好）；
- `WORKFLOW_PREF` 从 WorkflowMiner 输出挖掘。
