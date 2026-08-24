"""Long-Term Authority rules shared by adapters and storage implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from memoryhub.domain.contracts import EvolutionStatus, LongTermEnvelope, MemoryType


class AuthorityError(ValueError):
    """Base error for rejected Authority operations."""


class AuthorityVersionConflictError(AuthorityError):
    """The submitted content version conflicts with the stored version."""


class AuthorityStatusConflictError(AuthorityError):
    """The operation would create more than one ACTIVE version in a chain."""


class AuthorityRepositoryPort(Protocol):
    def get(
        self, *, tenant_id: str, user_id: str, memory_id: str,
        include_inactive: bool = False,
    ) -> LongTermEnvelope | None: ...

    def list(
        self, *, tenant_id: str, user_id: str, include_inactive: bool = False,
    ) -> list[LongTermEnvelope]: ...

    def save(self, envelope: LongTermEnvelope) -> LongTermEnvelope: ...


@dataclass(frozen=True, slots=True)
class AuthorityValidation:
    """Stable validation result used by the canonical write service."""

    envelope: LongTermEnvelope
    existing: LongTermEnvelope | None
    chain_key: tuple[str, str, str, str, str]


class LongTermAuthorityFacade:
    """Validate unified Long-Term envelopes before delegating to a repository.

    The facade owns the semantic invariants; the repository owns tenant-scoped
    persistence and legacy Preference/Knowledge compatibility.  Inactive
    versions remain queryable only through an explicit diagnostic flag.
    """

    def __init__(self, repository: AuthorityRepositoryPort):
        self.repository = repository

    @staticmethod
    def chain_key(envelope: LongTermEnvelope) -> tuple[str, str, str, str, str]:
        return (
            envelope.tenant_id,
            envelope.user_id,
            envelope.memory_type.value,
            envelope.normalized_key,
            f"{envelope.scope_level.value}:{envelope.scope}",
        )

    @staticmethod
    def is_default_readable(envelope: LongTermEnvelope) -> bool:
        return envelope.evolution_status is EvolutionStatus.ACTIVE

    def validate(
        self,
        envelope: LongTermEnvelope,
        *,
        existing: LongTermEnvelope | None = None,
        siblings: Iterable[LongTermEnvelope] = (),
    ) -> AuthorityValidation:
        if not isinstance(envelope, LongTermEnvelope):
            raise TypeError("long-term authority requires LongTermEnvelope")
        existing = existing or self.repository.get(
            tenant_id=envelope.tenant_id,
            user_id=envelope.user_id,
            memory_id=envelope.memory_id,
            include_inactive=True,
        )
        if existing is not None:
            if existing.model_dump(mode="json") == envelope.model_dump(mode="json"):
                return AuthorityValidation(envelope, existing, self.chain_key(envelope))
            if envelope.content_version <= existing.content_version:
                raise AuthorityVersionConflictError(
                    f"memory {envelope.memory_id} already has content_version "
                    f"{existing.content_version}"
                )
        if envelope.evolution_status is EvolutionStatus.ACTIVE:
            key = self.chain_key(envelope)
            for sibling in siblings:
                if (
                    sibling.memory_id != envelope.memory_id
                    and self.is_default_readable(sibling)
                    and self.chain_key(sibling) == key
                ):
                    raise AuthorityStatusConflictError(
                        "an Authority version chain may have at most one ACTIVE version"
                    )
        return AuthorityValidation(envelope, existing, self.chain_key(envelope))

    def prepare(self, envelope: LongTermEnvelope) -> AuthorityValidation:
        siblings = self.repository.list(
            tenant_id=envelope.tenant_id,
            user_id=envelope.user_id,
            include_inactive=True,
        )
        return self.validate(envelope, siblings=siblings)

    def write(self, envelope: LongTermEnvelope) -> LongTermEnvelope:
        """Validate and persist through the configured Authority adapter."""
        validation = self.prepare(envelope)
        if validation.existing is not None and (
            validation.existing.model_dump(mode="json") == envelope.model_dump(mode="json")
        ):
            return validation.existing
        return self.repository.save(envelope)

    def read(
        self,
        *,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        include_inactive: bool = False,
    ) -> LongTermEnvelope | None:
        return self.repository.get(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_id=memory_id,
            include_inactive=include_inactive,
        )

    def list_active(self, *, tenant_id: str, user_id: str) -> list[LongTermEnvelope]:
        return self.repository.list(
            tenant_id=tenant_id, user_id=user_id, include_inactive=False
        )


class LongTermValidationError(AuthorityError):
    """A long-term envelope fails type-specific content validation."""


@dataclass(frozen=True, slots=True)
class ContentValidationIssue:
    """One validation issue for a long-term envelope."""

    code: str
    message: str
    field: str = ""


@dataclass(frozen=True, slots=True)
class ContentValidationResult:
    """Result of validating a long-term envelope's content."""

    ok: bool
    issues: list[ContentValidationIssue] = field(default_factory=list)


