"""Relationship-aware deterministic conflict detection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FactConflictResult:
    relation: str
    existing: list[object] = field(default_factory=list)
    reason: str = ""
    conflict_type: str = ""


class FactConflictDetector:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _key(subject_id: str, predicate, object_id: str) -> tuple[str, str, str]:
        predicate_id = predicate.predicate_id
        left, right = subject_id, object_id
        if predicate.symmetric:
            left, right = sorted((left, right))
        elif predicate.inverse_of and predicate_id > predicate.inverse_of:
            predicate_id, left, right = predicate.inverse_of, right, left
        return predicate_id, left, right

    def check(self, *, user_id: str, tenant_id: str, scope: str,
              subject_id: str, predicate_id: str, object_id: str,
              memory=None) -> FactConflictResult:
        predicate = self.repository.get_predicate(predicate_id)
        if predicate is None:
            return FactConflictResult("NEW")
        if subject_id == object_id and predicate.irreflexive:
            return FactConflictResult("CONFLICT", reason="关系不允许主体与客体相同",
                                      conflict_type="irreflexive_violation")
        subject = self.repository.get_entity(subject_id, tenant_id, user_id)
        obj = self.repository.get_entity(object_id, tenant_id, user_id)
        if subject is not None and predicate.domain and subject.entity_type not in {"Other", *predicate.domain}:
            return FactConflictResult("CONFLICT", reason="主体类型不符合谓词 domain",
                                      conflict_type="domain_type_violation")
        if obj is not None and predicate.range and obj.entity_type not in {"Other", *predicate.range}:
            return FactConflictResult("CONFLICT", reason="客体类型不符合谓词 range",
                                      conflict_type="range_type_violation")
        existing = self.repository.list_bindings(user_id, tenant_id, scope)
        new_key = self._key(subject_id, predicate, object_id)
        related = []
        for binding in existing:
            old_pred = self.repository.get_predicate(binding.predicate_id)
            if old_pred is None:
                continue
            old_key = self._key(binding.subject_id, old_pred, binding.object_id)
            if old_key[0] != new_key[0]:
                if binding.subject_id == subject_id and predicate_id in predicate.exclusive_with:
                    return FactConflictResult("CONFLICT", [binding], "出现互斥谓词",
                                              "mutually_exclusive_predicate")
                continue
            related.append(binding)
            if old_key == new_key:
                if binding.scope == scope:
                    return FactConflictResult("DUPLICATE", [binding], "关系本体归一化后重复",
                                              "inverse_or_symmetric_duplicate")
                continue
        for binding in related:
            old_key = self._key(binding.subject_id, self.repository.get_predicate(binding.predicate_id), binding.object_id)
            # A project fact may override the global default for that project,
            # but never archives or mutates the global binding.
            if binding.scope != scope:
                continue
            if old_key[1] == new_key[1] and old_key[2] != new_key[2] and predicate.single_value:
                return FactConflictResult("CONFLICT", [binding], "单值关系出现不同客体",
                                          "subject_cardinality")
            if old_key[2] == new_key[2] and old_key[1] != new_key[1] and predicate.object_single_value:
                return FactConflictResult("CONFLICT", [binding], "逆向单值关系出现不同主体",
                                          "object_cardinality")
        if predicate.acyclic:
            graph: dict[str, set[str]] = {}
            for binding in related:
                old_pred = self.repository.get_predicate(binding.predicate_id)
                if old_pred is None:
                    continue
                _, left, right = self._key(binding.subject_id, old_pred, binding.object_id)
                graph.setdefault(left, set()).add(right)
            pending, seen = [new_key[2]], set()
            while pending:
                node = pending.pop()
                if node == new_key[1]:
                    return FactConflictResult("CONFLICT", [*related], "关系会形成环",
                                              "relation_cycle")
                if node in seen:
                    continue
                seen.add(node)
                pending.extend(graph.get(node, ()))
        if related:
            return FactConflictResult("COEXIST", related, "关系允许多值共存")
        return FactConflictResult("NEW")


# Compatibility name used by the source package and its callers.
ConflictDetector = FactConflictDetector
