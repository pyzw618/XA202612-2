"""Relationship-aware deterministic conflict detection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FactConflictResult:
    relation: str
    existing: list[object] = field(default_factory=list)
    reason: str = ""
    conflict_type: str = ""
    conflict_types: list[str] = field(default_factory=list)


class FactConflictDetector:
    def __init__(self, repository):
        self.repository = repository

    def _get_predicate(self, predicate_id: str, tenant_id: str, user_id: str):
        try:
            return self.repository.get_predicate(predicate_id, tenant_id, user_id)
        except TypeError:
            return self.repository.get_predicate(predicate_id)

    @staticmethod
    def _key(subject_id: str, predicate, object_id: str) -> tuple[str, str, str]:
        predicate_id = predicate.predicate_id
        left, right = subject_id, object_id
        if predicate.symmetric:
            left, right = sorted((left, right))
        elif predicate.inverse_of and predicate_id > predicate.inverse_of:
            predicate_id, left, right = predicate.inverse_of, right, left
        return predicate_id, left, right

    def check(
        self,
        *,
        user_id: str,
        tenant_id: str,
        scope: str,
        subject_id: str,
        predicate_id: str,
        object_id: str,
        memory=None,
        single_value_override: bool | None = None,
        subject_type: str | None = None,
        object_type: str | None = None,
    ) -> FactConflictResult:
        predicate = self._get_predicate(predicate_id, tenant_id, user_id)
        if predicate is None:
            return FactConflictResult("NEW")
        hard: list[tuple[object | None, str, str]] = []
        if subject_id == object_id and predicate.irreflexive:
            hard.append((None, "irreflexive_violation", "关系不允许主体与客体相同"))
        subject = self.repository.get_entity(subject_id, tenant_id, user_id)
        obj = self.repository.get_entity(object_id, tenant_id, user_id)
        actual_subject_type = subject.entity_type if subject is not None else subject_type
        actual_object_type = obj.entity_type if obj is not None else object_type
        if actual_subject_type and predicate.domain and actual_subject_type not in {"Other", *predicate.domain}:
            hard.append((None, "domain_type_violation", "主体类型不符合谓词 domain"))
        if actual_object_type and predicate.range and actual_object_type not in {"Other", *predicate.range}:
            hard.append((None, "range_type_violation", "客体类型不符合谓词 range"))
        existing = self.repository.list_bindings(user_id, tenant_id, scope)
        new_key = self._key(subject_id, predicate, object_id)
        related = []
        duplicate = []
        for binding in existing:
            old_pred = self._get_predicate(binding.predicate_id, tenant_id, user_id)
            if old_pred is None:
                continue
            old_key = self._key(binding.subject_id, old_pred, binding.object_id)
            same_scope = binding.scope == scope
            same_subject = binding.subject_id == subject_id
            exclusive = (
                same_scope
                and same_subject
                and (
                    old_pred.predicate_id in (predicate.exclusive_with or [])
                    or predicate.predicate_id in (old_pred.exclusive_with or [])
                )
            )
            if exclusive:
                hard.append((binding, "mutually_exclusive_predicate", "出现互斥谓词"))
            if old_key[0] != new_key[0]:
                continue
            if same_scope:
                related.append(binding)
                if old_key == new_key:
                    duplicate.append(binding)
                continue
            # A project fact may read a GLOBAL default, but equal facts in
            # different scopes remain independent records.  Evidence for a
            # project record must never reinforce or archive its GLOBAL row.
        for binding in related:
            old_pred = self._get_predicate(binding.predicate_id, tenant_id, user_id)
            if old_pred is None:
                continue
            old_key = self._key(binding.subject_id, old_pred, binding.object_id)
            # A project fact may override the global default for that project,
            # but never archives or mutates the global binding.
            if binding.scope != scope:
                continue
            if (
                old_key[1] == new_key[1]
                and old_key[2] != new_key[2]
                and (predicate.single_value or single_value_override is True)
            ):
                hard.append((binding, "subject_cardinality", "单值关系出现不同客体"))
            if (
                old_key[2] == new_key[2]
                and old_key[1] != new_key[1]
                and predicate.object_single_value
            ):
                hard.append((binding, "object_cardinality", "逆向单值关系出现不同主体"))
        if predicate.acyclic:
            graph: dict[str, set[str]] = {}
            for binding in related:
                old_pred = self._get_predicate(binding.predicate_id, tenant_id, user_id)
                if old_pred is None:
                    continue
                _, left, right = self._key(binding.subject_id, old_pred, binding.object_id)
                graph.setdefault(left, set()).add(right)
            pending, seen = [new_key[2]], set()
            while pending:
                node = pending.pop()
                if node == new_key[1]:
                    hard.append((None, "relation_cycle", "关系会形成环"))
                    break
                if node in seen:
                    continue
                seen.add(node)
                pending.extend(graph.get(node, ()))
        conflict_bindings = []
        for binding, _, _ in hard:
            if binding is not None and binding not in conflict_bindings:
                conflict_bindings.append(binding)
        if hard:
            types = list(dict.fromkeys(item[1] for item in hard))
            reasons = list(dict.fromkeys(item[2] for item in hard))
            return FactConflictResult(
                "CONFLICT",
                [*conflict_bindings, *[b for b in related if b not in conflict_bindings]],
                "；".join(reasons),
                "|".join(types),
                types,
            )
        if duplicate:
            return FactConflictResult("DUPLICATE", duplicate, "关系本体归一化后重复",
                                      "inverse_or_symmetric_duplicate")
        if related:
            return FactConflictResult("COEXIST", related, "关系允许多值共存")
        return FactConflictResult("NEW")


# Compatibility name used by the source package and its callers.
ConflictDetector = FactConflictDetector
