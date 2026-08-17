"""Knowledge extraction from admitted task trajectories.

The public class and method signatures are intentionally stable.  The internal
algorithm favors deterministic structured extraction, uses LLMs only when a
trajectory is otherwise admissible but underspecified, and never treats an
arbitrary accepted event as reusable knowledge.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    SceneScope,
    SourceType,
    ToolCallStatus,
)
from memoryhub.core.knowledge.confidence import (
    KnowledgeConfidenceCalculator,
    KnowledgeConfidenceFactors,
)
from memoryhub.core.knowledge.template_builder import TemplateBuilder

logger = logging.getLogger(__name__)


class KnowledgeExtractionError(RuntimeError):
    """Stable extraction failure that can be persisted by the retry pipeline."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class KnowledgeExtractor:
    """Extract workflows, cases, and templates from one completed trajectory."""

    _FAILURE_MARKERS = (
        "fail",
        "failed",
        "failure",
        "error",
        "cancel",
        "timeout",
        "失败",
        "错误",
        "取消",
        "超时",
    )
    _PARTIAL_MARKERS = ("partial", "pending", "running", "in_progress", "进行中", "部分")
    _SUCCESS_MARKERS = ("success", "succeeded", "done", "complete", "completed", "成功", "完成")
    _USABLE_TOOL_STATUSES = {ToolCallStatus.SUCCESS.value, ToolCallStatus.PARTIAL.value}

    def __init__(self, llm_client=None, template_builder: TemplateBuilder | None = None):
        self.llm_client = llm_client
        self.template_builder = template_builder or TemplateBuilder(llm_client=llm_client)
        self.confidence_calculator = KnowledgeConfidenceCalculator()
        self._min_steps_rule = 2

    def extract_from_trajectory(self, events: list[MemoryEvent | dict]) -> list[KnowledgeMemory]:
        trajectory = self._prepare_trajectory(events)
        if not trajectory:
            return []

        knowledge_items: list[KnowledgeMemory] = []
        workflow = self._build_workflow(trajectory)
        if workflow is not None:
            knowledge_items.append(workflow)
        case = self._build_case(trajectory)
        if case is not None:
            knowledge_items.append(case)
            if len(case.steps) >= self._min_steps_rule:
                knowledge_items.append(self.template_builder.build_from_case(case))
        return knowledge_items

    def extract_workflow(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        trajectory = self._prepare_trajectory(events)
        return self._build_workflow(trajectory) if trajectory else None

    def extract_case(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        trajectory = self._prepare_trajectory(events)
        return self._build_case(trajectory) if trajectory else None

    def extract_template(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        case = self.extract_case(events)
        if case is None or len(case.steps) < self._min_steps_rule:
            return None
        return self.template_builder.build_from_case(case)

    def _build_workflow(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        steps = self._extract_steps(events)
        if len(steps) < self._min_steps_rule:
            return None
        tools = self._extract_tool_chain(events)
        first_event = events[0]
        goal = self._identify_task_goal(events)
        evidences = self._build_evidences(events)
        confidence = self._knowledge_confidence(
            events,
            steps=steps,
            tools=tools,
            result=self._extract_result(events),
            evidences=evidences,
            kind="workflow",
        )
        return KnowledgeMemory(
            user_id=self._get_event_field(first_event, "user_id", "default"),
            knowledge_type=KnowledgeType.WORKFLOW,
            name=f"{goal}工作流",
            content=f"围绕 '{goal}' 的标准执行流程",
            steps=steps,
            tools=tools,
            scope=self._scope(first_event),
            confidence=confidence,
            success_count=1,
            total_count=1,
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.MID,
            evidences=evidences,
        )

    def _build_case(self, events: list[MemoryEvent | dict]) -> KnowledgeMemory | None:
        steps = self._extract_steps(events)
        tools = self._extract_tool_chain(events)
        result = self._extract_result(events)
        if not result or not (steps or tools):
            return None
        first_event = events[0]
        goal = self._identify_task_goal(events)
        evidences = self._build_evidences(events)
        confidence = self._knowledge_confidence(
            events,
            steps=steps,
            tools=tools,
            result=result,
            evidences=evidences,
            kind="case",
        )
        content = (
            f"任务目标：「{goal}」；执行步骤："
            f"{', '.join(steps) if steps else '无'}；最终结果：{result}。"
        )
        return KnowledgeMemory(
            user_id=self._get_event_field(first_event, "user_id", "default"),
            knowledge_type=KnowledgeType.CASE,
            name=f"{goal}案例",
            content=content,
            steps=steps,
            tools=tools,
            scope=self._scope(first_event),
            confidence=confidence,
            success_count=1,
            total_count=1,
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.MID,
            evidences=evidences,
        )

    def _prepare_trajectory(
        self, events: list[MemoryEvent | dict]
    ) -> list[MemoryEvent | dict]:
        prepared = self._prepare_events(events)
        trajectory = self._select_trajectory_events(prepared)
        if not trajectory:
            return []
        if self._should_llm_enrich(trajectory):
            trajectory = self._llm_enrich_trajectory(trajectory)
        return trajectory if self._trajectory_complete(trajectory) else []

    def _prepare_events(self, events: list[MemoryEvent | dict]) -> list[MemoryEvent | dict]:
        deduplicated: dict[str, MemoryEvent | dict] = {}
        anonymous: list[MemoryEvent | dict] = []
        for raw_event in events:
            event = self._coerce_event(raw_event)
            if event is None or self._event_quality_score(event) < 0.3:
                continue
            event_id = self._get_event_field(event, "event_id", "")
            if not event_id:
                anonymous.append(event)
                continue
            current = deduplicated.get(event_id)
            if (
                current is None
                or self._event_quality_score(event) > self._event_quality_score(current)
            ):
                deduplicated[event_id] = event
        return sorted([*deduplicated.values(), *anonymous], key=self._event_sort_key)

    def _select_trajectory_events(
        self, events: list[MemoryEvent | dict]
    ) -> list[MemoryEvent | dict]:
        signals = [event for event in events if self._is_knowledge_signal(event)]
        if not signals:
            return []
        groups: dict[tuple[str, str, str], list[MemoryEvent | dict]] = {}
        for event in signals:
            key = (
                self._get_event_field(event, "user_id", "default"),
                self._get_event_field(event, "session_id", ""),
                self._get_event_field(event, "task_type", ""),
            )
            groups.setdefault(key, []).append(event)
        return max(
            groups.values(),
            key=lambda group: (
                len(group),
                sum(self._event_quality_score(event) for event in group),
                self._event_sort_key(group[-1]),
            ),
        )

    def _is_knowledge_signal(self, event: MemoryEvent | dict) -> bool:
        event_type = self._get_event_type(event)
        content = self._event_content(event)
        if event_type in {"task_trajectory", "tool_call"}:
            return True
        if any(
            content.get(key) not in (None, "", [], {})
            for key in ("task_name", "goal", "steps", "tools", "result", "output")
        ):
            return True
        return bool(self._iter_tool_calls(event, usable_only=True))

    def _trajectory_complete(self, events: list[MemoryEvent | dict]) -> bool:
        statuses: list[str] = []
        for event in events:
            content = self._event_content(event)
            for key in ("status", "state", "outcome", "result_status"):
                value = content.get(key)
                if value not in (None, ""):
                    statuses.append(str(value).strip().lower())
        last_status = statuses[-1] if statuses else ""
        if self._contains_marker(last_status, self._FAILURE_MARKERS):
            return False
        if self._contains_marker(last_status, self._PARTIAL_MARKERS):
            return False
        if self._contains_marker(last_status, self._SUCCESS_MARKERS):
            return True

        result = self._extract_result(events)
        lowered = result.lower()
        if not result or self._contains_marker(lowered, self._FAILURE_MARKERS):
            return False
        if self._contains_marker(lowered, self._PARTIAL_MARKERS):
            return False
        return self._contains_marker(lowered, self._SUCCESS_MARKERS) or bool(
            self._extract_steps(events) or self._extract_tool_chain(events)
        )

    @staticmethod
    def _contains_marker(value: str, markers: tuple[str, ...]) -> bool:
        return any(marker in value for marker in markers)

    def _llm_available(self) -> bool:
        if self.llm_client is None:
            return False
        checker = getattr(self.llm_client, "is_available", None)
        return (
            bool(checker())
            if callable(checker)
            else callable(getattr(self.llm_client, "generate", None))
        )

    def _identify_task_goal(self, events: list[MemoryEvent | dict]) -> str:
        for event in events:
            content = self._event_content(event)
            for key in ("task_name", "goal", "title"):
                value = content.get(key)
                if value:
                    return self._clean_goal(str(value))

        rule_goal = ""
        for event in events:
            content = self._event_content(event)
            value = content.get("text") or self._get_event_field(event, "text", "")
            if value:
                rule_goal = str(value).strip()
                break
        if (not rule_goal or len(rule_goal) > 50) and self._llm_available():
            llm_goal = self._llm_summarize_goal(events)
            if llm_goal:
                return llm_goal
        return self._clean_goal(rule_goal or self._get_event_field(events[0], "task_type", "任务"))

    @staticmethod
    def _clean_goal(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip(" 「」'\"。，、：:")
        return cleaned[:20] if len(cleaned) > 20 else (cleaned or "任务")

    def _extract_tool_chain(self, events: list[MemoryEvent | dict]) -> list[str]:
        tools: list[str] = []
        seen: set[str] = set()
        for event in events:
            content = self._event_content(event)
            raw_tools = content.get("tools") or []
            if isinstance(raw_tools, list):
                for tool_name in raw_tools:
                    self._append_unique(tools, seen, str(tool_name))
            if self._get_event_type(event) == "tool_call":
                self._append_unique(tools, seen, str(content.get("tool_name", "")))
            for call in self._iter_tool_calls(event, usable_only=True):
                self._append_unique(tools, seen, str(self._call_field(call, "tool_name", "")))
        return tools

    def _extract_steps(self, events: list[MemoryEvent | dict]) -> list[str]:
        steps: list[str] = []
        seen: set[str] = set()
        for event in events:
            raw_steps = self._event_content(event).get("steps") or []
            if isinstance(raw_steps, list):
                for step in raw_steps:
                    self._append_unique(steps, seen, self._normalize_step(str(step)))
        if len(steps) < self._min_steps_rule:
            for event in events:
                for call in self._iter_tool_calls(event, usable_only=True):
                    tool = str(self._call_field(call, "tool_name", "")).strip()
                    if tool:
                        self._append_unique(steps, seen, f"调用 {tool}")
        if len(steps) < self._min_steps_rule and self._llm_available():
            for step in self._llm_extract_steps(events):
                self._append_unique(steps, seen, self._normalize_step(step))
        return steps

    @staticmethod
    def _append_unique(target: list[str], seen: set[str], value: str) -> None:
        cleaned = value.strip()
        key = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", cleaned.lower())
        if cleaned and len(cleaned) >= 2 and key and key not in seen:
            target.append(cleaned)
            seen.add(key)

    @staticmethod
    def _normalize_step(step: str) -> str:
        step = re.sub(
            r"^\s*(?:\u7b2c[\u4e00-\u9fff\d]+[\u6b65\u3001\uff1a:.]\s*|\d+[.\u3001\s]+)", "", step
        )
        return step.strip(" \u3002\uff0c\u3001\uff1a:.")

    def _extract_result(self, events: list[MemoryEvent | dict]) -> str:
        for event in reversed(events):
            content = self._event_content(event)
            for key in ("result", "output", "summary"):
                value = content.get(key)
                if value not in (None, "", [], {}):
                    return self._stringify(value)
            for call in reversed(self._iter_tool_calls(event, usable_only=True)):
                value = self._call_field(call, "result", None)
                if value not in (None, "", [], {}):
                    return self._stringify(value)
        return ""

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:500]

    def _knowledge_confidence(
        self,
        events: list[MemoryEvent | dict],
        *,
        steps: list[str],
        tools: list[str],
        result: str,
        evidences: list[Evidence],
        kind: str,
    ) -> float:
        qualities = [self._event_quality_score(event) for event in events]
        average_quality = sum(qualities) / len(qualities)
        event_quality = 0.7 * average_quality + 0.3 * min(qualities)
        explicit_completion = any(
            self._contains_marker(
                str(self._event_content(event).get(key, "")).lower(),
                self._SUCCESS_MARKERS,
            )
            for event in events
            for key in ("status", "state", "outcome", "result_status")
        )
        completion = 1.0 if explicit_completion else 0.82
        expected_steps = 3 if kind == "workflow" else 2
        structure = min(1.0, 0.35 + 0.14 * min(len(steps), expected_steps + 2) + 0.05 * len(tools))
        unique_events = {item.event_id for item in evidences if item.event_id}
        source_types = {str(item.source_type) for item in evidences}
        evidence = min(1.0, 0.25 + 0.18 * len(unique_events) + 0.08 * len(source_types))
        all_calls = [
            call
            for event in events
            for call in self._iter_tool_calls(event, usable_only=False)
        ]
        usable_calls = [
            call
            for event in events
            for call in self._iter_tool_calls(event, usable_only=True)
        ]
        consistency = len(usable_calls) / len(all_calls) if all_calls else 0.9
        outcome = 1.0 if result else (0.78 if kind == "workflow" else 0.55)
        return self.confidence_calculator.score(
            KnowledgeConfidenceFactors(
                event_quality=event_quality,
                completion=completion,
                structure=structure,
                evidence=evidence,
                outcome=outcome,
                consistency=consistency,
            )
        )

    def _build_evidences(self, events: list[MemoryEvent | dict]) -> list[Evidence]:
        evidences: list[Evidence] = []
        weights = {
            "task_trajectory": 0.95,
            "tool_call": 0.85,
            "user_feedback": 0.9,
            "manual_config": 0.9,
        }
        for event in events:
            event_id = self._get_event_field(event, "event_id", "")
            event_type = self._get_event_type(event)
            content = self._event_content(event)
            if event_type == "task_trajectory":
                summary = (
                    f"任务「{content.get('task_name', self._identify_task_goal([event]))}」"
                    f"执行结果：{content.get('result', self._extract_result([event]) or '未知')}"
                )
            elif self._iter_tool_calls(event, usable_only=True):
                names = [
                    str(self._call_field(call, "tool_name", ""))
                    for call in self._iter_tool_calls(event, usable_only=True)
                ]
                summary = f"工具调用：{', '.join(name for name in names if name)}"
            else:
                summary = str(content)[:160]
            if not summary:
                continue
            evidence_key = f"{event_id}|{event_type}|{summary}"
            evidence_id = hashlib.sha256(evidence_key.encode("utf-8")).hexdigest()[:8]
            evidences.append(
                Evidence(
                    evidence_id=evidence_id,
                    event_id=event_id,
                    content=summary[:200],
                    source_type=self._evidence_source_type(event),
                    timestamp=self._event_timestamp(event),
                    weight=weights.get(event_type, 0.8),
                )
            )
        return evidences

    def _should_llm_enrich(self, events: list[MemoryEvent | dict]) -> bool:
        """Use one structured LLM pass only when the trajectory is underspecified."""
        if not self._llm_available():
            return False
        steps = self._extract_steps_from_payload(events)
        has_goal = any(
            self._event_content(event).get(key)
            for event in events
            for key in ("task_name", "goal", "title")
        )
        has_result = bool(self._extract_result(events))
        return len(steps) < self._min_steps_rule or not has_goal or not has_result

    def _extract_steps_from_payload(self, events: list[MemoryEvent | dict]) -> list[str]:
        steps: list[str] = []
        for event in events:
            raw_steps = self._event_content(event).get("steps") or []
            if isinstance(raw_steps, list):
                steps.extend(str(step).strip() for step in raw_steps if str(step).strip())
        return steps

    def _llm_enrich_trajectory(
        self, events: list[MemoryEvent | dict]
    ) -> list[MemoryEvent | dict]:
        summaries = [
            f"{self._get_event_type(event)}: "
            f"{json.dumps(self._event_content(event), ensure_ascii=False, default=str)[:240]}"
            for event in events[:20]
        ]
        prompt = (
            "Complete reusable knowledge from these gate-approved task events. "
            "Return JSON only with goal, steps, tools, and result. "
            "Use empty values when evidence is insufficient and do not invent facts.\n"
            + "\n".join(summaries)
        )
        try:
            result = self.llm_client.generate_json(
                prompt=prompt,
                schema={
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "steps": {"type": "array", "items": {"type": "string"}},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "result": {"type": "string"},
                    },
                },
                system_prompt="You strictly structure task trajectories into reusable knowledge.",
            )
        except Exception as exc:
            logger.exception("LLM trajectory enrichment failed: %s", exc)
            raise KnowledgeExtractionError("knowledge.enrichment_llm_failed") from exc
        if not isinstance(result, dict):
            raise KnowledgeExtractionError("knowledge.enrichment_invalid")
        enriched = dict(self._event_content(events[0]))
        if result.get("goal"):
            enriched.setdefault("task_name", str(result["goal"]).strip())
        for field in ("steps", "tools"):
            values = result.get(field)
            if isinstance(values, list) and values:
                enriched[field] = [str(value).strip() for value in values if str(value).strip()]
        if result.get("result"):
            enriched["result"] = str(result["result"]).strip()
        if isinstance(events[0], MemoryEvent):
            updated = events[0].model_copy(update={"payload": enriched})
        else:
            updated = dict(events[0])
            updated["payload"] = enriched
        return [updated, *events[1:]]

    def _llm_summarize_goal(self, events: list[MemoryEvent | dict]) -> str | None:
        summaries = [
            f"{self._get_event_type(event)}: {str(self._event_content(event))[:80]}"
            for event in events[:10]
        ]
        prompt = (
            "请从以下任务执行事件中，用不超过10个字的短语概括核心任务目标。"
            "只返回目标短语，不要解释。\n事件列表：\n" + "\n".join(summaries)
        )
        try:
            result = self.llm_client.generate(
                prompt=prompt,
                system_prompt="你是任务分析专家，擅长从执行记录中提炼核心目标。",
            )
        except Exception as exc:
            logger.exception("LLM goal summarization failed: %s", exc)
            raise KnowledgeExtractionError("knowledge.goal_llm_failed") from exc
        goal = str(getattr(result, "content", "")).strip().strip("「」'\"。，")
        return goal if 2 <= len(goal) <= 20 else None

    def _llm_extract_steps(self, events: list[MemoryEvent | dict]) -> list[str]:
        summaries = []
        for event in events[:20]:
            content = self._event_content(event)
            serialized = json.dumps(content, ensure_ascii=False, default=str)[:120]
            summaries.append(f"{self._get_event_type(event)}: {serialized}")
        prompt = (
            "请按执行顺序归纳3-6条核心步骤，只返回JSON："
            '{"steps":["步骤1","步骤2"]}。\n执行事件：\n' + "\n".join(summaries)
        )
        try:
            result = self.llm_client.generate_json(
                prompt=prompt,
                schema={
                    "type": "object",
                    "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
                },
                system_prompt="你是流程分析专家。",
            )
        except Exception as exc:
            logger.exception("LLM step extraction failed: %s", exc)
            raise KnowledgeExtractionError("knowledge.steps_llm_failed") from exc
        steps = result.get("steps", []) if isinstance(result, dict) else []
        if not isinstance(steps, list):
            return []
        return [str(step).strip() for step in steps[:8] if str(step).strip()]

    def _coerce_event(self, event: MemoryEvent | dict) -> MemoryEvent | dict | None:
        if isinstance(event, MemoryEvent):
            return event
        if isinstance(event, dict):
            try:
                return MemoryEvent.model_validate(event)
            except Exception:
                return event
        return None

    def _get_event_type(self, event: MemoryEvent | dict) -> str:
        raw = self._get_event_field(event, "event_type", "").strip().lower()
        if raw:
            return raw
        source = self._get_event_field(event, "source_type", "").strip().lower()
        if source in {"tool_result", "tool_call"}:
            return "tool_call"
        if source == "manual_config":
            return "manual_config"
        if source == "user_behavior":
            return "user_behavior"
        return "task_trajectory"

    def _event_content(self, event: MemoryEvent | dict) -> dict:
        if isinstance(event, MemoryEvent):
            content = dict(event.payload or {})
            if event.text and not content.get("text"):
                content["text"] = event.text
            return content
        if isinstance(event, dict):
            content = (
                event.get("content")
                if isinstance(event.get("content"), dict)
                else event.get("payload")
            )
            result = dict(content) if isinstance(content, dict) else {}
            if event.get("text") and not result.get("text"):
                result["text"] = event.get("text")
            return result
        return {}

    def _event_quality_score(self, event: MemoryEvent | dict) -> float:
        if isinstance(event, MemoryEvent):
            return float(getattr(event.quality, "score", 0.5))
        quality = event.get("quality") if isinstance(event, dict) else None
        if isinstance(quality, dict):
            return float(quality.get("score", 0.5))
        return float(event.get("quality_score", 0.5)) if isinstance(event, dict) else 0.5

    def _get_event_field(self, event: MemoryEvent | dict, field: str, default: str = "") -> str:
        value = getattr(event, field, None) if isinstance(event, MemoryEvent) else event.get(field)
        if value in (None, "") and field == "source":
            value = (
                getattr(event, "source_type", None)
                if isinstance(event, MemoryEvent)
                else event.get("source_type")
            )
        raw = getattr(value, "value", value)
        return str(raw) if raw not in (None, "") else default

    def _event_sort_key(self, event: MemoryEvent | dict) -> tuple[datetime, str, str]:
        return (
            self._event_timestamp(event),
            self._get_event_field(event, "turn_id", ""),
            self._get_event_field(event, "event_id", ""),
        )

    def _event_timestamp(self, event: MemoryEvent | dict) -> datetime:
        value = self._get_event_field(event, "occurred_at", "") or self._get_event_field(
            event, "timestamp", ""
        )
        if value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    def _evidence_source_type(self, event: MemoryEvent | dict) -> SourceType:
        raw = self._get_event_field(event, "source_type", SourceType.TOOL_RESULT.value)
        try:
            return SourceType(raw)
        except ValueError:
            return SourceType.TOOL_RESULT

    def _scope(self, event: MemoryEvent | dict) -> SceneScope:
        return SceneScope(
            scene=self._get_event_field(event, "scene", ""),
            task_type=self._get_event_field(event, "task_type", ""),
            app=self._get_event_field(event, "source", ""),
        )

    def _iter_tool_calls(self, event: MemoryEvent | dict, *, usable_only: bool) -> list[Any]:
        calls = (
            list(getattr(event, "tool_calls", []) or [])
            if isinstance(event, MemoryEvent)
            else list(event.get("tool_calls", []) or [])
        )
        calls.sort(key=lambda call: int(self._call_field(call, "sequence", 0) or 0))
        if not usable_only:
            return calls
        result = []
        for call in calls:
            status = getattr(
                self._call_field(call, "status", ""), "value", self._call_field(call, "status", "")
            )
            if str(status).strip().lower() in self._USABLE_TOOL_STATUSES:
                result.append(call)
        return result

    @staticmethod
    def _call_field(call: Any, field: str, default: Any) -> Any:
        return (
            getattr(call, field, default)
            if not isinstance(call, dict)
            else call.get(field, default)
        )
