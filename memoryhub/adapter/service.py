"""Minimal working memory service used by the REST adapter."""

from __future__ import annotations

import re
import time

from sqlalchemy import func

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryDecision,
    MemoryStatus,
    PreferenceMemory,
    QualityStatus,
    SceneScope,
    SearchRequest,
    SearchResponse,
    SearchResult,
    WriteEventRequest,
    WriteEventResponse,
)
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.storage.database import (
    Database,
    EventRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.models import EventRow, PreferenceRow


class MemoryService:
    """A small persistent vertical slice for Agent integration tests."""

    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.events = EventRepository(self.db)
        self.preferences = PreferenceRepository(self.db)
        self.knowledge = KnowledgeRepository(self.db)
        self.preference_extractor = PreferenceExtractor()
        self._writer = None

    def _write_service(self):
        """Lazy unified write service so the degraded fallback never writes bare repos.

        Both repositories share this service's Database, so DomainMemoryWriter is
        built and preference writes get transactional lineage/evidence/outbox
        (R6: no production write bypass via direct repository save)."""
        if self._writer is None:
            from memoryhub.core.memory_write import MemoryWriteService

            self._writer = MemoryWriteService(
                pref_repo=self.preferences,
                know_repo=self.knowledge,
            )
        return self._writer

    def start(self) -> None:
        self.db.init_schema()

    def close(self) -> None:
        self.db.close()

    def health(self) -> dict:
        with self.db.session() as session:
            event_count = session.query(func.count(EventRow.event_id)).scalar() or 0
            preference_count = (
                session.query(func.count(PreferenceRow.memory_id)).scalar() or 0
            )
        return {
            "status": "healthy",
            "storage": "sqlite",
            "event_count": event_count,
            "preference_count": preference_count,
        }

    def write_events(self, request: WriteEventRequest) -> WriteEventResponse:
        accepted_ids: list[str] = []
        rejected = 0
        seen_event_ids: set[str] = set()
        seen_hashes: set[str] = set()

        for event in request.events:
            duplicate = (
                event.event_id in seen_event_ids
                or event.source_hash in seen_hashes
                or self.events.get_by_id(event.event_id) is not None
            )
            if duplicate or event.quality.status is not QualityStatus.ACCEPTED:
                rejected += 1
                continue

            seen_event_ids.add(event.event_id)
            seen_hashes.add(event.source_hash)
            self.events.save(event)
            accepted_ids.append(event.event_id)

            for preference in self.preference_extractor.extract(event):
                self._save_preference_version(preference)

        return WriteEventResponse(
            accepted=len(accepted_ids),
            rejected=rejected,
            event_ids=accepted_ids,
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        started = time.perf_counter()
        preference_memories = self.preferences.get_active(
            request.user_id, request.context.scene
        )
        knowledge_memories = self.knowledge.get_by_type(request.user_id)

        ranked: list[tuple[float, str, PreferenceMemory | KnowledgeMemory]] = []
        for preference in preference_memories:
            if preference.confidence < request.min_confidence:
                continue
            if not self._scope_matches(preference.scope, request.context):
                continue
            score = self._memory_score(
                request.query,
                preference.text,
                preference.scope,
                request.context,
            )
            ranked.append((score, "preference", preference))

        for knowledge in knowledge_memories:
            if knowledge.confidence < request.min_confidence:
                continue
            if not self._scope_matches(knowledge.scope, request.context):
                continue
            searchable = " ".join(
                part
                for part in (
                    knowledge.name,
                    knowledge.content,
                    " ".join(knowledge.steps),
                )
                if part
            )
            score = self._memory_score(
                request.query, searchable, knowledge.scope, request.context
            )
            ranked.append((score, "knowledge", knowledge))

        if request.memory_types:
            allowed = set(request.memory_types)
            ranked = [item for item in ranked if item[1] in allowed]

        ranked.sort(key=lambda item: (item[0], item[2].updated_at), reverse=True)
        selected = ranked[: max(request.top_k, 0)]
        results: list[SearchResult] = []
        selected_preferences: list[PreferenceMemory] = []
        selected_knowledge: list[KnowledgeMemory] = []

        for score, memory_type, memory in selected:
            if memory_type == "preference":
                selected_preferences.append(memory)
                content = memory.text
            else:
                selected_knowledge.append(memory)
                content = memory.content or memory.name
            results.append(
                SearchResult(
                    memory_id=memory.memory_id,
                    memory_type=memory_type,
                    content=content,
                    score=round(score, 6),
                    source="keyword+metadata",
                    metadata={
                        "scene": memory.scope.scene,
                        "task_type": memory.scope.task_type,
                        "confidence": memory.confidence,
                    },
                )
            )

        return SearchResponse(
            results=results,
            preferences=selected_preferences,
            knowledge=selected_knowledge,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            total_count=len(results),
        )

    def context(self, request: SearchRequest) -> tuple[str, SearchResponse]:
        response = self.search(request)
        if not response.preferences and not response.knowledge:
            return "未检索到与当前任务相关的长期记忆。", response

        lines = ["以下是与当前任务相关的用户记忆，请在不违背本轮明确指令时参考："]
        if response.preferences:
            lines.append("用户偏好：")
            lines.extend(
                f"- {preference.text}" for preference in response.preferences
            )
        if response.knowledge:
            lines.append("可复用知识：")
            for knowledge in response.knowledge:
                detail = knowledge.content or "；".join(knowledge.steps)
                lines.append(f"- {knowledge.name}: {detail}".rstrip(": "))
        return "\n".join(lines), response

    def list_preferences(
        self,
        user_id: str,
        scene: str = "",
        status: str = "active",
    ) -> list[PreferenceMemory]:
        if status == "active":
            return self.preferences.get_active(user_id, scene)
        return [
            memory
            for memory in self.preferences.list_all(status=status, user_id=user_id)
        ]

    def _save_preference_version(self, preference: PreferenceMemory) -> None:
        existing = self.preferences.get_by_scope(
            preference.user_id,
            preference.scope.scene,
            preference.scope.task_type,
        )
        same_type = [
            memory
            for memory in existing
            if memory.preference_type == preference.preference_type
        ]
        writer = self._write_service()
        if same_type:
            latest = max(same_type, key=lambda memory: memory.version)
            if latest.text.strip().lower() == preference.text.strip().lower():
                return
            # Archive superseded versions through the unified writer so lifecycle
            # transitions are recorded in lineage and projected consistently.
            for memory in same_type:
                memory.status = MemoryStatus.ARCHIVED
                writer.upsert_memory(memory, action=MemoryDecision.SUPERSEDE)
            preference.version = latest.version + 1
            preference.parent_id = latest.memory_id
            preference.root_id = latest.root_id or latest.memory_id
            writer.upsert_memory(preference, action=MemoryDecision.SUPERSEDE)
        else:
            writer.upsert_memory(preference, action=MemoryDecision.NEW)

    @staticmethod
    def _scope_matches(memory_scope: SceneScope, request_scope: SceneScope) -> bool:
        if (
            memory_scope.scene
            and request_scope.scene
            and memory_scope.scene != "*"
            and memory_scope.scene != request_scope.scene
        ):
            return False
        if (
            memory_scope.task_type
            and request_scope.task_type
            and memory_scope.task_type != "*"
            and memory_scope.task_type != request_scope.task_type
        ):
            return False
        return True

    @classmethod
    def _memory_score(
        cls,
        query: str,
        content: str,
        memory_scope: SceneScope,
        request_scope: SceneScope,
    ) -> float:
        query_tokens = cls._tokens(query)
        content_tokens = cls._tokens(content)
        overlap = len(query_tokens & content_tokens)
        lexical = overlap / max(len(query_tokens), 1)
        if query and query.lower() in content.lower():
            lexical = max(lexical, 0.8)

        scope_score = 0.0
        if request_scope.scene and memory_scope.scene == request_scope.scene:
            scope_score += 0.25
        if (
            request_scope.task_type
            and memory_scope.task_type == request_scope.task_type
        ):
            scope_score += 0.45
        return min(1.0, lexical * 0.6 + scope_score + 0.05)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        words = set(re.findall(r"[a-z0-9_]+", lowered))
        chinese = re.findall(r"[\u4e00-\u9fff]", lowered)
        words.update(chinese)
        words.update(
            "".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)
        )
        return words
