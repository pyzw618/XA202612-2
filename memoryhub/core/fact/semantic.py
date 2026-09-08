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
    tenant_id: str = "default"
    scope: str = "global"
    subject_id: str = ""
    predicate_id: str = ""
    object_id: str = ""
    existing_memory_ids: list[str] = field(default_factory=list)
    reason: str = ""
    conflict_type: str = ""
    conflict_types: list[str] = field(default_factory=list)
    pending_operations: list[dict] = field(default_factory=list)
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
                try:
                    self.repository.save_predicate(
                        predicate, tenant_id="__ontology__", user_id="__ontology__",
                        built_in=True,
                    )
                except TypeError:
                    self.repository.save_predicate(predicate)
        self.entities = EntityNormalizer(self.repository)
        self.predicates = PredicateNormalizer(self.repository, _load_definitions())
        self.conflicts = FactConflictDetector(self.repository)

    @staticmethod
    def _tenant(memory) -> str:
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        authority = dict(payload.get("vnext_authority", {}) or {})
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
                selected_object_id: str | None = None,
                force_new_subject: bool = False,
                force_new_predicate: bool = False,
                force_new_object: bool = False) -> FactSemanticResult:
        tenant_id = self._tenant(memory)
        user_id = str(memory.user_id or "default")
        pending_operations: list[dict] = []
        resolution_field = "subject"
        try:
            metadata = dict(getattr(memory, "extra_payload", {}) or {})
            subject_id = self.entities.normalize(
                memory.subject, self._entity_type(metadata.get("subject_type", "Other")),
                user_id=user_id, tenant_id=tenant_id, selected_id=selected_subject_id,
                force_new=force_new_subject,
                persist=False, pending_operations=pending_operations,
            )
            resolution_field = "predicate"
            predicate_id = self.predicates.normalize(
                memory.predicate,
                selected_id=selected_predicate_id,
                tenant_id=tenant_id,
                user_id=user_id,
                force_new=force_new_predicate,
                persist=False, pending_operations=pending_operations,
            )
            resolution_field = "object"
            if selected_object_id:
                object_id = selected_object_id
                selected_object = self.repository.get_entity(object_id, tenant_id, user_id)
                object_type = self._entity_type(memory.object_type)
                if selected_object is None or (
                    object_type != EntityType.OTHER.value
                    and selected_object.entity_type != object_type
                ):
                    raise ValueError("fact.object_selection_invalid")
            else:
                object_id = self.entities.normalize(
                    memory.object_value, self._entity_type(memory.object_type),
                    user_id=user_id, tenant_id=tenant_id,
                    force_new=force_new_object,
                    persist=False, pending_operations=pending_operations,
                )
        except FactDecisionRequired as exc:
            decision_task = exc.to_dict()
            decision_task["field"] = resolution_field
            return FactSemanticResult(
                relation="DECISION_REQUIRED", tenant_id=tenant_id,
                scope=self._scope(memory), reason=exc.reason,
                decision_task=decision_task,
            )

        entity_types = {
            operation["entity"].entity_id: operation["entity"].entity_type
            for operation in pending_operations
            if operation.get("kind") == "entity_create"
        }
        result = self.conflicts.check(
            user_id=user_id, tenant_id=tenant_id, scope=self._scope(memory),
            subject_id=subject_id, predicate_id=predicate_id, object_id=object_id,
            memory=memory,
            single_value_override=getattr(memory, "single_value", None),
            subject_type=entity_types.get(subject_id),
            object_type=entity_types.get(object_id),
        )
        return FactSemanticResult(
            relation=result.relation, tenant_id=tenant_id,
            scope=self._scope(memory), subject_id=subject_id,
            predicate_id=predicate_id, object_id=object_id,
            existing_memory_ids=[getattr(item, "memory_id", "") for item in result.existing],
            reason=result.reason, conflict_type=result.conflict_type,
            conflict_types=list(getattr(result, "conflict_types", []) or []),
            pending_operations=pending_operations,
        )

    def commit(self, memory, result: FactSemanticResult) -> None:
        """Materialize only the operations accepted by the write path.

        ``prepare`` deliberately performs no writes.  This method is called
        after the Knowledge row has passed the safety gate and the semantic
        outcome is NEW/COEXIST/DUPLICATE, so an ambiguous or rejected proposal
        cannot register an unconfirmed alias or entity.
        """
        for operation in result.pending_operations or []:
            kind = operation.get("kind")
            if kind == "entity_create":
                self.repository.save_entity(operation["entity"])
            elif kind == "entity_alias":
                self.repository.add_alias(
                    operation["entity_id"], operation["alias"],
                    operation["tenant_id"], operation["user_id"],
                )
            elif kind == "predicate_create":
                self.repository.save_predicate(
                    operation["predicate"], tenant_id=operation["tenant_id"],
                    user_id=operation["user_id"],
                )
            elif kind == "predicate_alias":
                self.repository.add_predicate_alias(
                    operation["predicate_id"], operation["alias"],
                    operation["tenant_id"], operation["user_id"],
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
        authority = payload.get("vnext_authority")
        if isinstance(authority, dict):
            authority = dict(authority)
            authority["content"] = {
                **dict(authority.get("content", {}) or {}),
                "fact_semantic": payload["fact_semantic"],
            }
            payload["vnext_authority"] = authority
        memory.extra_payload = payload

    def ensure_memory_binding(self, memory) -> FactSemanticResult | None:
        """Backfill bindings for legacy FACT rows without running conflict checks."""
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        semantic = dict(payload.get("fact_semantic", {}) or {})
        if semantic.get("subject_id") and semantic.get("predicate_id") and semantic.get("object_id"):
            tenant_id = self._tenant(memory)
            user_id = str(memory.user_id or "default")
            existing = getattr(self.repository, "get_binding", lambda *_args: None)(
                memory.memory_id, tenant_id, user_id
            )
            if existing is not None:
                return FactSemanticResult("BOUND", tenant_id=tenant_id,
                                          scope=self._scope(memory), **{
                key: semantic.get(key, "")
                for key in ("subject_id", "predicate_id", "object_id")
                })
            result = FactSemanticResult(
                "BOUND", tenant_id=tenant_id, scope=self._scope(memory),
                subject_id=semantic["subject_id"],
                predicate_id=semantic["predicate_id"],
                object_id=semantic["object_id"],
            )
            self.bind(memory, result)
            return result
        tenant_id = self._tenant(memory)
        user_id = str(memory.user_id or "default")
        try:
            subject_id = self.entities.normalize(memory.subject, "Other", user_id=user_id, tenant_id=tenant_id)
            predicate_id = self.predicates.normalize(
                memory.predicate, tenant_id=tenant_id, user_id=user_id
            )
            object_id = self.entities.normalize(memory.object_value, self._entity_type(memory.object_type), user_id=user_id, tenant_id=tenant_id)
        except (FactDecisionRequired, ValueError):
            return None
        result = FactSemanticResult(
            "BOUND", tenant_id=tenant_id, scope=self._scope(memory),
            subject_id=subject_id, predicate_id=predicate_id, object_id=object_id,
        )
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
