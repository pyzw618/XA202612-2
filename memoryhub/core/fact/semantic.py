"""Facts semantic facade over the existing Knowledge repository."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .conflict import FactConflictDetector
from .models import EntityType, FactDecisionRequired, PredicateDef
from .normalizer import EntityNormalizer, PredicateNormalizer


@dataclass
class FactSemanticResult:
    relation: str
    subject_id: str = ""
    predicate_id: str = ""
    object_id: str = ""
    existing_memory_ids: list[str] = field(default_factory=list)
    reason: str = ""
    conflict_type: str = ""
    decision_task: dict | None = None


def _load_definitions() -> list[PredicateDef]:
    path = Path(__file__).with_name("predicate_ontology.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"predicates": []}
    return [PredicateDef(**item) for item in data.get("predicates", [])]


class FactSemanticService:
    """Prepare and check a FACT without performing its business write.

    ``KnowledgeUpdater`` owns the final write.  This separation keeps entity
    resolution and conflict checks reusable by REST, Agent, and vNext paths.
    """

    def __init__(self, *, knowledge_repo, semantic_repo):
        self.knowledge_repo = knowledge_repo
        self.repository = semantic_repo
        for predicate in _load_definitions():
            if self.repository.get_predicate(predicate.predicate_id) is None:
                self.repository.save_predicate(predicate)
        self.entities = EntityNormalizer(self.repository)
        self.predicates = PredicateNormalizer(self.repository, _load_definitions())
        self.conflicts = FactConflictDetector(self.repository)

    @staticmethod
    def _tenant(memory) -> str:
        authority = dict(getattr(memory, "extra_payload", {}).get("vnext_authority", {}) or {})
        return str(authority.get("tenant_id") or "default")

    @staticmethod
    def _scope(memory) -> str:
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        project_id = str(payload.get("project_id") or "").strip()
        authority = dict(payload.get("vnext_authority", {}) or {})
        if not project_id and authority.get("scope_level") == "project":
            project_id = str(authority.get("scope") or "").strip()
        if project_id:
            return f"project:{project_id}"
        # A free-form scene is not a project identity.  Only explicit project
        # metadata can narrow the fact's scope.
        return "global"

    @staticmethod
    def _entity_type(value: str) -> str:
        value = str(value or EntityType.OTHER.value)
        return value if value in {item.value for item in EntityType} else EntityType.OTHER.value

    def prepare(self, memory, *, selected_subject_id: str | None = None,
                selected_predicate_id: str | None = None,
                selected_object_id: str | None = None) -> FactSemanticResult:
        tenant_id = self._tenant(memory)
        user_id = str(memory.user_id or "default")
        try:
            metadata = dict(getattr(memory, "extra_payload", {}) or {})
            subject_id = self.entities.normalize(
                memory.subject, self._entity_type(metadata.get("subject_type", "Other")),
                user_id=user_id, tenant_id=tenant_id, selected_id=selected_subject_id,
            )
            predicate_id = self.predicates.normalize(
                memory.predicate, selected_id=selected_predicate_id
            )
            predicate = self.repository.get_predicate(predicate_id)
            if predicate is not None and getattr(memory, "single_value", None) is not None:
                predicate.single_value = bool(memory.single_value)
                self.repository.save_predicate(predicate)
            if selected_object_id:
                object_id = selected_object_id
                if self.repository.get_entity(object_id, tenant_id, user_id) is None:
                    raise ValueError("fact.object_selection_invalid")
            else:
                object_id = self.entities.normalize(
                    memory.object_value, self._entity_type(memory.object_type),
                    user_id=user_id, tenant_id=tenant_id,
                )
        except FactDecisionRequired as exc:
            return FactSemanticResult(
                relation="DECISION_REQUIRED", reason=exc.reason,
                decision_task=exc.to_dict(),
            )

        result = self.conflicts.check(
            user_id=user_id, tenant_id=tenant_id, scope=self._scope(memory),
            subject_id=subject_id, predicate_id=predicate_id, object_id=object_id,
            memory=memory,
        )
        return FactSemanticResult(
            relation=result.relation, subject_id=subject_id,
            predicate_id=predicate_id, object_id=object_id,
            existing_memory_ids=[getattr(item, "memory_id", "") for item in result.existing],
            reason=result.reason, conflict_type=result.conflict_type,
        )

    def bind(self, memory, result: FactSemanticResult) -> None:
        if result.relation == "DECISION_REQUIRED":
            return
        tenant_id = self._tenant(memory)
        self.repository.bind(
            memory, tenant_id=tenant_id, scope=self._scope(memory),
            subject_id=result.subject_id, predicate_id=result.predicate_id,
            object_id=result.object_id,
        )
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        payload["fact_semantic"] = {
            "subject_id": result.subject_id,
            "predicate_id": result.predicate_id,
            "object_id": result.object_id,
            "scope": self._scope(memory),
        }
        memory.extra_payload = payload

    def ensure_memory_binding(self, memory) -> FactSemanticResult | None:
        """Backfill bindings for legacy FACT rows without running conflict checks."""
        semantic = dict(getattr(memory, "extra_payload", {}).get("fact_semantic", {}) or {})
        if semantic.get("subject_id") and semantic.get("predicate_id") and semantic.get("object_id"):
            return FactSemanticResult("BOUND", **{
                key: semantic.get(key, "")
                for key in ("subject_id", "predicate_id", "object_id")
            })
        tenant_id = self._tenant(memory)
        user_id = str(memory.user_id or "default")
        try:
            subject_id = self.entities.normalize(memory.subject, "Other", user_id=user_id, tenant_id=tenant_id)
            predicate_id = self.predicates.normalize(memory.predicate)
            object_id = self.entities.normalize(memory.object_value, self._entity_type(memory.object_type), user_id=user_id, tenant_id=tenant_id)
        except (FactDecisionRequired, ValueError):
            return None
        result = FactSemanticResult("BOUND", subject_id, predicate_id, object_id)
        self.bind(memory, result)
        return result

    def set_status(self, memory_id: str, status: str) -> None:
        self.repository.set_binding_status(memory_id, status)

    def save_decision(self, memory, task: dict) -> str:
        decision_id = f"fact-decision:{memory.memory_id}"
        self.repository.save_decision(
            decision_id=decision_id, tenant_id=self._tenant(memory),
            user_id=str(memory.user_id or "default"), memory_id=memory.memory_id,
            task_type=str(task.get("decision_type") or "fact_conflict"),
            payload=task, expected_version=max(1, int(memory.version)),
        )
        return decision_id
