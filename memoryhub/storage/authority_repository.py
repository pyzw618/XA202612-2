"""Tenant-scoped Long-Term Authority adapter over legacy memory tables."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    KnowledgeType,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
    PreferenceType,
    SceneScope,
)
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
)
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
    _know_row_to_pydantic,
    _pref_row_to_pydantic,
)
from memoryhub.storage.models import KnowledgeRow, PreferenceRow


class AuthorityRepositoryError(ValueError):
    """Base error for Authority persistence failures."""


class AuthorityActiveVersionConflict(AuthorityRepositoryError):
    """There is already an ACTIVE version in the same tenant/scope chain."""


class AuthorityRepository:
    """Expose Preference/Knowledge as one vNext Long-Term Authority surface.

    vNext metadata is carried in the legacy row's additive tenant and
    ``extra_payload`` fields.  The underlying rows remain the compatibility
    Authority adapter; no second long-term business table is introduced.
    """

    def __init__(
        self,
        db: Database,
        *,
        preference_repository: PreferenceRepository | None = None,
        knowledge_repository: KnowledgeRepository | None = None,
    ) -> None:
        self.db = db
        self.preference_repository = preference_repository or PreferenceRepository(db)
        self.knowledge_repository = knowledge_repository or KnowledgeRepository(db)

    def save(
        self, envelope: LongTermEnvelope, *, session: Session | None = None
    ) -> LongTermEnvelope:
        """Persist a validated envelope through the legacy repository adapter."""
        if not isinstance(envelope, LongTermEnvelope):
            raise TypeError("authority repository requires LongTermEnvelope")

        if session is None:
            with self.db.session() as managed_session:
                self._save(managed_session, envelope)
            return envelope
        self._save(session, envelope)
        return envelope

    def _save(self, session: Session, envelope: LongTermEnvelope) -> None:
        current = self._get_in_session(
            session,
            tenant_id=envelope.tenant_id,
            user_id=envelope.user_id,
            memory_id=envelope.memory_id,
        )
        if current is not None:
            if current.model_dump(mode="json") == envelope.model_dump(mode="json"):
                return
            if envelope.content_version <= current.content_version:
                raise AuthorityRepositoryError(
                    f"memory {envelope.memory_id} content_version must increase"
                )

        if envelope.evolution_status is EvolutionStatus.ACTIVE:
            for sibling in self._list_in_session(
                session,
                tenant_id=envelope.tenant_id,
                user_id=envelope.user_id,
                include_inactive=True,
            ):
                if (
                    sibling.memory_id != envelope.memory_id
                    and sibling.evolution_status is EvolutionStatus.ACTIVE
                    and self._chain_key(sibling) == self._chain_key(envelope)
                ):
                    raise AuthorityActiveVersionConflict(
                        "an Authority version chain may have at most one ACTIVE version"
                    )

        legacy = self.to_legacy_memory(envelope)
        if envelope.memory_type is MemoryType.PREFERENCE:
            self.preference_repository.save(legacy, session=session)  # type: ignore[arg-type]
        else:
            self.knowledge_repository.save(legacy, session=session)  # type: ignore[arg-type]
        # Preserve the existing projection_version column; Authority writes never
        # artificially inflate it. The projection worker owns column updates.
        self._preserve_projection_version(session, envelope)

    def get(
        self,
        *,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        include_inactive: bool = False,
    ) -> LongTermEnvelope | None:
        with self.db.session() as session:
            envelope = self._get_in_session(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                memory_id=memory_id,
            )
            if envelope is None or (
                not include_inactive and envelope.evolution_status is not EvolutionStatus.ACTIVE
            ):
                return None
            return envelope

    def list(
        self,
        *,
        tenant_id: str,
        user_id: str,
        include_inactive: bool = False,
        memory_type: MemoryType | str | None = None,
    ) -> list[LongTermEnvelope]:
        with self.db.session() as session:
            values = self._list_in_session(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                include_inactive=include_inactive,
            )
        if memory_type is not None:
            wanted = memory_type.value if isinstance(memory_type, MemoryType) else str(memory_type)
            values = [value for value in values if value.memory_type.value == wanted]
        return values

    def legacy_memory(
        self, envelope: LongTermEnvelope
    ) -> PreferenceMemory | KnowledgeMemory:
        """Return the legacy model used by MemoryWriteService/DomainMemoryWriter."""
        return self.to_legacy_memory(envelope)

    put = save
    read = get
    list_active = list

    @staticmethod
    def to_legacy_memory(envelope: LongTermEnvelope) -> PreferenceMemory | KnowledgeMemory:
        authority = envelope.model_dump(mode="json")
        metadata = {"vnext_authority": authority}
        scope = AuthorityRepository._legacy_scope(envelope)
        status = AuthorityRepository._legacy_status(envelope.evolution_status)
        common: dict[str, Any] = {
            "memory_id": envelope.memory_id,
            "user_id": envelope.user_id,
            "scope": scope,
            "confidence": envelope.confidence,
            "status": status,
            "level": MemoryLevel.LONG,
            "version": envelope.content_version,
            "evidences": [],
            "extra_payload": metadata,
            "created_at": envelope.created_at,
            "updated_at": envelope.updated_at,
        }
        # Carry projection_version in extra_payload metadata since legacy models
        # do not define the field directly.
        metadata["vnext_authority"]["projection_version"] = envelope.projection_version
        if envelope.memory_type is MemoryType.PREFERENCE:
            content = envelope.content
            text = content.get("text") or content.get("value") or json.dumps(
                content, ensure_ascii=False, sort_keys=True
            )
            payload = content.get("payload", content)
            preference_type = str(content.get("preference_type", "output_style"))
            try:
                preference_type = PreferenceType(preference_type)
            except ValueError:
                preference_type = PreferenceType.OUTPUT_STYLE
            return PreferenceMemory(
                **common,
                preference_type=preference_type,
                text=str(text),
                payload=dict(payload) if isinstance(payload, dict) else {"value": payload},
                is_global=envelope.scope_level is MemoryScope.GLOBAL,
                extract_source="vnext_authority",
            )

        content = envelope.content
        knowledge_type = {
            MemoryType.SEMANTIC: KnowledgeType.FACT,
            MemoryType.PROCEDURAL: KnowledgeType.WORKFLOW,
            MemoryType.EPISODIC: KnowledgeType.CASE,
        }[envelope.memory_type]
        return KnowledgeMemory(
            **common,
            knowledge_type=knowledge_type,
            name=str(content.get("name", envelope.normalized_key)),
            content=str(content.get("content", content.get("text", ""))),
            steps=[str(value) for value in content.get("steps", [])],
            tools=[str(value) for value in content.get("tools", [])],
            template_body=str(content.get("template_body", "")),
            subject=str(content.get("subject", "")),
            predicate=str(content.get("predicate", "")),
            object_value=str(content.get("object_value", "")),
            object_type=str(content.get("object_type", "")),
            single_value=content.get("single_value"),
        )

    def _preserve_projection_version(
        self, session: Session, envelope: LongTermEnvelope
    ) -> None:
        model = PreferenceRow if envelope.memory_type is MemoryType.PREFERENCE else KnowledgeRow
        row = (
            session.query(model)
            .filter_by(
                memory_id=envelope.memory_id,
                tenant_id=envelope.tenant_id,
                user_id=envelope.user_id,
            )
            .first()
        )
        if row is None:
            return
        # New rows start at 0; existing rows keep their current projection_version.
        if row.projection_version is None:
            row.projection_version = 0

    @staticmethod
    def _legacy_scope(envelope: LongTermEnvelope) -> SceneScope:
        if envelope.scope_level is MemoryScope.GLOBAL:
            return SceneScope()
        return SceneScope(scene=envelope.scope, task_type="", app="")

    @staticmethod
    def _legacy_status(status: EvolutionStatus) -> MemoryStatus:
        if status is EvolutionStatus.ACTIVE:
            return MemoryStatus.ACTIVE
        if status is EvolutionStatus.DELETED:
            return MemoryStatus.DELETED
        return MemoryStatus.ARCHIVED

    @staticmethod
    def _chain_key(envelope: LongTermEnvelope) -> tuple[str, str, str, str, str]:
        return (
            envelope.tenant_id,
            envelope.user_id,
            envelope.memory_type.value,
            envelope.normalized_key,
            f"{envelope.scope_level.value}:{envelope.scope}",
        )

    def _get_in_session(
        self, session: Session, *, tenant_id: str, user_id: str, memory_id: str
    ) -> LongTermEnvelope | None:
        pref = (
            session.query(PreferenceRow)
            .filter_by(memory_id=memory_id, tenant_id=tenant_id, user_id=user_id)
            .one_or_none()
        )
        if pref is not None:
            return self._from_legacy(
                _pref_row_to_pydantic(pref),
                tenant_id=tenant_id,
                projection_version=pref.projection_version,
            )
        know = (
            session.query(KnowledgeRow)
            .filter_by(memory_id=memory_id, tenant_id=tenant_id, user_id=user_id)
            .one_or_none()
        )
        if know is not None:
            return self._from_legacy(
                _know_row_to_pydantic(know),
                tenant_id=tenant_id,
                projection_version=know.projection_version,
            )
        return None

    def _list_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        user_id: str,
        include_inactive: bool,
    ) -> list[LongTermEnvelope]:
        prefs = (
            session.query(PreferenceRow)
            .filter_by(tenant_id=tenant_id, user_id=user_id)
            .all()
        )
        knows = (
            session.query(KnowledgeRow)
            .filter_by(tenant_id=tenant_id, user_id=user_id)
            .all()
        )
        values = [
            self._from_legacy(
                _pref_row_to_pydantic(row),
                tenant_id=tenant_id,
                projection_version=row.projection_version,
            )
            for row in prefs
        ] + [
            self._from_legacy(
                _know_row_to_pydantic(row),
                tenant_id=tenant_id,
                projection_version=row.projection_version,
            )
            for row in knows
        ]
        if not include_inactive:
            values = [
                value
                for value in values
                if value.evolution_status is EvolutionStatus.ACTIVE
            ]
        return sorted(values, key=lambda value: (value.updated_at, value.memory_id), reverse=True)

    @staticmethod
    def _from_legacy(
        memory: PreferenceMemory | KnowledgeMemory,
        *,
        tenant_id: str,
        projection_version: int | None = None,
    ) -> LongTermEnvelope:
        metadata = dict(getattr(memory, "extra_payload", {}) or {}).get("vnext_authority")
        if isinstance(metadata, dict):
            envelope = LongTermEnvelope.model_validate(metadata)
            # Column value wins if set; otherwise fall back to metadata.
            if projection_version and projection_version > 0:
                envelope.projection_version = projection_version
            return envelope

        if isinstance(memory, PreferenceMemory):
            memory_type = MemoryType.PREFERENCE
            content: dict[str, Any] = {
                "text": memory.text,
                "payload": memory.payload,
                "preference_type": str(memory.preference_type),
            }
            scope_level = MemoryScope.GLOBAL if memory.is_global else MemoryScope.PROJECT
            scope = memory.scope.scene or memory.scope.task_type or ""
        else:
            type_map = {
                KnowledgeType.FACT: MemoryType.SEMANTIC,
                KnowledgeType.WORKFLOW: MemoryType.PROCEDURAL,
                KnowledgeType.TEMPLATE: MemoryType.PROCEDURAL,
                KnowledgeType.CASE: MemoryType.EPISODIC,
            }
            memory_type = type_map.get(memory.knowledge_type, MemoryType.SEMANTIC)
            content = {
                "name": memory.name,
                "content": memory.content,
                "steps": memory.steps,
                "tools": memory.tools,
                "template_body": memory.template_body,
                "subject": memory.subject,
                "predicate": memory.predicate,
                "object_value": memory.object_value,
                "object_type": memory.object_type,
            }
            scope_level = MemoryScope.PROJECT
            scope = memory.scope.scene or memory.scope.task_type or ""
        status_map = {
            MemoryStatus.ACTIVE: EvolutionStatus.ACTIVE,
            MemoryStatus.DELETED: EvolutionStatus.DELETED,
            MemoryStatus.ARCHIVED: EvolutionStatus.ARCHIVED,
            MemoryStatus.PENDING: EvolutionStatus.DORMANT,
        }
        return LongTermEnvelope(
            tenant_id=tenant_id,
            user_id=memory.user_id,
            memory_id=memory.memory_id,
            memory_type=memory_type,
            normalized_key=memory.memory_id,
            content=content,
            scope_level=scope_level,
            scope=scope or "legacy",
            evolution_status=status_map.get(memory.status, EvolutionStatus.DORMANT),
            confidence=float(memory.confidence),
            utility=0.0,
            projection_version=projection_version or 0,
            evidence_refs=[
                str(item.get("evidence_id", "legacy"))
                for item in (memory.evidences or [])
                if isinstance(item, dict)
            ]
            or [f"legacy:{memory.memory_id}"],
            created_at=memory.created_at or datetime.now(),
            updated_at=memory.updated_at or datetime.now(),
        )


LongTermAuthorityRepository = AuthorityRepository


__all__ = [
    "AuthorityActiveVersionConflict",
    "AuthorityRepository",
    "AuthorityRepositoryError",
    "LongTermAuthorityRepository",
]
