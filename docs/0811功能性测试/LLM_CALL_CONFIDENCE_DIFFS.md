# 偏好 / 知识 / 事实提取:LLM 调用与置信度计算差异

记录三种记忆（偏好 Preference、知识 Knowledge、事实 Fact）在调用 LLM 抽取以及置信度计算方式上的差异，作为功能测试的对照说明。

## 一、LLM 调用方式差异

| 维度 | 事实 `TripleExtractor` | 偏好 `PreferenceExtractor` | 知识 `KnowledgeExtractor` |
|------|------|------|------|
| 文件 | `memoryhub/core/fact/extractor.py` | `memoryhub/core/preference/extractor.py` | `memoryhub/core/knowledge/extractor.py` |
| 调用接口 | 原生 OpenAI 兼容 `client.chat.completions.create()`（`build_chat_client` 封装，默认 DeepSeek） | 上层注入的 `llm_client.generate()` | 上层注入的 `llm_client.generate()` / `generate_json()` |
| 调用模式 | 单次调用，`temperature=0.0`、`max_tokens=4096` | **三代 GVR 循环**：最多 3 轮生成 + 校验反馈迭代重写 | 多次单次调用：goal 摘要 / steps 提取 / trajectory 富化 三类独立调用 |
| Prompt 风格 | 模板 `EXTRACTION_SYSTEM_PROMPT` + 用户文本占位 | 长 system prompt 要求严格 JSON，含 GVR 质量校验与拒绝重写；处理 markdown code fence | 中文短指令（"你是任务分析专家"等），JSON 结构化输出 |
| 降级/失败策略 | 降级：LLM 失败或未返回三元组 → `_rule_extract()` 规则兜底（两者都失败才上报 `last_error`） | 规则优先（`_rule_extract`），LLM 仅用于隐式偏好（quality≥0.6 且规则无命中）；无 LLM 返回空 | 规则挖掘优先，LLM 仅在规则不足时补充；LLM 失败**抛 `KnowledgeExtractionError`**，不降级 |
| 关键引用 | `extractor.py:68` create 调用、`extractor.py:82` 规则回退 | `extractor.py:170` generate、`extractor.py:163` 循环 | `extractor.py:493/536/556` 三类调用、`extractor.py:507` 抛错 |

要点：

1. **事实**是"单发一锤定音 + 规则兜底"，靠确定性规则保证无 API key 时客观事实仍可写入（FCT-01）。
2. **偏好**最复杂：GVR 校验循环会拒绝过度具体化的输出并要求模型重写，最多迭代 3 次。
3. **知识**把任务拆成 goal/steps/enrichment 三个独立 LLM 调用；失败策略是抛错交给上层重试队列，而不是静默降级。
4. 事实模块自行封装 LLM 客户端（DeepSeek 直连），偏好/知识复用上层统一注入的 `llm_client`。

## 二、置信度计算方式差异

| 维度 | 事实 | 偏好 | 知识 |
|------|------|------|------|
| 是否有计算器 | **无** | `ConfidenceCalculator`（preference/confidence.py:28） | `KnowledgeConfidenceCalculator`（knowledge/confidence.py:31） |
| 来源 | 不计算，直接取值：① LLM 在 JSON 输出中**自报**的 `confidence`；② 规则降级固定 `0.7`；③ admission 分类硬编码 `0.95/0.9/0.85/0.7` | 确定性公式 + Sigmoid 平滑 | 加权多因子评分 + 最弱链惩罚 |
| 公式 | — | `raw = f_source×f_time×f_consistency×(1+0.15×f_count)`；`final = Sigmoid(3×(raw-0.5)) - OVERRIDE 惩罚` | `score = Σ(权重×因子) × (0.82+0.18×min(因子))`，上限 0.97 |
| 权重/因子 | — | 证据数 / 来源类型 / 时间衰减(半衰期14天) / 一致性 | 质量 0.28、完成度 0.20、结构 0.20、证据 0.14、结果 0.10、一致性 0.08 |
| 无证据时 | — | 按抽取来源给基线：explicit=0.8 / implicit=0.5 | — |
| 增量/变体 | — | `update_confidence()` 追加证据后重算 | `merge_score`（新旧合并+成功率+支持度）、`template_score`（案例置信度+泛化+证据） |
| 关键引用 | `extractor.py:122` 固定 0.7、`admission.py:48-82` 硬编码 | `preference/confidence.py:58-69` | `knowledge/confidence.py:34-76` |

要点：

1. **偏好、知识**置信度由系统用证据/因子推算；**事实**不做推算，置信度是模型自报或常量，最弱。
2. **事实的 admission 置信度语义不同**：0.95/0.9 等其实表示"归类判断信心"（这是偏好表达 / 假设表达 / 临时事实的判断），并非事实成立信心。
3. 偏好仅一套 sigmoid 公式；知识有三套（score/merge/template）覆盖抽取、演进合并、模板生成三类场景。

## 三、附注

- 测试入口：`tests/test_fact/test_extractor.py`（FCT 降级）、`tests/test_evt_acceptance.py` / `tests/test_preference_functionality.py`（偏好 GVR 与置信度）、`tests/test_knowledge/`（知识置信度与错误处理）。
- 功能测试详见本目录 `FCT_ACCEPTANCE_RESULT.md`、`KNW_ACCEPTANCE_RESULT.md`、`EVT_PRE_ACCEPTANCE_RESULT.md`。
