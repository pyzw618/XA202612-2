"""Convert one upstream MemoryEvent into durable fact proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import (
    FactCandidate,
    FactDecisionMode,
    FactProposalStatus,
    Resolution,
)
from .pipeline import FactMemoryPipeline


@dataclass
class FactIngestionOutcome:
    proposal_ids: list[str] = field(default_factory=list)
    committed_fact_ids: list[str] = field(default_factory=list)
    awaiting_decision_ids: list[str] = field(default_factory=list)
    rejected_count: int = 0


class FactIngestionAdapter:
    """Process one already-quality-scored and safety-approved MemoryEvent."""

    _USABLE_STATUSES = {"success", "partial"}

    def __init__(
        self,
        pipeline: FactMemoryPipeline,
        decision_mode: str = FactDecisionMode.USER_REVIEW.value,
        conflict_decision_mode: str = FactDecisionMode.USER_REVIEW.value,
    ):
        if decision_mode not in FactDecisionMode.choices():
            raise ValueError(f"unsupported fact decision mode: {decision_mode}")
        if conflict_decision_mode not in FactDecisionMode.choices():
            raise ValueError(
                "unsupported fact conflict decision mode: "
                f"{conflict_decision_mode}"
            )
        self.pipeline = pipeline
        self.decision_mode = decision_mode
        self.conflict_decision_mode = conflict_decision_mode

    def propose_from_event(self, event: Any) -> list[FactCandidate]:
        """Use one extraction call for the complete event and all usable tool results."""
        event_id = str(getattr(event, "event_id", "")).strip()
        project_id_hint = self._project_id_hint(event)
        text, sources = self.format_event(event)
        if not text:
            return []
        return self.pipeline.propose(
            text,
            source_id=event_id or "event",
            project_id=project_id_hint,
            metadata={
                **self._event_metadata(event),
                "content_source": "memory_event",
                "content_sources": sources,
                "conflict_decision_mode": self.conflict_decision_mode,
            },
            decision_mode=self.decision_mode,
        )

    def ingest_event(self, event: Any) -> FactIngestionOutcome:
        """Stage candidates for review or commit admitted candidates autonomously."""
        project_id = self._project_id_hint(event)
        scope = "project" if project_id else "global"
        user_id = str(getattr(event, "user_id", "") or "default")
        outcome = FactIngestionOutcome()

        for candidate in self.propose_from_event(event):
            if (
                self.decision_mode == FactDecisionMode.AGENT_AUTONOMOUS.value
                and not candidate.admission.should_remember
            ):
                outcome.rejected_count += 1
                continue

            self.pipeline.store.save_fact_proposal(
                candidate,
                user_id=user_id,
                decision_mode=self.decision_mode,
                conflict_decision_mode=self.conflict_decision_mode,
            )
            outcome.proposal_ids.append(candidate.proposal_id)

            if self.decision_mode == FactDecisionMode.USER_REVIEW.value:
                continue

            result = self.pipeline.commit(
                candidate,
                scope=scope,
                project_id=project_id,
                user_id=user_id,
                auto_resolve=(
                    self.conflict_decision_mode
                    == FactDecisionMode.AGENT_AUTONOMOUS.value
                ),
            )
            requires_decision = (
                result.relation == "CONFLICT"
                and result.resolution == Resolution.ESCALATE.value
            )
            if requires_decision:
                proposal_status = FactProposalStatus.AWAITING_DECISION.value
                outcome.awaiting_decision_ids.append(candidate.proposal_id)
            else:
                proposal_status = FactProposalStatus.COMMITTED.value
                stored_fact = (
                    result.existing_fact
                    if (
                        result.existing_fact
                        and (
                            result.relation == "DUPLICATE"
                            or result.resolution == Resolution.KEEP_OLD.value
                        )
                    )
                    else result.new_fact
                )
                if stored_fact is not None:
                    outcome.committed_fact_ids.append(stored_fact.fact_id)
            self.pipeline.store.update_fact_proposal_status(
                candidate.proposal_id,
                user_id=user_id,
                status=proposal_status,
                committed_fact_id=(
                    None
                    if requires_decision
                    else outcome.committed_fact_ids[-1]
                    if outcome.committed_fact_ids
                    else None
                ),
            )
        return outcome

    @classmethod
    def format_event(cls, event: Any) -> tuple[str, list[dict[str, str]]]:
        """Build one structured prompt while retaining source identifiers."""
        payload: dict[str, Any] = {}
        sources: list[dict[str, str]] = []
        event_text = str(getattr(event, "text", "") or "").strip()
        if event_text:
            payload["event_text"] = event_text
            sources.append({"kind": "event_text", "id": "text"})

        calls = []
        for call in list(getattr(event, "tool_calls", []) or []):
            status = cls._enum_value(getattr(call, "status", ""))
            result = getattr(call, "result", None)
            if status not in cls._USABLE_STATUSES or result in (None, "", [], {}):
                continue
            call_id = str(getattr(call, "call_id", "")).strip()
            tool_name = str(getattr(call, "tool_name", "")).strip()
            calls.append(
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "arguments": getattr(call, "arguments", {}) or {},
                    "result": result,
                    "status": status,
                }
            )
            sources.append(
                {"kind": "tool_result", "id": call_id or tool_name or "tool"}
            )
        if calls:
            payload["tool_calls"] = calls
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            if payload
            else "",
            sources,
        )

    @classmethod
    def format_tool_call(cls, call: Any) -> str:
        """Compatibility helper retained for callers that format one tool result."""
        tool_name = str(getattr(call, "tool_name", "")).strip()
        return "\n".join(
            (
                f"工具名称：{tool_name or 'unknown'}",
                "调用参数：",
                cls._json_text(getattr(call, "arguments", {}) or {}),
                "工具返回结果：",
                cls._json_text(getattr(call, "result", None)),
            )
        )

    @staticmethod
    def _json_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _enum_value(value: Any) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").strip().lower()

    @staticmethod
    def _project_id_hint(event: Any) -> Optional[str]:
        direct = str(getattr(event, "project_id", "") or "").strip()
        if direct:
            return direct
        payload = getattr(event, "payload", {}) or {}
        if isinstance(payload, dict):
            value = str(payload.get("project_id", "") or "").strip()
            return value or None
        return None

    @staticmethod
    def _event_metadata(event: Any) -> dict:
        quality = getattr(event, "quality", None)
        return {
            "event_id": str(getattr(event, "event_id", "") or ""),
            "user_id": str(getattr(event, "user_id", "") or "default"),
            "source_type": FactIngestionAdapter._enum_value(
                getattr(event, "source_type", "")
            ),
            "event_type": str(getattr(event, "event_type", "") or ""),
            "session_id": str(getattr(event, "session_id", "") or ""),
            "turn_id": str(getattr(event, "turn_id", "") or ""),
            "scene": str(getattr(event, "scene", "") or ""),
            "task_type": str(getattr(event, "task_type", "") or ""),
            "quality_score": getattr(quality, "score", None),
            "quality_status": FactIngestionAdapter._enum_value(
                getattr(quality, "status", "")
            ),
        }
