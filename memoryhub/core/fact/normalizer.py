"""Deterministic entity and predicate resolution for FACT memories."""

from __future__ import annotations

import re
import uuid

from .models import Entity, FactDecisionRequired, PredicateDef


def _clean(value: str) -> str:
    # Keep symbols which change meaning (C++, C#, version numbers and dates).
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _containment(left: str, right: str) -> float:
    a, b = _clean(left), _clean(right)
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        return len(shorter) / max(1, len(longer))
    return 0.0


class EntityNormalizer:
    """Resolve only same-user, same-type entities; ambiguous matches escalate."""

    def __init__(self, repository):
        self.repository = repository

    def normalize(self, text: str, entity_type: str = "Other", *,
                  user_id: str = "default", tenant_id: str = "default",
                  selected_id: str | None = None,
                  force_new: bool = False,
                  persist: bool = True,
                  pending_operations: list[dict] | None = None) -> str:
        text = str(text or "").strip()
        if not text:
            raise ValueError("fact entity cannot be empty")
        if selected_id:
            entity = self.repository.get_entity(selected_id, tenant_id, user_id)
            if entity is None or (entity.entity_type != entity_type and entity_type != "Other"):
                raise ValueError("fact.entity_selection_invalid")
            return entity.entity_id

        if force_new:
            candidates = []
        else:
            candidates = self.repository.find_entities(text, tenant_id, user_id, entity_type)
        if len(candidates) == 1:
            entity = candidates[0]
            if text.casefold() not in {entity.canonical_name.casefold(), *(str(a).casefold() for a in entity.aliases)}:
                if persist:
                    self.repository.add_alias(entity.entity_id, text, tenant_id, user_id)
                elif pending_operations is not None:
                    pending_operations.append({
                        "kind": "entity_alias", "entity_id": entity.entity_id,
                        "alias": text, "tenant_id": tenant_id, "user_id": user_id,
                    })
            return entity.entity_id
        if len(candidates) > 1:
            raise FactDecisionRequired(
                "entity_resolution", input_text=text,
                candidates=[self.repository.entity_dict(item) for item in candidates],
                allowed_actions=["select_existing", "create_new"],
                reason="实体存在多个同名候选，需要主 Agent 或用户裁决",
            )

        entities = [] if force_new else self.repository.list_entities(
            tenant_id, user_id, entity_type
        )
        scored = sorted(
            ((max(_containment(text, e.canonical_name),
                  *(_containment(text, alias) for alias in e.aliases)), e)
             for e in entities), key=lambda item: item[0], reverse=True
        )
        if scored and scored[0][0] >= 0.85:
            if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.12:
                raise FactDecisionRequired(
                    "entity_resolution", input_text=text,
                    candidates=[self.repository.entity_dict(e) | {"similarity": round(s, 4)}
                                for s, e in scored[:10]],
                    allowed_actions=["select_existing", "create_new"],
                    reason="实体相似度接近，无法安全自动合并",
                )
            if persist:
                self.repository.add_alias(scored[0][1].entity_id, text, tenant_id, user_id)
            elif pending_operations is not None:
                pending_operations.append({
                    "kind": "entity_alias", "entity_id": scored[0][1].entity_id,
                    "alias": text, "tenant_id": tenant_id, "user_id": user_id,
                })
            return scored[0][1].entity_id

        entity = Entity(
            entity_id=Entity.make_id(
                entity_type, text, user_id, tenant_id,
                disambiguator=uuid.uuid4().hex if force_new else "",
            ),
            canonical_name=text, entity_type=entity_type,
            aliases=[text], user_id=user_id, tenant_id=tenant_id,
        )
        if persist:
            self.repository.save_entity(entity)
        elif pending_operations is not None:
            pending_operations.append({"kind": "entity_create", "entity": entity})
        return entity.entity_id


class PredicateNormalizer:
    def __init__(self, repository, definitions: list[PredicateDef] | None = None):
        self.repository = repository
        self.definitions = definitions or []

    def normalize(
        self,
        text: str,
        *,
        selected_id: str | None = None,
        force_new: bool = False,
        tenant_id: str = "default",
        user_id: str = "default",
        persist: bool = True,
        pending_operations: list[dict] | None = None,
    ) -> str:
        value = str(text or "").strip()
        if not value:
            raise ValueError("fact predicate cannot be empty")
        if selected_id:
            try:
                selected = self.repository.get_predicate(selected_id, tenant_id, user_id)
            except TypeError:
                selected = self.repository.get_predicate(selected_id)
            if selected is None:
                raise ValueError("fact.predicate_selection_invalid")
            return selected_id
        if force_new:
            matches = []
        else:
            try:
                matches = self.repository.find_predicates(value, tenant_id, user_id)
            except TypeError:
                matches = self.repository.find_predicates(value)
        if len(matches) == 1:
            # Built-in ontology aliases are process-wide and read-only.  A
            # user spelling that happens to match one simply reuses the
            # predicate; only custom predicates receive owner-scoped aliases.
            is_builtin = bool(getattr(matches[0], "built_in", False))
            if persist and not is_builtin:
                try:
                    self.repository.add_predicate_alias(
                        matches[0].predicate_id, value, tenant_id, user_id
                    )
                except TypeError:
                    self.repository.add_predicate_alias(matches[0].predicate_id, value)
            elif not is_builtin and pending_operations is not None:
                pending_operations.append({
                    "kind": "predicate_alias", "predicate_id": matches[0].predicate_id,
                    "alias": value, "tenant_id": tenant_id, "user_id": user_id,
                })
            return matches[0].predicate_id
        if len(matches) > 1:
            raise FactDecisionRequired(
                "predicate_resolution", input_text=value,
                candidates=[self.repository.predicate_dict(p) for p in matches],
                allowed_actions=["select_existing", "create_new"],
                reason="谓词存在多个候选，需要主 Agent 或用户裁决",
            )
        pred = None if force_new else next(
            (p for p in self.definitions
             if _clean(value) in {_clean(p.canonical_name), *map(_clean, p.aliases)}),
            None,
        )
        if pred is not None:
            if persist:
                try:
                    self.repository.save_predicate(
                        pred, tenant_id=tenant_id, user_id=user_id, built_in=True
                    )
                except TypeError:
                    self.repository.save_predicate(pred)
            return pred.predicate_id
        # A predicate not present in the ontology is conservatively multi-valued;
        # callers may explicitly mark the FACT as single-valued.
        pred = PredicateDef(
            PredicateDef.make_id(value, tenant_id=tenant_id, user_id=user_id),
            value,
            [value],
            single_value=False,
            ontology_version="custom/v1-unset",
        )
        if persist:
            try:
                self.repository.save_predicate(pred, tenant_id=tenant_id, user_id=user_id)
            except TypeError:
                self.repository.save_predicate(pred)
        elif pending_operations is not None:
            pending_operations.append({
                "kind": "predicate_create", "predicate": pred,
                "tenant_id": tenant_id, "user_id": user_id,
            })
        return pred.predicate_id
