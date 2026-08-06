"""
知识抽取模块
从任务执行轨迹中提取工作流知识、历史案例、可复用模板。
采用 规则结构化提取优先 + LLM 语义兜底 的双引擎架构。
"""
from __future__ import annotations

import math
import re
from datetime import datetime

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    SceneScope,
    SourceType,
)
from memoryhub.core.knowledge.template_builder import TemplateBuilder


class KnowledgeExtractor:
    """
    知识抽取器
    使用方式:
        extractor = KnowledgeExtractor(llm_client=llm)
        knowledge = extractor.extract_from_trajectory(events)
    """
    def __init__(self, llm_client=None, template_builder: TemplateBuilder | None = None):
        """
        参数:
            llm_client: LLM 抽象客户端，用于语义辅助抽取，可选
        """
        self.llm_client = llm_client
        self.template_builder = template_builder or TemplateBuilder(llm_client=llm_client)
        # LLM 触发阈值
        self._min_steps_rule = 2  # 规则提取步骤少于该值触发LLM

    def extract_from_trajectory(self, events: list[MemoryEvent | dict]) -> list[KnowledgeMemory]:
        """
        从任务执行轨迹中抽取知识。
        支持两种输入：
        1. 旧版结构化事件列表（含 content/quality_score）
        2. 新版接入层输出（MemoryEvent / 原始字典）
        """
        if not events:
            return []

        normalized_events = [self._coerce_event(event) for event in events]
        normalized_events = [event for event in normalized_events if event is not None]
        if not normalized_events:
            return []

        valid_events = [e for e in normalized_events if self._event_quality_score(e) >= 0.3]
        if not valid_events:
            return []

        knowledge_items: list[KnowledgeMemory] = []
        workflow = self.extract_workflow(valid_events)
        if workflow is not None:
            knowledge_items.append(workflow)
        case = self.extract_case(valid_events)
        if case is not None:
            knowledge_items.append(case)
        template = self.extract_template(valid_events)
        if template is not None:
            knowledge_items.append(template)
        return knowledge_items

    def extract_template_instruction(self, event: MemoryEvent) -> KnowledgeMemory | None:
        """从用户明确给出的章节结构中形成模板，不要求前端提供模板对象。"""
        if event.source_type not in (SourceType.USER_BEHAVIOR, SourceType.MANUAL_CONFIG):
            return None
        text = event.text.strip()
        if "比赛方案" not in text or "部分" not in text:
            return None
        quoted = re.search(r"[“\"]([^”\"]+)[”\"]", text)
        if quoted is None:
            return None
        sections = [item.strip() for item in re.split(r"[、,，]", quoted.group(1)) if item.strip()]
        if len(sections) < 2:
            return None
        body = "\n\n".join(f"# {section}\n{{{{{index + 1}}}}}" for index, section in enumerate(sections))
        return KnowledgeMemory(
            user_id=event.user_id,
            knowledge_type=KnowledgeType.TEMPLATE,
            name="比赛方案模板",
            content="根据用户明确指定的章节结构生成。",
            template_body=body,
            scope=SceneScope(scene="office", task_type="competition_proposal"),
            confidence=0.96,
            success_count=0,
            total_count=1,
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.LONG,
            evidences=self._build_evidences([event]),
        )

    def extract_workflow(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        """
        从事件序列中提取工作流知识。
        """
        if not events:
            return None
        steps = self._extract_steps(events)
        tools = self._extract_tool_chain(events)
        if not steps:
            return None

        first_event = events[0]
        goal = self._identify_task_goal(events)
        scope = SceneScope(
            scene=self._get_event_field(first_event, "scene", ""),
            task_type=self._get_event_field(first_event, "task_type", ""),
            app=self._get_event_field(first_event, "source", self._get_event_field(first_event, "source_type", "")),
        )

        # 多因子置信度计算：平均质量分 + 对数边际收益
        avg_quality = sum(self._event_quality_score(event) for event in events) / len(events)
        base_conf = 0.5 + 0.1 * math.log1p(len(steps)) + 0.05 * math.log1p(min(len(tools), 3))
        confidence = round(min(0.95, base_conf * avg_quality), 4)

        return KnowledgeMemory(
            user_id=self._get_event_field(first_event, "user_id", "default"),
            knowledge_type=KnowledgeType.WORKFLOW,
            name=f"{goal}工作流",
            content=f"围绕 '{goal}' 的标准执行流程",
            steps=steps,
            tools=tools,
            scope=scope,
            confidence=confidence,
            success_count=max(1, len(events)),
            total_count=max(1, len(events)),
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.MID,
            evidences=self._build_evidences(events),
        )

    def extract_case(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        """
        从事件序列中提取历史案例。
        """
        if not events:
            return None
        first_event = events[0]
        goal = self._identify_task_goal(events)
        steps = self._extract_steps(events)
        result = self._extract_result(events)

        # 结构化案例描述
        content = f"任务目标：「{goal}」；执行步骤：{', '.join(steps) if steps else '无'}；最终结果：{result or '未记录'}。"

        # 多因子置信度计算
        avg_quality = sum(self._event_quality_score(event) for event in events) / len(events)
        base_conf = 0.6 + 0.05 * math.log1p(min(len(steps), 5))
        confidence = round(min(0.95, base_conf * avg_quality), 4)

        return KnowledgeMemory(
            user_id=self._get_event_field(first_event, "user_id", "default"),
            knowledge_type=KnowledgeType.CASE,
            name=f"{goal}案例",
            content=content,
            steps=steps,
            tools=self._extract_tool_chain(events),
            scope=SceneScope(
                scene=self._get_event_field(first_event, "scene", ""),
                task_type=self._get_event_field(first_event, "task_type", ""),
                app=self._get_event_field(first_event, "source", self._get_event_field(first_event, "source_type", "")),
            ),
            confidence=confidence,
            success_count=max(1, len(events)),
            total_count=max(1, len(events)),
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.MID,
            evidences=self._build_evidences(events),
        )

    def extract_template(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        """
        从事件序列中提取可复用模板。
        """
        case = self.extract_case(events)
        if case is None:
            return None
        return self.template_builder.build_from_case(case)

    def _llm_available(self) -> bool:
        """兼容项目 BaseLLMClient 及轻量测试桩。"""
        if self.llm_client is None:
            return False
        checker = getattr(self.llm_client, "is_available", None)
        return bool(checker()) if callable(checker) else callable(getattr(self.llm_client, "generate", None))

    def _identify_task_goal(self, events: list[MemoryEvent | dict]) -> str:
        """识别任务目标：优先结构化字段，兜底LLM语义归纳"""
        for event in events:
            if self._get_event_type(event) == "task_trajectory":
                task_name = self._event_content(event).get("task_name")
                if task_name:
                    return str(task_name).strip()

        rule_goal = "任务"
        for event in events:
            if isinstance(event, MemoryEvent) and event.text:
                rule_goal = event.text.strip()
                break
            content = self._event_content(event)
            for key in ("result", "text"):
                value = content.get(key)
                if value:
                    rule_goal = str(value).strip()
                    break
            if rule_goal != "任务":
                break

        # 第三优先级：规则提取效果差，触发LLM语义归纳
        need_llm = (rule_goal == "任务") or len(rule_goal) > 50
        if need_llm and self._llm_available():
            llm_goal = self._llm_summarize_goal(events)
            if llm_goal:
                return llm_goal

        # 最终兜底：规则结果截断
        return rule_goal[:20] if len(rule_goal) > 20 else rule_goal

    def _extract_tool_chain(self, events: list[MemoryEvent | dict]) -> list[str]:
        """提取工具调用链：优先保留轨迹的完整时序，再补充零散调用"""
        tools: list[str] = []
        seen: set[str] = set()
        # 第一优先级：任务轨迹中的完整工具链（保证时序）
        for event in events:
            if self._get_event_type(event) == "task_trajectory":
                raw_tools = self._event_content(event).get("tools") or []
                if isinstance(raw_tools, list):
                    for tool_name in raw_tools:
                        value = str(tool_name).strip()
                        if value and value not in seen:
                            tools.append(value)
                            seen.add(value)
        # 第二优先级：零散工具调用事件补充
        for event in events:
            if isinstance(event, MemoryEvent):
                for call in event.tool_calls:
                    if call.tool_name not in seen:
                        tools.append(call.tool_name)
                        seen.add(call.tool_name)
            if self._get_event_type(event) == "tool_call":
                tool_name = self._event_content(event).get("tool_name", "").strip()
                if tool_name and tool_name not in seen:
                    tools.append(tool_name)
                    seen.add(tool_name)
        return tools

    def _extract_steps(self, events: list[MemoryEvent | dict]) -> list[str]:
        """提取执行步骤：规则结构化提取优先，LLM语义归纳兜底"""
        steps: list[str] = []
        seen: set[str] = set()
        # 规则主路径：从结构化 steps 字段提取
        for event in events:
            content = self._event_content(event)
            raw_steps = content.get("steps") or []
            if isinstance(raw_steps, list):
                for step in raw_steps:
                    value = self._normalize_step(str(step).strip())
                    if value and value not in seen and len(value) >= 2:
                        steps.append(value)
                        seen.add(value)
            if isinstance(event, MemoryEvent):
                step_labels = {
                    "file_search": "检索项目资料",
                    "calendar_query": "读取日程",
                    "report_writer": "生成报告",
                }
                for call in event.tool_calls:
                    value = step_labels.get(call.tool_name, f"调用 {call.tool_name}")
                    if value not in seen:
                        steps.append(value)
                        seen.add(value)

        # 规则提取不足，触发LLM从事件序列中归纳步骤
        if len(steps) < self._min_steps_rule and self._llm_available():
            llm_steps = self._llm_extract_steps(events)
            for step in llm_steps:
                value = self._normalize_step(step)
                if value and value not in seen and len(value) >= 2:
                    steps.append(value)
                    seen.add(value)

        return steps

    def _normalize_step(self, step: str) -> str:
        """步骤文本归一化：去除序号、多余空白与标点"""
        # 去除中文序号前缀
        step = re.sub(r'^\s*(第[一二三四五六七八九十\d]+[步、：:.]\s*)', '', step)
        # 去除数字序号前缀
        step = re.sub(r'^\s*\d+[.、\s]+', '', step)
        # 清理首尾标点与空白
        return step.strip(' 。，、：:.')

    def _extract_result(self, events: list[MemoryEvent | dict]) -> str:
        for event in reversed(events):
            if isinstance(event, MemoryEvent) and event.tool_calls:
                result = event.tool_calls[-1].result
                if result:
                    return str(result).strip()
            result = self._event_content(event).get("result")
            if result:
                return str(result).strip()
        return ""

    def _build_evidences(self, events: list[MemoryEvent | dict]) -> list[Evidence]:
        """构建证据链：按事件类型差异化权重，优化摘要信息密度"""
        evidences: list[Evidence] = []
        type_weight = {
            "task_trajectory": 0.95,
            "tool_call": 0.8,
            "user_feedback": 0.9,
            "user_behavior": 0.85,
            "manual_config": 0.9,
        }
        for event in events:
            content = self._event_content(event)
            event_type = self._get_event_type(event)
            summary = ""
            if event_type == "task_trajectory":
                summary = f"任务「{content.get('task_name', '未知')}」执行结果：{content.get('result', '未知')}".strip()
            elif event_type == "tool_call":
                summary = f"工具调用：{content.get('tool_name', '未知')}，状态：{content.get('status', '未知')}".strip()
            elif event_type == "user_feedback":
                summary = f"用户反馈：{content.get('text', '')}".strip()
            else:
                summary = str(content)[:100]

            weight = type_weight.get(event_type, 0.8)
            if summary:
                evidences.append(
                    Evidence(
                        event_id=self._get_event_field(event, "event_id", ""),
                        content=summary,
                        source_type=self._evidence_source_type(event),
                        timestamp=self._event_timestamp(event),
                        weight=weight,
                    )
                )
        return evidences

    # ==================== LLM 语义辅助方法（条件触发）====================
    def _llm_summarize_goal(self, events: list[MemoryEvent | dict]) -> str | None:
        """LLM 归纳任务目标：从事件序列中提炼核心任务主题"""
        event_summaries = []
        for event in events[:10]:
            event_summaries.append(f"{self._get_event_type(event)}: {str(self._event_content(event))[:80]}")
        prompt = f"""
请从以下任务执行事件中，用不超过10个字的简洁短语概括核心任务目标。
要求：
1. 只返回目标短语，不要任何解释、标点、前缀
2. 准确提炼任务核心，不要冗余描述
3. 例如：生成项目周报、排查代码bug

事件列表：
{chr(10).join(event_summaries)}
"""
        try:
            result = self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是任务分析专家，擅长从执行记录中提炼核心目标。"
            )
            goal = result.content.strip().strip('「」""\'\'。，')
            if goal and 2 <= len(goal) <= 20:
                return goal
            return None
        except Exception:
            return None

    def _llm_extract_steps(self, events: list[MemoryEvent | dict]) -> list[str]:
        """LLM 从事件序列中归纳执行步骤：解决无结构化steps字段的抽取问题"""
        event_summaries = []
        for event in events[:20]:
            content = self._event_content(event)
            event_type = self._get_event_type(event)
            if event_type == "tool_call":
                event_summaries.append(f"调用工具：{content.get('tool_name', '')}，输入：{content.get('input', '')[:50]}")
            elif event_type == "task_trajectory":
                event_summaries.append(f"任务：{content.get('task_name', '')}，结果：{content.get('result', '')[:50]}")
            else:
                event_summaries.append(str(content)[:60])

        prompt = f"""
请从以下任务执行事件中，按执行顺序归纳出 3-6 条核心执行步骤。
要求：
1. 每条步骤简洁清晰，不超过15字，动宾结构
2. 按实际执行先后顺序排列
3. 过滤失败、重试、调试类的异常步骤
4. 只返回 JSON 格式：{{"steps": ["步骤1", "步骤2", ...]}}
5. 不要输出任何额外解释文字

执行事件：
{chr(10).join(event_summaries)}
"""
        try:
            result = self.llm_client.generate_json(
                prompt=prompt,
                schema={"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}}},
                system_prompt="你是流程分析专家，擅长从操作记录中提炼标准执行步骤。"
            )
            steps = result.get("steps", [])
            if isinstance(steps, list) and 2 <= len(steps) <= 8:
                return [s.strip() for s in steps if s.strip()]
            return []
        except Exception:
            return []

    def _coerce_event(self, event: MemoryEvent | dict) -> MemoryEvent | dict | None:
        """兼容旧版事件对象与新版接入层输入。"""
        if isinstance(event, MemoryEvent):
            return event
        if isinstance(event, dict):
            try:
                return MemoryEvent.model_validate(event)
            except Exception:
                # 接入层原始载荷可能暂不完全符合 1.1 约束；保留原始字典，
                # 由后续兼容读取逻辑继续从 payload/steps/tools 中提取内容。
                return event
        return None

    def _get_event_type(self, event: MemoryEvent | dict) -> str:
        """统一返回事件类型字符串。"""
        if isinstance(event, MemoryEvent):
            event_type = getattr(event, "event_type", "")
            if isinstance(event_type, str) and event_type:
                return event_type.lower()
            if getattr(event, "source_type", None) is SourceType.TOOL_RESULT:
                return "tool_call"
            return "task_trajectory"
        if isinstance(event, dict):
            event_type = str(event.get("event_type", "")).strip().lower()
            if event_type in {"tool_call", "task_trajectory", "user_feedback", "user_behavior", "manual_config"}:
                return event_type
            source_type = str(event.get("source_type", "")).strip().lower()
            if source_type in {"tool_result", "tool_call"}:
                return "tool_call"
            if source_type in {"manual_config"}:
                return "manual_config"
            if source_type in {"user_behavior"}:
                return "user_behavior"
            return "task_trajectory"
        return "task_trajectory"

    def _event_content(self, event: MemoryEvent | dict) -> dict:
        """从旧版/新版输入中提取内容字典。"""
        if isinstance(event, MemoryEvent):
            content = getattr(event, "content", None)
            if isinstance(content, dict):
                return content
            payload = getattr(event, "payload", {}) or {}
            if isinstance(payload, dict):
                return payload
            return {}
        if isinstance(event, dict):
            if isinstance(event.get("content"), dict):
                return event.get("content")
            if isinstance(event.get("payload"), dict):
                return event.get("payload")
            return {}
        return {}

    def _event_quality_score(self, event: MemoryEvent | dict) -> float:
        """兼容旧版 quality_score 与新版 quality.score。"""
        if isinstance(event, MemoryEvent):
            quality = getattr(event, "quality", None)
            if quality is not None and hasattr(quality, "score"):
                return float(quality.score)
            return float(getattr(event, "quality_score", 0.5))
        if isinstance(event, dict):
            quality = event.get("quality")
            if isinstance(quality, dict):
                return float(quality.get("score", 0.5))
            return float(event.get("quality_score", 0.5))
        return 0.5

    def _get_event_field(self, event: MemoryEvent | dict, field: str, default: str = "") -> str:
        """统一读取 scene/task_type/source/user_id/event_id 等字段。"""
        if isinstance(event, MemoryEvent):
            value = getattr(event, field, None)
            if value not in (None, ""):
                return str(value)
            if field == "source":
                source_type = getattr(event, "source_type", None)
                if source_type is not None:
                    return str(source_type)
            return default
        if isinstance(event, dict):
            value = event.get(field)
            if value not in (None, ""):
                return str(value)
            if field == "source":
                value = event.get("source_type")
                if value not in (None, ""):
                    return str(value)
            return default
        return default

    def _event_timestamp(self, event: MemoryEvent | dict):
        """统一获取时间戳，兼容旧版 datetime 和新版 ISO 字符串。"""
        if isinstance(event, MemoryEvent):
            value = getattr(event, "timestamp", None)
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except Exception:
                    return datetime.now()
            if value is not None:
                return value
            occurred_at = getattr(event, "occurred_at", None)
            if isinstance(occurred_at, str):
                try:
                    return datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
                except Exception:
                    return datetime.now()
            return datetime.now()
        if isinstance(event, dict):
            occurred_at = event.get("occurred_at") or event.get("timestamp")
            if isinstance(occurred_at, str):
                try:
                    return datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
                except Exception:
                    return datetime.now()
            return datetime.now()
        return datetime.now()

    def _evidence_source_type(self, event: MemoryEvent | dict) -> SourceType:
        """把事件类型映射为 Evidence.source_type 所需枚举。"""
        event_type = self._get_event_type(event)
        if event_type == "tool_call":
            return SourceType.TOOL_RESULT
        if event_type == "user_behavior":
            return SourceType.USER_BEHAVIOR
        if event_type == "manual_config":
            return SourceType.MANUAL_CONFIG
        return SourceType.TOOL_RESULT
