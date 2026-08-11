"""统一事件处理协调器（前端 agent 演示适配层）。

把已通过安全处理并落库的 MemoryEvent 分发给偏好、知识和事实候选管线。
本文件是便于前端联调而重建的临时适配层，复用 memoryhub 现成服务。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence

from memoryhub.adapter.schemas import (
    EventProcessingSummary,
    KnowledgeMemory,
    MemoryEvent,
    PreferenceMemory,
    SafetyAction,
    SceneScope,
)
from memoryhub.core.conflict.detector import ConflictDetector
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
        conflict_repo=None,
        memory_write_service=None,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.fact_pipeline = fact_pipeline
        self.preference_extractor = PreferenceExtractor(llm_client=llm_client)
        self.knowledge_extractor = KnowledgeExtractor(llm_client=llm_client)
        self.on_memory_written = on_memory_written
        # 写入服务：非 None 时走 MemoryWriteService（同步向量/关键词索引）
        self.memory_write_service = memory_write_service
        # 演示适配层：确定性冲突检测（不依赖 LLM），让前端能测试冲突处理页
        self.conflict_repo = conflict_repo
        self.conflict_detector = ConflictDetector() if conflict_repo is not None else None
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
                    for _idx, raw in enumerate(structured_preferences):
                        if not isinstance(raw, Mapping):
                            continue
                        # 演示适配层：演示事件通常不携带 memory_id，
                        # 若沿用 f"pref_{event.event_id}" 会导致同轮多条偏好互相覆盖，
                        # 这里按序号生成唯一 id，保证每条偏好都能落库。
                        base_id = raw.get("memory_id") or f"pref_{event.event_id}"
                        memory_id = base_id if raw.get("memory_id") else f"{base_id}_{_idx + 1}"
                        preference_items.append(
                            PreferenceMemory(
                                memory_id=memory_id,
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
                if not preference_items:
                    preference_items = self._extract_dialogue_preferences(event)
                for memory in preference_items:
                    self._save_preference(memory)
                    summary.preferences_written.append(memory.memory_id)
                    self._detect_pref_conflict(memory, summary)
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
            external_calls = [
                call
                for event in events
                for call in event.tool_calls
                if not call.tool_name.startswith(("memory_", "preference_", "fact_", "conflict_", "template_"))
            ]
            if not knowledge_items and len(external_calls) >= 2:
                try:
                    knowledge_items = self.knowledge_extractor.extract_from_trajectory(events)
                except Exception:
                    pass
            for memory in knowledge_items:
                kind = getattr(memory.knowledge_type, "value", str(memory.knowledge_type))
                if kind not in {"workflow", "template"}:
                    continue
                self._save_knowledge(memory)
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
                    # 演示适配层：无显式 fact_triples 时不调用 LLM 提取，
                    # 避免 ollama 未运行时阻塞 step 响应（fact 提取走确定性数据）
                    for proposal in proposals:
                        summary.fact_proposal_ids.append(proposal.proposal_id)
                    # 候选由 agent_api 暂存，供前端 FactDialog 裁决
                    self._fact_candidates = list(proposals)
                except Exception:
                    summary.warnings.append(f"fact proposal failed for {event.event_id}")

        return summary

    def _extract_dialogue_preferences(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """演示适配层：无 LLM 时从中文对话文本确定性抽取显式偏好。

        仅在结构化偏好与 PreferenceExtractor 均无输出时作为兜底，
        保证前端 demo 在 ollama 未运行时也能沉淀常见写作/输出偏好。
        """
        text = (event.text or "").strip()
        if not text:
            return []
        user_id = event.user_id or "default"
        quality = getattr(event, "quality", None)
        quality_score = float(getattr(quality, "score", 1.0) or 1.0)
        prefs: list[PreferenceMemory] = []
        idx = 0

        def _new(text_: str, ptype: str, *, global_: bool, tags: list[str]) -> PreferenceMemory:
            nonlocal idx
            idx += 1
            return PreferenceMemory(
                memory_id=f"pref_{event.event_id}_d{idx}",
                user_id=user_id,
                preference_type=ptype,
                text=text_,
                scope=SceneScope(scene="*" if global_ else event.scene, task_type="*" if global_ else event.task_type),
                is_global=global_,
                confidence=0.95,
                quality_score=quality_score,
                extract_source="explicit_feedback",
                tags=tags,
            )

        lang_map = {
            "中文": "中文", "汉语": "中文",
            "英文": "英语", "英语": "英语",
            "法语": "法语", "日语": "日语", "德语": "德语", "韩语": "韩语",
        }
        lang_match = re.search(r"使用?(中文|汉语|英文|英语|法语|日语|德语|韩语)", text)
        if lang_match:
            prefs.append(_new(
                f"项目材料默认使用{lang_map[lang_match.group(1)]}。",
                "language_preference",
                global_=True,
                tags=["语言", lang_map[lang_match.group(1)]],
            ))

        if re.search(r"简洁|简略|简要|精炼|紧凑|不要太详|不要啰嗦", text):
            prefs.append(_new(
                "内容尽量保持简洁。",
                "output_style",
                global_=True,
                tags=["简洁", "风格"],
            ))

        has_conclusion = re.search(r"先给?结论|结论先行|先.{0,6}结论", text) is not None
        has_bullet = re.search(r"列?要点|列表|分点|条目", text) is not None
        if has_conclusion or has_bullet:
            prefs.append(_new(
                "先给结论，再列要点。",
                "output_style",
                global_=True,
                tags=["结构", "要点"],
            ))

        if re.search(r"正式|详细|详尽|书面", text):
            prefs.append(_new(
                "采用正式、详细的表达方式。",
                "scene_preference",
                global_=False,
                tags=["正式", "详细"],
            ))

        return prefs

    def _save_preference(self, memory) -> None:
        """写偏好：优先走 MemoryWriteService（同步检索索引），否则直接落库。"""
        if self.memory_write_service is not None:
            self.memory_write_service.upsert_memory(memory)
        else:
            self.pref_repo.save(memory)

    def _save_knowledge(self, memory) -> None:
        """写知识：优先走 MemoryWriteService（同步检索索引），否则直接落库。"""
        if self.memory_write_service is not None:
            self.memory_write_service.upsert_memory(memory)
        else:
            self.know_repo.save(memory)

    def _detect_pref_conflict(self, memory, summary) -> None:
        """写入偏好后做确定性冲突检测，冲突记录存进 conflict_repo 供前端冲突页测试。"""
        if self.conflict_detector is None:
            return
        try:
            existing = self.pref_repo.list_all(status="active", user_id=memory.user_id)
            conflict = self.conflict_detector.check_preference(memory, existing)
            if conflict is not None:
                self.conflict_repo.save(conflict)
                summary.conflict_ids.append(conflict.conflict_id)
        except Exception:
            pass

    def _notify(self, memory: object) -> None:
        if self.on_memory_written is not None:
            self.on_memory_written(memory)