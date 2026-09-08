"""Small, storage-neutral models used by the fact semantic layer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class EntityType(str, Enum):
    PERSON = "Person"
    ORGANIZATION = "Organization"
    LOCATION = "Location"
    DEVICE = "Device"
    SOFTWARE = "Software"
    FILE = "File"
    ACCOUNT = "Account"
    DATE = "Date"
    OTHER = "Other"


class Resolution(str, Enum):
    REPLACE = "replace"
    KEEP_OLD = "keep_old"
    MERGE = "merge"
    COEXIST = "coexist"
    ESCALATE = "escalate"


class MemoryScope(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"


class FactDecisionRequired(ValueError):
    """Raised when a host Agent/user must choose a semantic interpretation."""

    def __init__(self, decision_type: str, *, input_text: str,
                 candidates: list[dict], allowed_actions: list[str], reason: str):
        super().__init__(reason)
        self.decision_type = decision_type
        self.input_text = input_text
        self.candidates = candidates
        self.allowed_actions = allowed_actions
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "decision_type": self.decision_type,
            "input_text": self.input_text,
            "candidates": self.candidates,
            "allowed_actions": self.allowed_actions,
            "reason": self.reason,
        }


@dataclass
class Entity:
    entity_id: str
    canonical_name: str
    entity_type: str = EntityType.OTHER.value
    aliases: list[str] = field(default_factory=list)
    user_id: str = "default"
    tenant_id: str = "default"

    @staticmethod
    def make_id(entity_type: str, name: str, user_id: str = "default") -> str:
        digest = hashlib.sha256(
            f"{user_id}:{entity_type}:{name}".encode("utf-8")
        ).hexdigest()[:12]
        return f"entity:{str(entity_type).lower()}:{digest}"


@dataclass
class PredicateDef:
    predicate_id: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)
    range: list[str] = field(default_factory=list)
    single_value: bool = True
    inverse_of: str | None = None
    symmetric: bool = False
    irreflexive: bool = False
    object_single_value: bool = False
    exclusive_with: list[str] = field(default_factory=list)
    acyclic: bool = False

    @staticmethod
    def make_id(name: str) -> str:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
        return f"pred:{digest}"
