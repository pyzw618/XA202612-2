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
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.knowledge.confidence import KnowledgeConfidenceCalculator
from memoryhub.core.knowledge.handler import KnowledgeMemoryHandler
from memoryhub.core.knowledge.updater import KnowledgeUpdater
from memoryhub.core.preference.extractor import PreferenceExtractor, build_event_evidence
from memoryhub.core.preference.handler import PreferenceMemoryHandler
from memoryhub.core.preference.updater import PreferenceUpdater
from memoryhub.core.safety import SensitiveDetector


class EventProcessingCoordinator:
    def __init__(
        self,
        *,
        pref_repo,
        know_repo,
        llm_client=None,
        on_memory_written: Callable[[object], None] | None = None,
        safety_config=None,
        conflict_repo=None,
        memory_write_service=None,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.preference_extractor = PreferenceExtractor(llm_client=llm_client)
        self.knowledge_extractor = KnowledgeExtractor(llm_client=llm_client)
        self.preference_updater = PreferenceUpdater(
            llm_client=llm_client,
            pref_repo=pref_repo,
            conflict_repo=conflict_repo,
            write_service=memory_write_service,
        )
        self.knowledge_updater = KnowledgeUpdater(
            write_service=memory_write_service,
            conflict_repo=conflict_repo,
            llm_client=llm_client,
        )
        # R1: 演示路径与正式链路同构——偏好/知识抽取经统一 Handler 链（同一套
        # extract → evidence → confidence → decide → apply），不再在演示层分叉。
        self.preference_handler = PreferenceMemoryHandler(
            self.preference_extractor, self.preference_updater
        )
        self.knowledge_handler = KnowledgeMemoryHandler(
            self.knowledge_extractor, self.knowledge_updater
        )
        self.on_memory_written = on_memory_written
        # 写入服务：非 None 时走 MemoryWriteService（同步向量/关键词索引）
        self.memory_write_service = memory_write_service
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

    def sanitize(
        self, events: list[MemoryEvent]
    ) -> tuple[list[MemoryEvent], list[str]]:
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
                        f"event {event.event_id} blocked by safety action "
                        f"{result.decision.action.value}"
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
                if isinstance(structured_preferences, Sequence) and not isinstance(
                    structured_preferences, (str, bytes)
                ):
                    for _idx, raw in enumerate(structured_preferences):
                        if not isinstance(raw, Mapping):
                            continue
                        # 演示适配层：演示事件通常不携带 memory_id，
                        # 若沿用 f"pref_{event.event_id}" 会导致同轮多条偏好互相覆盖，
                        # 这里按序号生成唯一 id，保证每条偏好都能落库。
                        base_id = raw.get("memory_id") or f"pref_{event.event_id}"
                        memory_id = (
                            base_id if raw.get("memory_id") else f"{base_id}_{_idx + 1}"
                        )
                        preference_items.append(
                            PreferenceMemory(
                                memory_id=memory_id,
                                user_id=event.user_id or "default",
                                preference_type=raw.get(
                                    "preference_type", "output_style"
                                ),
                                text=str(raw.get("text", "")),
                                payload=dict(raw.get("payload", {})),
                                scope=SceneScope(**dict(raw.get("scope", {}))),
                                is_global=bool(raw.get("is_global", False)),
                                confidence=float(raw.get("confidence", 0.95)),
                                quality_score=event.quality.score,
                                extract_source="structured_agent_event",
                                tags=[str(tag) for tag in raw.get("tags", [])],
                                # 携带事件证据链，让统一四因子公式真正参与计算
                                # （无证据会落入 baseline，structured_agent_event 仅按质量分派生）
                                evidences=[build_event_evidence(event)],
                            )
                        )
                written: list[str] = []
                if preference_items:
                    for memory in preference_items:
                        result_id = self.preference_updater.add(
                            memory, skip_write_gate=True
                        )
                        if result_id:
                            written.append(result_id)
                else:
                    # R1: 演示路径与正式链路同构——走统一 Handler 链，不再在演示层分叉抽取
                    decisions = self.preference_handler.process(event)
                    for decision in decisions:
                        result_id = self.preference_handler.apply(decision)
                        if result_id:
                            written.append(result_id)
                    # 兜底：Handler 链无产出时，从中文对话确定性抽取显式偏好（无 LLM 也可用）
                    if not written:
                        for memory in self._extract_dialogue_preferences(event):
                            result_id = self.preference_updater.add(
                                memory, skip_write_gate=True
                            )
                            if result_id:
                                written.append(result_id)
                summary.preferences_written.extend(written)
                for result_id in written:
                    stored = self.pref_repo.get_by_id(result_id)
                    if stored is not None:
                        self._notify(stored)
            except Exception as exc:
                summary.warnings.append(
                    f"preference extraction failed for {event.event_id}: {exc}"
                )

        try:
            knowledge_items = []
            for event in events:
                structured_knowledge = event.payload.get("knowledge", [])
                if not isinstance(structured_knowledge, Sequence) or isinstance(
                    structured_knowledge, (str, bytes)
                ):
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
                            # 携带事件证据链，置信度由统一计算器重算（见下方 add 前处理），
                            # payload 中的裸 confidence 不作为真实置信度落库
                            evidences=[build_event_evidence(event)],
                        )
                    )
            external_calls = [
                call
                for event in events
                for call in event.tool_calls
                if not call.tool_name.startswith(
                    ("memory_", "preference_", "fact_", "conflict_", "template_")
                )
            ]
            written: list[str] = []
            if knowledge_items:
                for memory in knowledge_items:
                    # 写路径强制重算置信度：raw payload confidence 只是占位，
                    # 统一 KnowledgeConfidenceCalculator 基于事件质量/结构/证据计算
                    self._recalculate_knowledge_confidence(memory)
                    result_id = self.knowledge_updater.add(
                        memory, skip_write_gate=True
                    )
                    if result_id:
                        written.append(result_id)
            elif external_calls:
                # R1: 演示路径与正式链路同构——走统一 Handler 链；
                # 修复：不再丢弃 CASE 知识（原 filter 只保留 workflow/template）。
                decisions = self.knowledge_handler.process(events)
                for decision in decisions:
                    result_id = self.knowledge_handler.apply(decision)
                    if result_id:
                        written.append(result_id)
                    elif decision.action in {"reject", "review"}:
                        summary.warnings.append(
                            "knowledge candidate "
                            f"{getattr(decision.candidate.payload, 'memory_id', '?')} "
                            f"dropped: action={decision.action} reason={decision.reason}"
                        )
            # 纯对话文本中的客观陈述（"X是Y/X为Y"）确定性抽取为 knowledge(FACT)
            # （extract_facts 内部规则，无 LLM 不臆造；§4.8.3）
            for fact in self.knowledge_extractor.extract_facts(events):
                result_id = self.knowledge_updater.add(
                    fact, skip_write_gate=True
                )
                if result_id:
                    written.append(result_id)
            summary.knowledge_written.extend(written)
            for result_id in written:
                stored = self.know_repo.get_by_id(result_id)
                if stored is not None:
                    self._notify(stored)
        except Exception as exc:
            summary.warnings.append(f"knowledge extraction failed: {exc}")

        # 事实（Fact）已并入知识链以 KnowledgeType.FACT 产出（REFACTOR_PLAN_V2 §4.8），
        # 不再经独立 Fact 管线生成 legacy 候选；演示适配层不再产生 fact_proposals。

        return summary

    def _extract_dialogue_preferences(
        self, event: MemoryEvent
    ) -> list[PreferenceMemory]:
        """演示适配层：无 LLM 时从中文对话文本确定性抽取显式偏好。

        仅在结构化偏好与 PreferenceExtractor 均无输出时作为兜底，
        保证前端 demo 在云端 LLM 暂时不可用时也能沉淀常见写作/输出偏好。
        """
        text = (event.text or "").strip()
        if not text:
            return []
        user_id = event.user_id or "default"
        quality = getattr(event, "quality", None)
        quality_score = float(getattr(quality, "score", 1.0) or 1.0)
        prefs: list[PreferenceMemory] = []
        idx = 0

        def _new(
            text_: str, ptype: str, *, global_: bool, tags: list[str]
        ) -> PreferenceMemory:
            nonlocal idx
            idx += 1
            return PreferenceMemory(
                memory_id=f"pref_{event.event_id}_d{idx}",
                user_id=user_id,
                preference_type=ptype,
                text=text_,
                scope=SceneScope(
                    scene="*" if global_ else event.scene,
                    task_type="*" if global_ else event.task_type,
                ),
                is_global=global_,
                confidence=0.95,
                quality_score=quality_score,
                extract_source="explicit_feedback",
                tags=tags,
                # 携带事件证据链，让统一四因子公式参与计算
                evidences=[build_event_evidence(event)],
            )

        lang_map = {
            "中文": "中文",
            "汉语": "中文",
            "英文": "英语",
            "英语": "英语",
            "法语": "法语",
            "日语": "日语",
            "德语": "德语",
            "韩语": "韩语",
        }
        lang_match = re.search(r"使用?(中文|汉语|英文|英语|法语|日语|德语|韩语)", text)
        if lang_match:
            prefs.append(
                _new(
                    f"项目材料默认使用{lang_map[lang_match.group(1)]}。",
                    "language_preference",
                    global_=True,
                    tags=["语言", lang_map[lang_match.group(1)]],
                )
            )

        if re.search(r"简洁|简略|简要|精炼|紧凑|不要太详|不要啰嗦", text):
            prefs.append(
                _new(
                    "内容尽量保持简洁。",
                    "output_style",
                    global_=True,
                    tags=["简洁", "风格"],
                )
            )

        has_conclusion = re.search(r"先给?结论|结论先行|先.{0,6}结论", text) is not None
        has_bullet = re.search(r"列?要点|列表|分点|条目", text) is not None
        if has_conclusion or has_bullet:
            prefs.append(
                _new(
                    "先给结论，再列要点。",
                    "output_style",
                    global_=True,
                    tags=["结构", "要点"],
                )
            )

        if re.search(r"正式|详细|详尽|书面", text):
            prefs.append(
                _new(
                    "采用正式、详细的表达方式。",
                    "scene_preference",
                    global_=False,
                    tags=["正式", "详细"],
                )
            )

        return prefs

    @staticmethod
    def _recalculate_knowledge_confidence(memory: KnowledgeMemory) -> None:
        """结构化知识写路径强制重算置信度。

        raw payload 中的 confidence 不作为真实置信度；与 MemoryWriteService 的
        写入收口点共用 KnowledgeConfidenceCalculator.from_memory，保证同一份
        记忆无论从哪条路径写入，落库置信度都一致。
        """
        memory.confidence = KnowledgeConfidenceCalculator().from_memory(memory)

    def _save_preference(self, memory) -> None:
        """Persist through Domain Writer; event processing has no direct repository bypass."""
        self._writer().upsert_memory(memory)

    def _save_knowledge(self, memory) -> None:
        """Persist through Domain Writer; event processing has no direct repository bypass."""
        self._writer().upsert_memory(memory)

    def _writer(self):
        if self.memory_write_service is None:
            from memoryhub.core.memory_write import MemoryWriteService

            self.memory_write_service = MemoryWriteService(
                pref_repo=self.pref_repo,
                know_repo=self.know_repo,
            )
        return self.memory_write_service

    def _notify(self, memory: object) -> None:
        if self.on_memory_written is not None:
            self.on_memory_written(memory)
