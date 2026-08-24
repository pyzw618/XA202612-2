"""Formation Shadow mode: compare vNext reflection/candidate/consolidation
with a legacy extraction stub without writing ACTIVE Long-Term memories.

The shadow service is intentionally isolated: it uses in-memory candidate
staging and never calls an Authority write.  All steps are recorded in the
provided TraceStore in redacted form.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from memoryhub.application.candidate_service import CandidateService
from memoryhub.application.consolidation_service import (
    ConsolidationContext,
    ConsolidationResult,
    ConsolidationService,
    PromotionDecision,
)
from memoryhub.application.reflection_service import ReflectionService
from memoryhub.core.reflection.schema import ReflectionInput
from memoryhub.domain.contracts import (
    LongTermEnvelope,
    MemoryEventContract,
)
from memoryhub.domain.long_term import LongTermContentValidator
from memoryhub.observability.trace_store import TraceStore
from memoryhub.storage.vnext_repositories import CandidateView


class LegacyExtractionPort(Protocol):
    """Adapts the old extraction pipeline into a comparable in-memory stub."""

    def extract(self, event: MemoryEventContract) -> list[LegacyMemoryStub]:
        ...


@dataclass(frozen=True, slots=True)
class LegacyMemoryStub:
    """A minimal representation of what the legacy pipeline would produce."""

    memory_id: str
    memory_type: str
    normalized_key: str
    scope_level: str
    scope: str
    would_write_active: bool = True


@dataclass(frozen=True, slots=True)
class ShadowDifference:
    """One classified difference between legacy and vNext outputs."""

    kind: str
    legacy_memory_id: str
    vnext_candidate_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ShadowComparisonReport:
    """Result of one Formation Shadow comparison."""

    event_id: str
    trace_id: str
    tenant_id: str
    user_id: str
    vnext_candidate: dict[str, Any]
    vnext_decision: dict[str, Any]
    legacy_results: list[dict[str, Any]] = field(default_factory=list)
    differences: list[ShadowDifference] = field(default_factory=list)
    premature_promotions: list[ShadowDifference] = field(default_factory=list)
    missed_promotions: list[ShadowDifference] = field(default_factory=list)
    scope_mismatches: list[ShadowDifference] = field(default_factory=list)
    type_mismatches: list[ShadowDifference] = field(default_factory=list)
    safe: bool = True

    @property
    def has_regression(self) -> bool:
        return bool(
            self.premature_promotions or self.missed_promotions or self.scope_mismatches
        )


class InMemoryCandidateRepository:
    """Candidate repository used only inside a shadow run.

    It intentionally does not touch the production candidate table.
    """

    def __init__(self) -> None:
        self._rows: dict[str, CandidateView] = {}

    def _key(
        self, *, tenant_id: str, user_id: str, candidate_id: str
    ) -> str:
        return f"{tenant_id}:{user_id}:{candidate_id}"

    def create(
        self,
        *,
        candidate_id: str,
        tenant_id: str,
        user_id: str,
        memory_type: str,
        normalized_key: str,
        claim: dict[str, Any],
        scope_level: str,
        scope: str,
        status: str = "ACCUMULATING",
        evidence_refs: list[str] | None = None,
        supporting_episode_ids: list[str] | None = None,
        frequency: int = 1,
    ) -> CandidateView:
        row = CandidateView(
            candidate_id=candidate_id,
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type=memory_type,
            status=status,
            formation_status="CANDIDATE",
            normalized_key=normalized_key,
            scope_level=scope_level,
            scope=scope,
            claim=dict(claim),
            confidence=0.0,
            utility=0.0,
            stability=0.0,
            frequency=frequency,
            evidence_refs=list(evidence_refs or []),
            supporting_episode_ids=list(supporting_episode_ids or []),
        )
        self._rows[self._key(tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id)] = row
        return row

    def find_by_key(
        self, *, tenant_id: str, user_id: str, normalized_key: str
    ) -> CandidateView | None:
        for row in self._rows.values():
            if (
                row.tenant_id == tenant_id
                and row.user_id == user_id
                and row.normalized_key == normalized_key
            ):
                return row
        return None

    def add_evidence(
        self,
        *,
        tenant_id: str,
        user_id: str,
        candidate_id: str,
        event_id: str,
        episode_id: str,
        is_independent: bool = True,
    ) -> CandidateView:
        key = self._key(tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id)
        existing = self._rows[key]
        refs = set(existing.evidence_refs or [])
        refs.add(event_id)
        episodes = set(existing.supporting_episode_ids or [])
        episodes.add(episode_id)
        frequency = existing.frequency + (1 if is_independent else 0)
        updated = CandidateView(
            candidate_id=existing.candidate_id,
            tenant_id=existing.tenant_id,
            user_id=existing.user_id,
            memory_type=existing.memory_type,
            status=existing.status,
            formation_status=existing.formation_status,
            normalized_key=existing.normalized_key,
            scope_level=existing.scope_level,
            scope=existing.scope,
            claim=dict(existing.claim),
            confidence=existing.confidence,
            utility=existing.utility,
            stability=existing.stability,
            frequency=frequency,
            evidence_refs=sorted(refs),
            supporting_episode_ids=sorted(episodes),
        )
        self._rows[key] = updated
        return updated


class DeterministicLegacyExtractionAdapter:
    """A deterministic stand-in for the old extraction/write path.

    The adapter intentionally over-promotes and defaults to GLOBAL scope so
    that the Shadow report can surface premature promotion and scope drift.
    """

    _TYPE_MAP: dict[str, str] = {
        "preference": "PREFERENCE",
        "knowledge.fact": "SEMANTIC",
        "knowledge.workflow": "PROCEDURAL",
        "knowledge.case": "EPISODIC",
        "fact": "SEMANTIC",
        "knowledge": "SEMANTIC",
    }

    def __init__(self, *, would_write_active: bool = True) -> None:
        self.would_write_active = would_write_active

    def extract(self, event: MemoryEventContract) -> list[LegacyMemoryStub]:
        text = str(event.payload.get("text", "")).lower()
        if "docx" in text:
            memory_type = "preference"
            key = "legacy:format:docx"
        elif "markdown" in text or " md" in text or text.endswith("md"):
            memory_type = "preference"
            key = "legacy:format:markdown"
        elif "fix" in text or "repair" in text:
            memory_type = "knowledge.workflow"
            key = "legacy:procedure:repair"
        elif "fact" in text or " is " in text:
            memory_type = "knowledge.fact"
            key = "legacy:fact:extracted"
        else:
            memory_type = "preference"
            key = "legacy:preference:unknown"

        vnext_type = self._TYPE_MAP.get(memory_type, "SEMANTIC")
        memory_id = f"legacy-{self._hash(event.event_id, key)}"
        return [
            LegacyMemoryStub(
                memory_id=memory_id,
                memory_type=vnext_type,
                normalized_key=key,
                scope_level="GLOBAL",
                scope="GLOBAL",
                would_write_active=self.would_write_active,
            )
        ]

    @staticmethod
    def _hash(*parts: str) -> str:
        payload = "|".join(parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class FormationShadowService:
    """Run the vNext formation pipeline side-by-side with a legacy stub.

    The service never writes an ACTIVE Long-Term memory.  It produces a
    diagnostic comparison report and redacted trace spans instead.
    """

    def __init__(
        self,
        *,
        reflection_service: ReflectionService | None = None,
        legacy_adapter: LegacyExtractionPort | None = None,
        consolidation_service: ConsolidationService | None = None,
        trace_store: TraceStore | None = None,
    ) -> None:
        self._candidate_repo = InMemoryCandidateRepository()
        self._candidate_service = CandidateService(self._candidate_repo)
        self._reflection_service = reflection_service or ReflectionService()
        self._legacy_adapter = legacy_adapter or DeterministicLegacyExtractionAdapter()
        self._consolidation_service = consolidation_service or ConsolidationService(
            authority_facade=None
        )
        self._trace_store = trace_store or TraceStore()
        self._validator = LongTermContentValidator()

    @property
    def trace_store(self) -> TraceStore:
        return self._trace_store

    def compare_event(
        self,
        event: MemoryEventContract,
        *,
        episode_id: str,
        working_state: dict[str, Any] | None = None,
        episode_event_id: str | None = None,
        seq_no: int = 1,
        episode_snapshot: dict[str, Any] | None = None,
    ) -> ShadowComparisonReport:
        if not isinstance(event, MemoryEventContract):
            raise TypeError("shadow comparison requires MemoryEventContract")

        trace_id = event.trace_id or f"trace-{event.event_id}"
        event_span = self._trace_store.record_event(
            trace_id=trace_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            event_id=event.event_id,
            event_type=event.event_type,
            source_type=event.source_type,
            policy_action=event.policy_action,
            source_hash=event.source_hash,
        )

        if working_state is not None:
            self._trace_store.record_working(
                trace_id=trace_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                event_id=event.event_id,
                working_state_id=f"ws-{event.task_id}",
                version=1,
                state=working_state,
                parent_id=event_span.span_id,
            )

        self._trace_store.record_episode(
            trace_id=trace_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            event_id=event.event_id,
            episode_id=episode_id,
            episode_event_id=episode_event_id,
            seq_no=seq_no,
            event_type="SHADOW_EPISODE",
            parent_id=event_span.span_id,
        )

        reflection_input = ReflectionInput(
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            task_id=event.task_id,
            episode_id=episode_id,
            event_id=event.event_id,
            payload_summary=dict(event.payload),
            working_state_snapshot=working_state or {},
            episode_history_summary=episode_snapshot or [],
            requested_memory_type=None,
            scope_hint=None,
            occurred_at=event.occurred_at,
        )
        candidate = self._reflection_service.run(reflection_input)

        candidate_span = self._trace_store.record_candidate(
            trace_id=trace_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            event_id=event.event_id,
            candidate_id=candidate.candidate_id,
            memory_type=candidate.memory_type.value,
            normalized_key=candidate.normalized_key,
            scope_level=candidate.scope_level.value,
            scope=candidate.scope,
            confidence=candidate.confidence,
            utility=candidate.utility,
            stability=candidate.stability,
            frequency=candidate.frequency,
            claim=dict(candidate.claim),
            parent_id=event_span.span_id,
        )

        staged = self._candidate_service.stage(
            candidate, source_event=event, episode_id=episode_id
        )

        # Preserve reflection scores while keeping merged frequency/evidence.
        scored = CandidateView(
            candidate_id=staged.candidate.candidate_id,
            tenant_id=staged.candidate.tenant_id,
            user_id=staged.candidate.user_id,
            memory_type=staged.candidate.memory_type,
            status=staged.candidate.status,
            formation_status=staged.candidate.formation_status,
            normalized_key=staged.candidate.normalized_key,
            scope_level=staged.candidate.scope_level,
            scope=staged.candidate.scope,
            claim=dict(staged.candidate.claim),
            confidence=candidate.confidence,
            utility=candidate.utility,
            stability=candidate.stability,
            frequency=staged.candidate.frequency,
            evidence_refs=list(staged.candidate.evidence_refs),
            supporting_episode_ids=list(staged.candidate.supporting_episode_ids),
        )

        staged_span = self._trace_store.record_candidate(
            trace_id=trace_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            event_id=event.event_id,
            candidate_id=scored.candidate_id,
            memory_type=scored.memory_type,
            normalized_key=scored.normalized_key,
            scope_level=scored.scope_level,
            scope=scored.scope,
            confidence=scored.confidence,
            utility=scored.utility,
            stability=scored.stability,
            frequency=scored.frequency,
            claim=dict(scored.claim),
            parent_id=candidate_span.span_id,
        )

        memory_id = self._memory_id_for_candidate(scored)
        context = self._build_consolidation_context(event)
        consolidation = self._consolidation_service.consolidate(
            scored,
            memory_id=memory_id,
            context=context,
        )

        consolidation_span = self._trace_store.record_consolidation(
            trace_id=trace_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            event_id=event.event_id,
            candidate_id=staged.candidate.candidate_id,
            decision=consolidation.decision,
            score=consolidation.score,
            reasons=consolidation.reasons,
            fast_path=consolidation.fast_path,
            parent_id=staged_span.span_id,
        )

        envelope = consolidation.envelope
        if envelope is not None:
            validation = self._validator.validate(envelope)
            self._trace_store.record_evolution(
                trace_id=trace_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                event_id=event.event_id,
                candidate_id=staged.candidate.candidate_id,
                memory_id=envelope.memory_id,
                action="SHADOW_PROMOTE",
                previous_memory_id=None,
                parent_id=consolidation_span.span_id,
            )

        legacy_stubs = self._legacy_adapter.extract(event)
        for stub in legacy_stubs:
            self._trace_store.record_legacy(
                trace_id=trace_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                event_id=event.event_id,
                memory_type=stub.memory_type,
                scope_level=stub.scope_level,
                scope=stub.scope,
                normalized_key=stub.normalized_key,
                memory_id=stub.memory_id,
                parent_id=event_span.span_id,
            )

        differences = self._compare(
            scored,
            consolidation,
            legacy_stubs,
            validation_issues=validation.issues if envelope is not None else [],
        )

        return ShadowComparisonReport(
            event_id=event.event_id,
            trace_id=trace_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            vnext_candidate=self._candidate_to_dict(scored),
            vnext_decision=self._decision_to_dict(consolidation, envelope),
            legacy_results=[self._legacy_to_dict(s) for s in legacy_stubs],
            differences=differences,
            premature_promotions=[d for d in differences if d.kind == "PREMATURE_PROMOTION"],
            missed_promotions=[d for d in differences if d.kind == "MISSED_PROMOTION"],
            scope_mismatches=[d for d in differences if d.kind == "SCOPE_MISMATCH"],
            type_mismatches=[d for d in differences if d.kind == "TYPE_MISMATCH"],
            safe=not any(
                d.kind in {"PREMATURE_PROMOTION", "MISSED_PROMOTION"}
                for d in differences
            ),
        )

    def _build_consolidation_context(self, event: MemoryEventContract) -> ConsolidationContext:
        payload = event.payload or {}
        return ConsolidationContext(
            source_event=event,
            explicit_long_term=bool(payload.get("explicit_long_term")),
            sensitivity_level=event.sensitivity_level or "NONE",
            tool_trust=str(payload.get("tool_trust", "medium")),
        )

    def _memory_id_for_candidate(self, candidate: CandidateView) -> str:
        payload = (
            f"{candidate.tenant_id}:{candidate.user_id}:"
            f"{candidate.memory_type}:{candidate.normalized_key}:{candidate.scope}"
        )
        return f"mem-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"

    @staticmethod
    def _candidate_to_dict(candidate: CandidateView) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "memory_type": candidate.memory_type,
            "normalized_key": candidate.normalized_key,
            "scope_level": candidate.scope_level,
            "scope": candidate.scope,
            "confidence": candidate.confidence,
            "utility": candidate.utility,
            "stability": candidate.stability,
            "frequency": candidate.frequency,
            "status": candidate.status,
        }

    @staticmethod
    def _decision_to_dict(
        consolidation: ConsolidationResult, envelope: LongTermEnvelope | None
    ) -> dict[str, Any]:
        return {
            "decision": consolidation.decision,
            "score": consolidation.score,
            "reasons": consolidation.reasons,
            "fast_path": consolidation.fast_path,
            "memory_id": envelope.memory_id if envelope is not None else None,
            "envelope_content_hash": (
                hashlib.sha256(
                    json.dumps(envelope.content, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                if envelope is not None
                else None
            ),
        }

    @staticmethod
    def _legacy_to_dict(stub: LegacyMemoryStub) -> dict[str, Any]:
        return {
            "memory_id": stub.memory_id,
            "memory_type": stub.memory_type,
            "normalized_key": stub.normalized_key,
            "scope_level": stub.scope_level,
            "scope": stub.scope,
            "would_write_active": stub.would_write_active,
        }

    def _compare(
        self,
        candidate: CandidateView,
        consolidation: ConsolidationResult,
        legacy_stubs: list[LegacyMemoryStub],
        validation_issues: list[Any],
    ) -> list[ShadowDifference]:
        differences: list[ShadowDifference] = []
        vnext_active = consolidation.decision == PromotionDecision.PROMOTE

        for issue in validation_issues:
            differences.append(
                ShadowDifference(
                    kind="VALIDATION_ISSUE",
                    legacy_memory_id="",
                    vnext_candidate_id=candidate.candidate_id,
                    reason=f"{issue.code}: {issue.message}",
                )
            )

        for stub in legacy_stubs:
            equivalent = self._equivalent(stub, candidate)

            if stub.would_write_active and not vnext_active and equivalent:
                differences.append(
                    ShadowDifference(
                        kind="PREMATURE_PROMOTION",
                        legacy_memory_id=stub.memory_id,
                        vnext_candidate_id=candidate.candidate_id,
                        reason="legacy would write ACTIVE while vNext does not promote",
                    )
                )

            if not equivalent:
                if vnext_active:
                    differences.append(
                        ShadowDifference(
                            kind="MISSED_PROMOTION",
                            legacy_memory_id=stub.memory_id,
                            vnext_candidate_id=candidate.candidate_id,
                            reason="vNext would promote but legacy produced no equivalent memory",
                        )
                    )
                continue

            if stub.scope_level != candidate.scope_level:
                differences.append(
                    ShadowDifference(
                        kind="SCOPE_MISMATCH",
                        legacy_memory_id=stub.memory_id,
                        vnext_candidate_id=candidate.candidate_id,
                        reason=f"legacy scope {stub.scope_level} != vNext {candidate.scope_level}",
                    )
                )

            if stub.memory_type != candidate.memory_type:
                differences.append(
                    ShadowDifference(
                        kind="TYPE_MISMATCH",
                        legacy_memory_id=stub.memory_id,
                        vnext_candidate_id=candidate.candidate_id,
                        reason=f"legacy type {stub.memory_type} != vNext {candidate.memory_type}",
                    )
                )

        if vnext_active and not legacy_stubs:
            differences.append(
                ShadowDifference(
                    kind="MISSED_PROMOTION",
                    legacy_memory_id="",
                    vnext_candidate_id=candidate.candidate_id,
                    reason="vNext would promote but legacy produced no memory",
                )
            )

        return differences

    def _equivalent(self, stub: LegacyMemoryStub, candidate: CandidateView) -> bool:
        key_distance = self._normalized_key_distance(
            stub.normalized_key, candidate.normalized_key
        )
        shared_token = self._key_has_shared_token(
            stub.normalized_key, candidate.normalized_key
        )
        return stub.memory_type == candidate.memory_type and (
            key_distance < 0.85 or shared_token
        )

    @staticmethod
    def _normalized_key_distance(left: str, right: str) -> float:
        """Simple token-overlap distance for normalized keys."""
        left_tokens = FormationShadowService._key_tokens(left)
        right_tokens = FormationShadowService._key_tokens(right)
        if not left_tokens and not right_tokens:
            return 0.0
        union = left_tokens | right_tokens
        if not union:
            return 1.0
        intersection = left_tokens & right_tokens
        return 1.0 - len(intersection) / len(union)

    @staticmethod
    def _key_has_shared_token(left: str, right: str) -> bool:
        left_tokens = FormationShadowService._key_tokens(left)
        right_tokens = FormationShadowService._key_tokens(right)
        return bool(left_tokens & right_tokens)

    @staticmethod
    def _key_tokens(value: str) -> set[str]:
        cleaned = value.replace("legacy:", "").lower()
        return {
            token.strip(".,!?;:'\"")
            for token in cleaned.replace(":", " ").split()
            if token.strip(".,!?;:'\"")
        }


__all__ = [
    "DeterministicLegacyExtractionAdapter",
    "FormationShadowService",
    "InMemoryCandidateRepository",
    "LegacyExtractionPort",
    "LegacyMemoryStub",
    "ShadowComparisonReport",
    "ShadowDifference",
]
