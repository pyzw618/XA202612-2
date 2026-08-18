# Phase G 实施记录：NL 语义遗忘升级（LLM 意图解析 + 语义定位）

> 日期：2026-08-18
> 分支：`dev-remem`
> 依据：`docs/refactor/REFACTOR_PLAN_V2.md` §4.5.2（赛题要求 5：自然语言指令精准遗忘）
> 验证环境：`mhub311` conda（Python 3.11.15）

## 1. 实施项（全部完成）

| 项 | 内容 | 关键文件 |
|---|---|---|
| **G1 LLM 意图解析** | `MemoryForgetter.parse_intent` 接入 `StructuredLLMAdapter`（`core/memory/llm.py`）：对语义模式输出结构化意图（memory_type/target_topic/keywords/negate）；失败回退规则不抛出。**设计取舍：memory_type 以规则推断优先（可靠可复现），LLM 仅在规则关键词为空时补充关键词/主题**——避免云端 LLM 误分类破坏确定性定位 | `core/forget/forgetter.py` |
| **G2 语义定位** | `_locate_by_keywords` 增加 embedding 相似度定位（≥0.75 召回）；`embedding_client` 参数；无 embedding_client 时退回顾有子串匹配 | `core/forget/forgetter.py`、`adapter/api.py` |
| **G3 装配** | `_get_forgetter` 传 `embedding_client`（app.state.embedding_client） | `adapter/api.py` |

## 2. 验证结果

- 新增测试 `tests/test_forget_semantic.py`（5 个）：
  1. LLM 可用时解析意图（memory_type 规则优先 + 关键词）；
  2. LLM 失败回退规则不抛异常；
  3. 规则关键词空时 LLM 补充；
  4. 精确 ID/scope 跳过 LLM；
  5. 语义定位（embedding 相似召回）+ 无 embedding 退回顾有子串行为。
- **过程中定位并修复了一个真回归**：`test_knowledge_filter_and_forget_preview_do_not_mutate`——我在 `parse_intent` 里让 LLM 覆盖 memory_type，云端 LLM 把 "forget weekly template" 误判为 preference，导致 preview 定位失效。改为**规则 memory_type 优先 + LLM 仅补充关键词**后恢复确定性，失败集回到基线。
- 关键测试：**16 passed**（forget_semantic + competition preview + forget_acceptance）。
- 全量：**875 passed / 16 failed / 7 skipped / 28 errors**；**失败集与基线逐条一致 → 无新增回归**。

## 3. 已打通的能力

```text
自然语言指令 → parse_intent（规则 memory_type + LLM 补充关键词）
  → locate（关键词 ∪ embedding 语义相似 ≥0.75）
  → delete（经 MemoryWriteService 软删，同步 lineage/outbox/索引）
```

解决赛题要求(5)"自然语言指令驱动的精准遗忘"——从纯规则子串升级为"规则 + LLM 语义解析 + 向量语义定位"三合一，同时保持确定性回退。

## 4. 后续（另行排期）

- forget 用户规则（user_rules 增 forget 类）；
- 遗忘精准度量化评测（与 Phase F 衔接）；
- 与记忆分层（Phase E）联动：按 level 精准遗忘（short/mid/long 范围）。
