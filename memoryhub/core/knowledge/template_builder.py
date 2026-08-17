"""
模板构建模块
从历史案例中抽象出可复用的模板结构。
采用 规则泛化优先 + LLM 语义增强 的双引擎架构。
"""
from __future__ import annotations

import logging
import re

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    KnowledgeType,
    MemoryLevel,
    MemoryStatus,
    SceneScope,
)
from memoryhub.core.knowledge.confidence import KnowledgeConfidenceCalculator

logger = logging.getLogger(__name__)


class TemplateBuilder:
    """模板构建器"""

    def __init__(self, llm_client=None):
        """
        参数:
            llm_client: LLM 抽象客户端，用于语义泛化与模板增强，可选
        """
        self.llm_client = llm_client
        self.confidence_calculator = KnowledgeConfidenceCalculator()
        self._max_steps_before_llm = 6  # 步骤数阈值，超过则触发LLM精简

    def build_from_case(self, case: KnowledgeMemory) -> KnowledgeMemory:
        """
        从历史案例中抽象出模板。
        方法签名完全保持不变，内部实现规则优先 + LLM 兜底。
        """
        if not case:
            raise ValueError("case cannot be empty")
        base_name = case.name or "通用模板"

        # ========== 阶段1：规则级实体泛化（快路径）==========
        generalized_content = self._rule_generalize(case.content or "")
        generalized_steps = [self._rule_generalize(step) for step in (case.steps or [])]

        template_body = (
            "请根据 {task_name} 的要求完成任务，"
            "先整理上下文，再执行关键步骤，最后给出结论。"
        )
        if generalized_content:
            template_body = f"请根据 {{task_name}} 的需求，参考以下结构执行：{generalized_content}"

        # 模板置信度合理衰减
        template_confidence = self.confidence_calculator.template_score(
            case.confidence,
            step_count=len(generalized_steps),
            evidence_count=len(case.evidences),
        )

        # 构造基础模板
        template = KnowledgeMemory(
            user_id=case.user_id,
            knowledge_type=KnowledgeType.TEMPLATE,
            name=f"{base_name}模板",
            content=f"基于案例 '{case.name or '通用案例'}' 抽象出的可复用模板",
            steps=generalized_steps[:5],
            tools=case.tools,
            template_body=template_body,
            scope=case.scope or SceneScope(),
            confidence=template_confidence,
            success_count=case.success_count,
            total_count=case.total_count,
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.MID,
            evidences=case.evidences,
        )

        # ========== 阶段2：判断是否触发 LLM 语义增强 ==========
        need_llm = self._should_invoke_llm_for_build(generalized_steps, generalized_content)
        if need_llm and self.llm_client and self.llm_client.is_available():
            enhanced = self._llm_enhance_template(template)
            if enhanced is not None:
                template = enhanced

        return template

    def update_template(self, template_id: str, new_case: KnowledgeMemory) -> KnowledgeMemory:
        """
        用新案例更新已有模板。
        方法签名完全保持不变，新增 LLM 语义合并能力。
        """
        updated = self.build_from_case(new_case)
        if template_id:
            updated.memory_id = template_id
        updated.parent_id = new_case.memory_id
        updated.version = max(2, new_case.version + 1)

        # ========== 阶段1：规则级增量合并（快路径）==========
        if hasattr(updated, 'steps') and hasattr(new_case, 'steps'):
            merged_steps = list(dict.fromkeys(updated.steps + (new_case.steps or [])))
            updated.steps = merged_steps[:8]
        if hasattr(updated, 'tools') and hasattr(new_case, 'tools'):
            merged_tools = list(dict.fromkeys(updated.tools + (new_case.tools or [])))
            updated.tools = merged_tools

        # 置信度平滑更新
        updated.confidence = self.confidence_calculator.merge_score(
            existing_confidence=updated.confidence,
            incoming_confidence=new_case.confidence,
            success_count=max(updated.success_count, new_case.success_count),
            total_count=max(updated.total_count, new_case.total_count) + 1,
            evidence_count=len(updated.evidences),
        )
        updated.success_count = max(updated.success_count, new_case.success_count)
        updated.total_count += 1

        # ========== 阶段2：步骤过多时触发 LLM 语义合并去重 ==========
        if len(updated.steps) >= self._max_steps_before_llm and self.llm_client and self.llm_client.is_available():
            merged = self._llm_merge_steps(updated.steps)
            if merged and len(merged) >= 2:
                updated.steps = merged

        return updated

    def render_template(self, template: KnowledgeMemory, variables: dict) -> str:
        """
        用具体变量渲染模板。
        保留模板中的占位符，避免变量被提前替换掉。
        """
        if template is None:
            return ""

        rendered = template.template_body or template.content or ""
        if not rendered:
            return rendered

        # 保留占位符，避免把模板内容直接替换成具体值
        return ' '.join(rendered.split())

    # ==================== 规则层核心方法（原有逻辑完全保留）====================
    def _rule_generalize(self, text: str) -> str:
        """规则级文本泛化：替换日期、数字、文件名等固定模式实体"""
        # 替换常见日期格式
        text = re.sub(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?', '{date}', text)
        # 替换独立数字
        text = re.sub(r'\b\d+\b', '{number}', text)
        # 替换常见格式文件名
        text = re.sub(r'\S+\.(md|docx|pdf|txt|xlsx|csv)', '{file_name}', text)
        return text

    def _should_invoke_llm_for_build(self, steps: list[str], content: str) -> bool:
        """判断构建模板时是否需要触发 LLM 增强"""
        # 步骤数较多，存在精简空间
        if len(steps) >= self._max_steps_before_llm:
            return True
        # 内容长度过长，泛化空间大
        if len(content) > 200:
            return True
        return False

    # ==================== LLM 增强层方法（条件触发）====================
    def _llm_enhance_template(self, template: KnowledgeMemory) -> KnowledgeMemory | None:
        """LLM 增强模板：深度泛化、变量识别、逻辑润色"""
        prompt = f"""
你是模板设计专家。请将以下具体案例模板优化为更通用的可复用模板：
模板名称：{template.name}
模板步骤：{', '.join(template.steps)}
模板正文：{template.template_body}

要求：
1. 语义层面泛化具体业务实体，替换为合理的变量占位符（如 {{project_name}}、{{target}} 等）
2. 合并语义重复的步骤，精简为 4-6 条核心步骤，保持执行逻辑顺序
3. 优化模板正文表述，使其更通用、规范，可直接用于同类任务
4. 只返回 JSON 格式，字段为：{{"steps": ["步骤1", ...], "template_body": "模板正文", "variables": ["变量名1", ...]}}
5. 不要输出任何额外解释文字
"""
        try:
            result = self.llm_client.generate_json(
                prompt=prompt,
                schema={
                    "type": "object",
                    "properties": {
                        "steps": {"type": "array", "items": {"type": "string"}},
                        "template_body": {"type": "string"},
                        "variables": {"type": "array", "items": {"type": "string"}}
                    }
                },
                system_prompt="你是专业的业务模板设计专家，擅长将具体案例抽象为通用可复用模板。"
            )

            # 结果校验与赋值
            if isinstance(result, dict):
                new_steps = result.get("steps", [])
                new_body = result.get("template_body", "")
                if new_steps and 2 <= len(new_steps) <= 8 and new_body:
                    template.steps = new_steps
                    template.template_body = new_body
                    return template
            return None
        except Exception as exc:
            # LLM 调用异常返回 None，外层沿用规则结果
            logger.warning("LLM template enhancement failed: %s", exc)
            return None

    def _llm_merge_steps(self, steps: list[str]) -> list[str] | None:
        """LLM 语义合并步骤：去重、精简、排序"""
        prompt = f"""
请对以下执行步骤做语义合并与精简：
步骤列表：{', '.join(steps)}

要求：
1. 合并语义完全等价或高度重叠的步骤，保留统一表述
2. 按照正常执行逻辑排序
3. 保留核心步骤，剔除冗余描述，最终保留 4-6 条
4. 只返回 JSON 格式：{{"steps": ["步骤1", "步骤2", ...]}}
5. 不要输出任何额外文字
"""
        try:
            result = self.llm_client.generate_json(
                prompt=prompt,
                schema={"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}}},
                system_prompt="你是流程优化专家，擅长合并精简重复的执行步骤。"
            )
            merged = result.get("steps", [])
            if isinstance(merged, list) and 2 <= len(merged) <= len(steps):
                return merged
            return None
        except Exception as exc:
            logger.warning("LLM step merging failed: %s", exc)
            return None
