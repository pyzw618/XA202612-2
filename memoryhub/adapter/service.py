"""Minimal working memory service used by the REST adapter."""

from __future__ import annotations

import re
import time
from datetime import datetime

from sqlalchemy import func

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryEvent,
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
from memoryhub.storage.models import EventRow, KnowledgeRow, PreferenceRow


class MemoryService:
    """A small persistent vertical slice for Agent integration tests."""

    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.events = EventRepository(self.db)
        self.preferences = PreferenceRepository(self.db)
        self.knowledge = KnowledgeRepository(self.db)
        self.preference_extractor = PreferenceExtractor()

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
            self.events.save(self._event_to_row(event))
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
        preference_rows = self.preferences.get_active(
            request.user_id, request.context.scene
        )
        knowledge_rows = self.knowledge.get_by_type(request.user_id)

        ranked: list[tuple[float, str, PreferenceMemory | KnowledgeMemory]] = []
        for row in preference_rows:
            preference = self._row_to_preference(row)
            if preference.confidence < request.min_confidence:
                continue
            if not self._scope_matches(preference.scope, request.context):
                continue
            score = self._memory_score(
                request.query,
                preference.content,
                preference.scope,
                request.context,
            )
            ranked.append((score, "preference", preference))

        for row in knowledge_rows:
            knowledge = self._row_to_knowledge(row)
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
                content = memory.content
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
                f"- {preference.content}" for preference in response.preferences
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
            rows = self.preferences.get_active(user_id, scene)
        else:
            with self.db.session() as session:
                query = session.query(PreferenceRow).filter(
                    PreferenceRow.user_id == user_id,
                    PreferenceRow.status == status,
                )
                if scene:
                    query = query.filter(PreferenceRow.scope_scene == scene)
                rows = list(query.order_by(PreferenceRow.updated_at.desc()).all())
        return [self._row_to_preference(row) for row in rows]

    def _save_preference_version(self, preference: PreferenceMemory) -> None:
        existing = self.preferences.get_by_scope(
            preference.user_id,
            preference.scope.scene,
            preference.scope.task_type,
        )
        same_type = [
            row
            for row in existing
            if row.preference_type == preference.preference_type.value
        ]
        if same_type:
            latest = max(same_type, key=lambda row: row.version)
            if latest.content.strip().lower() == preference.content.strip().lower():
                return
            for row in same_type:
                self.preferences.update_status(
                    row.memory_id, MemoryStatus.ARCHIVED.value
                )
            preference.version = latest.version + 1
            preference.parent_id = latest.memory_id
        self.preferences.save(self._preference_to_row(preference))

    @staticmethod
    def _scope_matches(memory_scope: SceneScope, request_scope: SceneScope) -> bool:
        if (
            memory_scope.scene
            and request_scope.scene
            and memory_scope.scene != request_scope.scene
        ):
            return False
        if (
            memory_scope.task_type
            and request_scope.task_type
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

    @staticmethod
    def _event_to_row(event: MemoryEvent) -> EventRow:
        occurred_at = datetime.strptime(event.occurred_at, "%Y-%m-%dT%H:%M:%SZ")
        return EventRow(
            event_id=event.event_id,
            source_type=event.source_type.value,
            event_type=event.event_type,
            user_id=event.user_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            scene=event.scene,
            task_type=event.task_type,
            occurred_at=occurred_at,
            text=event.text,
            payload=event.payload,
            tool_calls=[call.model_dump(mode="json") for call in event.tool_calls],
            schema_version=event.schema_version,
            source_hash=event.source_hash,
            redactions=event.redactions,
            quality=event.quality.model_dump(mode="json"),
        )

    @staticmethod
    def _preference_to_row(preference: PreferenceMemory) -> PreferenceRow:
        return PreferenceRow(
            memory_id=preference.memory_id,
            user_id=preference.user_id,
            memory_type=preference.memory_type,
            preference_type=preference.preference_type.value,
            content=preference.content,
            scope_scene=preference.scope.scene,
            scope_task_type=preference.scope.task_type,
            scope_app=preference.scope.app,
            confidence=preference.confidence,
            status=preference.status.value,
            level=preference.level.value,
            version=preference.version,
            parent_id=preference.parent_id,
            evidences=[
                evidence.model_dump(mode="json") for evidence in preference.evidences
            ],
            created_at=preference.created_at,
            updated_at=preference.updated_at,
        )

    @staticmethod
    def _row_to_preference(row: PreferenceRow) -> PreferenceMemory:
        return PreferenceMemory.model_validate(
            {
                "memory_id": row.memory_id,
                "user_id": row.user_id,
                "memory_type": row.memory_type,
                "preference_type": row.preference_type,
                "content": row.content,
                "scope": {
                    "scene": row.scope_scene,
                    "task_type": row.scope_task_type,
                    "app": row.scope_app,
                },
                "confidence": row.confidence,
                "status": row.status,
                "level": row.level,
                "version": row.version,
                "parent_id": row.parent_id or "",
                "evidences": row.evidences or [],
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    @staticmethod
    def _row_to_knowledge(row: KnowledgeRow) -> KnowledgeMemory:
        return KnowledgeMemory.model_validate(
            {
                "memory_id": row.memory_id,
                "user_id": row.user_id,
                "memory_type": row.memory_type,
                "knowledge_type": row.knowledge_type,
                "name": row.name,
                "content": row.content,
                "steps": row.steps or [],
                "tools": row.tools or [],
                "template_body": row.template_body or "",
                "scope": {
                    "scene": row.scope_scene,
                    "task_type": row.scope_task_type,
                    "app": row.scope_app,
                },
                "confidence": row.confidence,
                "success_count": row.success_count,
                "total_count": row.total_count,
                "status": row.status,
                "level": row.level,
                "version": row.version,
                "parent_id": row.parent_id or "",
                "evidences": row.evidences or [],
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