class LongTermContentValidator:
    """Type-specific content validation for Long-Term memories.

    The validator enforces the minimum shape required for each memory type.
    Procedure memories are held to the highest bar because they drive action:
    they must contain trigger, preconditions, steps, verification and failure
    recovery, and they must be supported by enough independent evidence.
    """

    MIN_PROCEDURE_FREQUENCY: int = 2

    def validate(self, envelope: LongTermEnvelope) -> ContentValidationResult:
        if envelope.memory_type is MemoryType.PREFERENCE:
            return self._validate_preference(envelope)
        if envelope.memory_type is MemoryType.SEMANTIC:
            return self._validate_semantic(envelope)
        if envelope.memory_type is MemoryType.PROCEDURAL:
            return self._validate_procedural(envelope)
        if envelope.memory_type is MemoryType.EPISODIC:
            return self._validate_episodic(envelope)
        return ContentValidationResult(
            ok=False,
            issues=[
                ContentValidationIssue(
                    code="UNKNOWN_MEMORY_TYPE",
                    message=f"unsupported memory type: {envelope.memory_type}",
                )
            ],
        )

    @staticmethod
    def _has_non_empty(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple)):
            return len(value) > 0
        if isinstance(value, dict):
            return bool(value)
        return True

    def _validate_preference(self, envelope: LongTermEnvelope) -> ContentValidationResult:
        content = envelope.content
        issues: list[ContentValidationIssue] = []
        value = content.get("value") or content.get("text") or content.get("payload")
        if not self._has_non_empty(value):
            issues.append(
                ContentValidationIssue(
                    code="PREFERENCE_VALUE_MISSING",
                    message="preference must contain a non-empty value, text or payload",
                    field="content.value/text/payload",
                )
            )
        return ContentValidationResult(ok=not issues, issues=issues)

    def _validate_semantic(self, envelope: LongTermEnvelope) -> ContentValidationResult:
        content = envelope.content
        issues: list[ContentValidationIssue] = []
        has_statement = self._has_non_empty(content.get("statement"))
        has_triple = (
            self._has_non_empty(content.get("subject"))
            and self._has_non_empty(content.get("predicate"))
            and self._has_non_empty(content.get("object_value"))
        )
        if not (has_statement or has_triple):
            issues.append(
                ContentValidationIssue(
                    code="SEMANTIC_FACT_INCOMPLETE",
                    message=(
                        "semantic fact must contain a statement or a "
                        "subject-predicate-object triple"
                    ),
                    field="content.statement or content.subject/predicate/object_value",
                )
            )
        return ContentValidationResult(ok=not issues, issues=issues)

    def _validate_procedural(self, envelope: LongTermEnvelope) -> ContentValidationResult:
        content = envelope.content
        issues: list[ContentValidationIssue] = []

        required_fields = {
            "trigger": "PROCEDURE_TRIGGER_MISSING",
            "preconditions": "PROCEDURE_PRECONDITIONS_MISSING",
            "steps": "PROCEDURE_STEPS_MISSING",
            "verification": "PROCEDURE_VERIFICATION_MISSING",
            "failure_recovery": "PROCEDURE_FAILURE_RECOVERY_MISSING",
        }

        for field_name, code in required_fields.items():
            value = content.get(field_name)
            if not self._has_non_empty(value):
                issues.append(
                    ContentValidationIssue(
                        code=code,
                        message=f"procedure must contain a non-empty {field_name}",
                        field=f"content.{field_name}",
                    )
                )

        steps = content.get("steps", [])
        failures = content.get("failure_recovery", [])
        if isinstance(steps, list) and isinstance(failures, list):
            has_conditional = any(
                isinstance(item, dict) and item.get("condition")
                for item in failures
            )
            if failures and not has_conditional:
                issues.append(
                    ContentValidationIssue(
                        code="PROCEDURE_FAILURE_RECOVERY_INCOMPLETE",
                        message=(
                            "failure recovery must include at least one "
                            "conditional recovery step"
                        ),
                        field="content.failure_recovery",
                    )
                )

        frequency = len(envelope.evidence_refs) if envelope.evidence_refs else 0
        if frequency < self.MIN_PROCEDURE_FREQUENCY:
            issues.append(
                ContentValidationIssue(
                    code="PROCEDURE_INSUFFICIENT_EVIDENCE",
                    message=(
                        f"procedure must be derived from at least "
                        f"{self.MIN_PROCEDURE_FREQUENCY} independent episodes"
                    ),
                    field="evidence_refs",
                )
            )

        outcome_field = content.get("outcome")
        if outcome_field is not None and str(outcome_field).lower() == "failed":
            issues.append(
                ContentValidationIssue(
                    code="PROCEDURE_FROM_FAILED_EPISODE",
                    message=(
                        "failed episodes may only contribute to failure recovery "
                        "or constraints, not to the main procedure"
                    ),
                    field="content.outcome",
                )
            )

        return ContentValidationResult(ok=not issues, issues=issues)

    def _validate_episodic(self, envelope: LongTermEnvelope) -> ContentValidationResult:
        content = envelope.content
        issues: list[ContentValidationIssue] = []
        has_content = self._has_non_empty(content.get("content")) or self._has_non_empty(
            content.get("text")
        )
        has_refs = self._has_non_empty(content.get("episode_refs"))
        if not (has_content or has_refs):
            issues.append(
                ContentValidationIssue(
                    code="EPISODIC_CONTENT_MISSING",
                    message=(
                        "episodic memory must contain content or reference "
                        "at least one episode"
                    ),
                    field="content.content/text or content.episode_refs",
                )
            )
        return ContentValidationResult(ok=not issues, issues=issues)


__all__ = [
    "AuthorityError",
    "AuthorityRepositoryPort",
    "AuthorityStatusConflictError",
    "AuthorityValidation",
    "AuthorityVersionConflictError",
    "ContentValidationIssue",
    "ContentValidationResult",
    "LongTermAuthorityFacade",
    "LongTermContentValidator",
    "LongTermValidationError",
]
