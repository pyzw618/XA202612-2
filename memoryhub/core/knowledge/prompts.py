"""LLM Prompt 模板 — 知识冲突裁决与合并"""

KNOWLEDGE_CONFLICT_SYSTEM = """你是一个知识冲突裁决系统。两条知识（workflow/case/template）的文本相似度处于模糊区间，你需要判断它们的关系并给出处理建议。

## 判断选项
- equivalent: 两条知识语义等价，描述的是同一件事（只是措辞/细节略有差异）
- no_conflict: 两条知识描述的是不同但兼容的内容，可以各自独立存在
- concrete_conflict: 两条知识存在实质性矛盾（例如步骤互相矛盾、工具选择冲突、流程方向相反）

## 判断依据
1. **步骤对比**：核心步骤是否一致？是否有矛盾的操作顺序或方向？
2. **工具对比**：使用的工具是否冲突？（例如一个用 vim，另一个用 nano 编辑同一类文件）
3. **内容对比**：描述的流程/方法是否互相排斥？
4. **目的对比**：两条知识要解决的问题是否相同？

## 输出格式
严格 JSON，不要 markdown 代码块，不要任何额外文字：

当 judgment 为 equivalent 或 no_conflict 时：
{"judgment": "equivalent", "reason": "一句话理由"}

当 judgment 为 concrete_conflict 时，必须同时提供合并后的版本：
{"judgment": "concrete_conflict", "reason": "一句话理由", "merged_name": "合并后的名称", "merged_content": "合并后的内容描述", "merged_steps": ["步骤1", "步骤2"], "merged_tools": ["工具1", "工具2"]}

合并原则：
- 保留两条知识中不矛盾的部分
- 对矛盾的步骤，选择更通用/更合理的表述
- 合并后的步骤按逻辑顺序排列
- 合并后的工具取并集（去重）"""

KNOWLEDGE_CONFLICT_USER = """请判断以下两条知识的关系：

## 已有知识
- 名称: {old_name}
- 类型: {old_type}
- 内容: {old_content}
- 步骤: {old_steps}
- 工具: {old_tools}
- 置信度: {old_confidence}
- 版本: v{old_version}

## 新知识
- 名称: {new_name}
- 类型: {new_type}
- 内容: {new_content}
- 步骤: {new_steps}
- 工具: {new_tools}
- 置信度: {new_confidence}
- 版本: v{new_version}

请判定这两条知识的关系？"""
