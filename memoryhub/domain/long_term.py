"""Long-Term Authority rules shared by adapters and storage implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from memoryhub.domain.contracts import EvolutionStatus, LongTermEnvelope


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


__all__ = [
    "AuthorityError",
    "AuthorityRepositoryPort",
    "AuthorityStatusConflictError",
    "AuthorityValidation",
    "AuthorityVersionConflictError",
    "LongTermAuthorityFacade",
]
