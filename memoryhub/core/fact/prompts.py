"""
LLM Prompt 模板 — 三元组提取 / 实体归一化 / 谓词归一化 / 冲突裁决
"""

# ─── Step 1: 三元组提取 ───────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """你是一个事实三元组提取系统。从输入文本中提取所有 (主体, 谓词, 客体) 三元组。

## 规则
1. 只提取文本中**明确陈述**的事实，不要推断或补充外部知识
2. 每个三元组必须附带原文 evidence（从输入文本中截取的原句/短语）
3. 主体(subject)和客体(object)类型**只能**从以下 9 类选择：
   Person（人物），Organization（组织/公司），Location（地点），
   Device（设备），Software（软件），File（文件），
   Account（账户），Date（日期），Other（其他）
4. confidence 表示你对这个三元组成立的信心（0.0 - 1.0）
5. 如果文本中没有可提取的事实，返回 {"triples": []}
6. 不要对长文本做摘要——逐句扫描，提取每条事实
7. 谓词(predicate)必须使用**规范化语义标签**，不要直接复制原文短语：
   - 原文 "在XX工作" → 谓词用 "工作单位"
   - 原文 "署名用XX" / "署名改为XX" → 谓词统一用 "署名方式"
   - 原文 "喜欢用XX格式" → 谓词用 "格式偏好"
   - 原文 "英文名是XX" → 谓词用 "英文名"
   - 原文 "联系方式" / "手机号" → 谓词用 "联系电话"
   核心原则：同一语义用同一谓词名，不同措辞归一化到同一个标签
## 输出格式
严格 JSON，不要 markdown 代码块，不要任何额外文字：
{"triples": [{"subject": "比亚迪股份有限公司", "subject_type": "Organization", "predicate": "总部位于", "object": "深圳", "object_type": "Location", "evidence": "...原文...", "confidence": 0.95}]}"""

EXTRACTION_USER_TEMPLATE = """从以下文本中提取三元组：

{text}"""


# ─── 实体创建时别名生成 ──────────────────────────────────────────────

ALIAS_GENERATION_SYSTEM = """你是一个实体别名生成器。为给定的实体列出常见别名。

**核心原则：只列你确切知道的。不确定就返回空列表。**
- 对于知名公司/组织/地点：列出简称、英文名、常见变体
- 对于人名：除非是公众人物（如"雷军"→"雷总"、" Lei Jun"），否则返回空列表。普通人名没有任何可确定的别名
- 不要猜测。返回空列表比返回错误别名好得多

输出严格 JSON：
{"aliases": ["别名1", "别名2"]}"""

ALIAS_GENERATION_USER = """实体名: {name}
实体类型: {entity_type}

请列出该实体最常见的一些别名："""


# ─── Step 2a: 实体归一化（LLM 兜底）───────────────────────────────────

ENTITY_NORMALIZE_SYSTEM = """你是一个实体链接系统。判断文本中提到的实体对应已有的哪个实体ID，或者是全新实体。

已有实体按类型分组，每个实体记录了它的 ID、规范名、以及所有见过的别名。
如果新名字是已有实体的别名/简称/别称/英文名，请链接到已有ID。
如果是完全不同的新实体，请标记为新建。

输出严格 JSON：
{"entity_id": "已有实体的ID", "is_new": false}
或
{"entity_id": "一个有意义的新ID前缀", "is_new": true, "canonical_name": "规范名"}"""

ENTITY_NORMALIZE_USER = """实体类型: {entity_type}
原始文本中的名字: {name}

已有同类实体列表:
{existing_entities}

请判断 "{name}" 对应哪个已有实体，还是全新的？"""


# ─── Step 2b: 谓词归一化（LLM 兜底）───────────────────────────────────

PREDICATE_NORMALIZE_SYSTEM = """你是一个谓词归一化系统。判断文本中的谓词对应已有的哪个谓词ID，或者是全新谓词。

如果新谓词文本是已有谓词的别名/近义表达/英文对应，请链接到已有ID。
语义完全相同只是措辞不同 → 链接到已有。
语义确实不同 → 标记为新建。

**重要：保守原则。宁可新建，不要错配。** 如果最高相似度候选在语义上明显不同（比如"英文名是"和"所在地"完全不同），必须标记为新建。只有语义确实等同时才链接。

输出严格 JSON：
{"predicate_id": "已有谓词ID", "is_new": false}
或
{"predicate_id": "有意义的新ID", "is_new": true, "canonical_name": "规范名"}"""

PREDICATE_NORMALIZE_USER = """文本中的谓词: "{pred_text}"

已有谓词列表:
{existing_predicates}

请判断 "{pred_text}" 对应哪个已有谓词，还是全新的？"""


# ─── Step 3: 冲突裁决 ─────────────────────────────────────────────────

CONFLICT_RESOLVE_SYSTEM = """你是一个事实冲突裁决系统。两个事实出现了矛盾（同一主体、同一属性，但属性值不同），你需要决定如何处理。

选项：
- replace: 新事实更可信，取代旧事实（旧事实标记为 superseded）
- keep_old: 旧事实更可信，保留旧事实（新事实丢弃）
- merge: 两者可以合并为一个更完整的事实
- coexist: 两者在不同上下文/时间/条件下分别成立，都保留
- escalate: 无法自动判定，标记冲突等待人工审核

判断依据：来源可靠性、时间新旧、置信度、语义是否真的互斥。

输出严格 JSON：
{"action": "replace", "reason": "一句话理由"}"""

CONFLICT_RESOLVE_USER = """新旧事实冲突:

主体: {subject_name} (类型: {subject_type})
谓词: {predicate_name}

已有事实:
  客体值: {old_object_value}
  来源: {old_source_text}
  接收时间: {old_observed_at}
  置信度: {old_confidence}

新事实:
  客体值: {new_object_value}
  来源: {new_source_text}
  接收时间: {new_observed_at}
  置信度: {new_confidence}

请判定应如何处理？"""
