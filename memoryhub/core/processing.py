"""统一事件处理协调器。

把已通过安全处理并落库的 MemoryEvent 分发给偏好、知识和事实候选管线。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from memoryhub.adapter.schemas import (
    EventProcessingSummary,
    KnowledgeMemory,
    MemoryEvent,
    PreferenceMemory,
    SafetyAction,
    SceneScope,
)
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.safety import SensitiveDetector


class EventProcessingCoordinator:
    def __init__(
        self,
        *,
        pref_repo,
        know_repo,
        fact_pipeline=None,
        llm_client=None,
        on_memory_written: Callable[[object], None] | None = None,
        safety_config=None,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.fact_pipeline = fact_pipeline
        self.preference_extractor = PreferenceExtractor(llm_client=llm_client)
        self.knowledge_extractor = KnowledgeExtractor(llm_client=llm_client)
        self.on_memory_written = on_memory_written
        detector_kwargs = {}
        if safety_config is not None:
            detector_kwargs = {
                "rule_snapshot": safety_config.rule_snapshot,
                "policy": safety_config.policy,
                "auto_mask": safety_config.auto_mask,
                "reject_on_detect": safety_config.reject_on_detect,
                "max_depth": safety_config.max_depth,
                "max_field_chars": safety_config.max_field_chars,
                "max_scan_bytes": safety_config.max_scan_bytes,
                "max_scanned_fields": safety_config.max_scanned_fields,
                "max_candidates": safety_config.max_candidates,
                "max_findings": safety_config.max_findings,
                "max_path_chars": safety_config.max_path_chars,
            }
        self.detector = SensitiveDetector(**detector_kwargs)

    def sanitize(self, events: list[MemoryEvent]) -> tuple[list[MemoryEvent], list[str]]:
        """返回只包含 ALLOW/MASK 分支的安全事件副本。"""
        safe_events: list[MemoryEvent] = []
        warnings: list[str] = []
        for event in events:
            try:
                result = self.detector.process(event)
                if result.decision.action in (SafetyAction.ALLOW, SafetyAction.MASK):
                    safe_events.append(result.sanitized_event or event)
                else:
                    warnings.append(
                        f"event {event.event_id} blocked by safety action {result.decision.action.value}"
                    )
            except Exception:
                warnings.append(f"event {event.event_id} failed safety processing")
        return safe_events, warnings

    def process(self, events: list[MemoryEvent]) -> EventProcessingSummary:
        summary = EventProcessingSummary()
        if not events:
            return summary

        for event in events:
            try:
                structured_preferences = event.payload.get("preferences", [])
                preference_items = []
                if isinstance(structured_preferences, Sequence) and not isinstance(structured_preferences, (str, bytes)):
                    for raw in structured_preferences:
                        if not isinstance(raw, Mapping):
                            continue
                        preference_items.append(
                            PreferenceMemory(
                                memory_id=raw.get("memory_id") or f"pref_{event.event_id}",
                                user_id=event.user_id or "default",
                                preference_type=raw.get("preference_type", "output_style"),
                                text=str(raw.get("text", "")),
                                payload=dict(raw.get("payload", {})),
                                scope=SceneScope(**dict(raw.get("scope", {}))),
                                is_global=bool(raw.get("is_global", False)),
                                confidence=float(raw.get("confidence", 0.95)),
                                quality_score=event.quality.score,
                                extract_source="structured_agent_event",
                                tags=[str(tag) for tag in raw.get("tags", [])],
                            )
                        )
                if not preference_items:
                    preference_items = self.preference_extractor.extract(event)
                for memory in preference_items:
                    self.pref_repo.save(memory)
                    summary.preferences_written.append(memory.memory_id)
                    self._notify(memory)
            except Exception as exc:
                summary.warnings.append(f"preference extraction failed for {event.event_id}: {exc}")

        try:
            knowledge_items = []
            for event in events:
                structured_knowledge = event.payload.get("knowledge", [])
                if not isinstance(structured_knowledge, Sequence) or isinstance(structured_knowledge, (str, bytes)):
                    continue
                for raw in structured_knowledge:
                    if not isinstance(raw, Mapping):
                        continue
                    knowledge_items.append(
                        KnowledgeMemory(
                            memory_id=raw.get("memory_id") or f"know_{event.event_id}",
                            user_id=event.user_id or "default",
                            knowledge_type=raw.get("knowledge_type", "workflow"),
                            name=str(raw.get("name", "")),
                            content=str(raw.get("content", "")),
                            steps=[str(step) for step in raw.get("steps", [])],
                            tools=[str(tool) for tool in raw.get("tools", [])],
                            template_body=str(raw.get("template_body", "")),
                            scope=SceneScope(**dict(raw.get("scope", {}))),
                            confidence=float(raw.get("confidence", 0.9)),
                            success_count=int(raw.get("success_count", 0)),
                            total_count=int(raw.get("total_count", 0)),
                        )
                    )
                inferred_template = self.knowledge_extractor.extract_template_instruction(event)
                if inferred_template is not None:
                    knowledge_items.append(inferred_template)
            external_calls = [
                call
                for event in events
                for call in event.tool_calls
                if not call.tool_name.startswith(("memory_", "preference_", "fact_", "conflict_", "template_"))
            ]
            if not knowledge_items and len(external_calls) >= 2:
                knowledge_items = self.knowledge_extractor.extract_from_trajectory(events)
            for memory in knowledge_items:
                kind = getattr(memory.knowledge_type, "value", str(memory.knowledge_type))
                if kind not in {"workflow", "template"}:
                    continue
                self.know_repo.save(memory)
                summary.knowledge_written.append(memory.memory_id)
                self._notify(memory)
        except Exception as exc:
            summary.warnings.append(f"knowledge extraction failed: {exc}")

        if self.fact_pipeline is not None:
            for event in events:
                text_parts = [event.text]
                for call in event.tool_calls:
                    try:
                        text_parts.append(json.dumps(call.result, ensure_ascii=False))
                    except Exception:
                        pass
                fact_text = "\n".join(part for part in text_parts if part)
                if not fact_text:
                    continue
                try:
                    structured_triples = event.payload.get("fact_triples", [])
                    proposals = []
                    if isinstance(structured_triples, Sequence) and not isinstance(structured_triples, (str, bytes)):
                        from memoryhub.core.fact.models import FactCandidate, RawTriple

                        for raw in structured_triples:
                            if not isinstance(raw, Mapping):
                                continue
                            triple = RawTriple(**dict(raw))
                            admission = self.fact_pipeline.admission.evaluate(
                                triple,
                                project_id=event.payload.get("project_id"),
                                scope_hint=event.payload.get("fact_scope"),
                            )
                            proposals.append(
                                FactCandidate(
                                    candidate_id=FactCandidate.make_id(),
                                    raw_triple=triple,
                                    admission=admission,
                                    source_id=event.event_id,
                                    project_id_hint=event.payload.get("project_id"),
                                    scope_hint=event.payload.get("fact_scope"),
                                    metadata={"session_id": event.session_id, "turn_id": event.turn_id},
                                )
                            )
                    if not proposals:
                        proposals = self.fact_pipeline.propose(
                            fact_text,
                            source_id=event.event_id,
                            project_id=event.payload.get("project_id"),
                            scope_hint=event.payload.get("fact_scope"),
                            metadata={"session_id": event.session_id, "turn_id": event.turn_id},
                        )
                    summary.fact_proposal_ids.extend(
                        self.fact_pipeline.persist_proposals(proposals)
                    )
                except Exception:
                    summary.warnings.append(f"fact proposal failed for {event.event_id}")

        return summary

    def _notify(self, memory: object) -> None:
        if self.on_memory_written is not None:
            self.on_memory_written(memory)
