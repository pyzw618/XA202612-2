"""Formation Shadow and Retrieval dual-read comparison.

The dual-read path deliberately returns the legacy result.  The vNext result
is observed only for redacted comparison, so a shadow error or mismatch cannot
change business output or write Authority state.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from memoryhub.application.formation_shadow import (
    FormationShadowService,
    ShadowComparisonReport,
)
from memoryhub.application.rollout_service import RolloutController
from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind
from memoryhub.observability.trace_policy import TraceCategory
from memoryhub.observability.trace_store import TraceStore


@dataclass(frozen=True, slots=True)
class DualReadDifference:
    kind: str
    count: int = 1
    reason_code: str = ""


@dataclass(frozen=True, slots=True)
class DualReadComparisonReport:
    request_id: str
    trace_id: str
    tenant_id: str
    user_id: str
    legacy_count: int
    vnext_count: int
    legacy_ids_hash: str
    vnext_ids_hash: str
    differences: tuple[DualReadDifference, ...] = ()
    policy_leak_count: int = 0
    cross_tenant_count: int = 0
    forget_leak_count: int = 0
    vnext_error: str = ""
    legacy_result_returned: bool = True
    redacted: bool = True

    @property
    def safe(self) -> bool:
        return (
            not self.vnext_error
            and self.policy_leak_count == 0
            and self.cross_tenant_count == 0
            and self.forget_leak_count == 0
        )


@dataclass(frozen=True, slots=True)
class DualReadResult:
    legacy_response: Any
    report: DualReadComparisonReport
    vnext_response: Any = None


@dataclass(frozen=True, slots=True)
class RolloutReadResult:
    """The one result-selection boundary shared by every read adapter."""

    response: Any
    mode: str
    served_by: str
    report: DualReadComparisonReport | None = None


@dataclass
class VNextShadowReport:
    """Aggregated report shape suitable for a redacted evaluation artifact."""

    report_version: str = "vnext/shadow/v1"
    redacted: bool = True
    formation_runs: int = 0
    retrieval_runs: int = 0
    difference_counts: dict[str, int] = field(default_factory=dict)
    policy_leak_count: int = 0
    forget_leak_count: int = 0
    safe: bool = True

    def add_formation(self, report: ShadowComparisonReport) -> None:
        self.formation_runs += 1
        for difference in report.differences:
            self.difference_counts[difference.kind] = (
                self.difference_counts.get(difference.kind, 0) + 1
            )
        self.safe = self.safe and report.safe

    def add_retrieval(self, report: DualReadComparisonReport) -> None:
        self.retrieval_runs += 1
        for difference in report.differences:
            self.difference_counts[difference.kind] = (
                self.difference_counts.get(difference.kind, 0) + difference.count
            )
        self.policy_leak_count += report.policy_leak_count
        self.forget_leak_count += report.forget_leak_count
        self.safe = self.safe and report.safe

    def to_redacted_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowReadService:
    """Coordinate Formation Shadow and legacy-preserving Retrieval dual-read."""

    def __init__(
        self,
        *,
        formation_shadow: FormationShadowService | None = None,
        trace_store: TraceStore | None = None,
    ) -> None:
        self.formation_shadow = formation_shadow or FormationShadowService()
        self.trace_store = trace_store or TraceStore()
        self.report = VNextShadowReport()

    def compare_formation(self, *args: Any, **kwargs: Any) -> ShadowComparisonReport:
        result = self.formation_shadow.compare_event(*args, **kwargs)
        self.report.add_formation(result)
        return result

    def dual_read(
        self,
        request: Any,
        *,
        legacy_reader: Callable[[Any], Any],
        vnext_reader: Callable[[Any], Any],
    ) -> DualReadResult:
        request_id = str(getattr(request, "request_id", "request-shadow"))
        trace_id = str(getattr(request, "trace_id", request_id))
        tenant_id = str(getattr(request, "tenant_id", "unknown-tenant"))
        user_id = str(getattr(request, "user_id", "unknown-user"))
        started = time.perf_counter()
        legacy_response = legacy_reader(request)
        vnext_error = ""
        try:
            vnext_response = vnext_reader(request)
        except Exception as exc:  # shadow must never break the legacy read
            vnext_response = []
            vnext_error = type(exc).__name__

        legacy_items = self._items(legacy_response)
        vnext_items = self._items(vnext_response)
        legacy_ids = [item.get("memory_id", "") for item in legacy_items]
        vnext_ids = [item.get("memory_id", "") for item in vnext_items]
        differences: list[DualReadDifference] = []
        if set(legacy_ids) != set(vnext_ids):
            differences.append(DualReadDifference("RESULT_SET_MISMATCH"))
        elif legacy_ids != vnext_ids:
            differences.append(DualReadDifference("ORDERING_MISMATCH"))

        shared_ids = set(legacy_ids) & set(vnext_ids)
        if any(
            legacy.get("content_version") != current.get("content_version")
            for memory_id in shared_ids
            for legacy in legacy_items
            for current in vnext_items
            if legacy.get("memory_id") == memory_id and current.get("memory_id") == memory_id
        ):
            differences.append(DualReadDifference("VERSION_MISMATCH"))
        if any(
            legacy.get("scope") != current.get("scope")
            for memory_id in shared_ids
            for legacy in legacy_items
            for current in vnext_items
            if legacy.get("memory_id") == memory_id and current.get("memory_id") == memory_id
        ):
            differences.append(DualReadDifference("SCOPE_MISMATCH"))
        if vnext_error:
            differences.append(DualReadDifference("VNEXT_READ_ERROR", reason_code=vnext_error))

        policy_leaks = sum(
            1
            for item in vnext_items
            if item.get("tenant_id") not in {None, "", tenant_id}
            or item.get("user_id") not in {None, "", user_id}
            or str(item.get("status", item.get("evolution_status", ""))).upper()
            in {"DELETED", "SUPERSEDED"}
        )
        cross_tenant = sum(
            1
            for item in vnext_items
            if item.get("tenant_id") not in {None, "", tenant_id}
        )
        forget_leaks = sum(
            1
            for item in vnext_items
            if str(item.get("status", item.get("evolution_status", ""))).upper()
            in {"DELETED", "SUPERSEDED"}
        )
        if policy_leaks:
            differences.append(
                DualReadDifference("POLICY_LEAK", policy_leaks, "TENANT_OR_STATUS")
            )
        if cross_tenant:
            differences.append(
                DualReadDifference("CROSS_TENANT", cross_tenant, "TENANT_MISMATCH")
            )
        if forget_leaks:
            differences.append(
                DualReadDifference("FORGET_LEAK", forget_leaks, "DELETED_OR_SUPERSEDED")
            )

        report = DualReadComparisonReport(
            request_id=request_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id=user_id,
            legacy_count=len(legacy_items),
            vnext_count=len(vnext_items),
            legacy_ids_hash=self._hash_ids(legacy_ids),
            vnext_ids_hash=self._hash_ids(vnext_ids),
            differences=tuple(differences),
            policy_leak_count=policy_leaks,
            cross_tenant_count=cross_tenant,
            forget_leak_count=forget_leaks,
            vnext_error=vnext_error,
        )
        self.report.add_retrieval(report)
        self.trace_store.record(
            TraceSpan(
                span_id=f"span-dual-read-{request_id}",
                trace_id=trace_id,
                kind=TraceSpanKind.RETRIEVAL,
                category=TraceCategory.RETRIEVAL,
                layer="DUAL_READ_SHADOW",
                tenant_id=tenant_id,
                user_id=user_id,
                ids={"request_id": request_id},
                classification={
                    "mode": "dual-read",
                    "legacy_result_returned": True,
                    "difference_count": len(differences),
                    "safe": report.safe,
                },
                scores={"latency_ms": (time.perf_counter() - started) * 1000},
            )
        )
        return DualReadResult(
            legacy_response=legacy_response,
            report=report,
            vnext_response=vnext_response,
        )

    @staticmethod
    def _items(response: Any) -> list[dict[str, Any]]:
        if response is None:
            return []
        if isinstance(response, dict):
            values = response.get("selected_memories", response.get("results", []))
        elif isinstance(response, (list, tuple)):
            values = response
        else:
            values = getattr(response, "selected_memories", None)
            if values is None:
                values = getattr(response, "results", [])
        normalized: list[dict[str, Any]] = []
        for value in values or []:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            elif not isinstance(value, dict):
                try:
                    value = vars(value)
                except TypeError:
                    value = {}
            normalized.append(
                {
                    key: value.get(key)
                    for key in (
                        "memory_id",
                        "tenant_id",
                        "user_id",
                        "content_version",
                        "scope",
                        "scope_level",
                        "status",
                        "evolution_status",
                    )
                    if key in value
                }
            )
        return normalized

    @staticmethod
    def _hash_ids(ids: list[str]) -> str:
        payload = json.dumps(ids, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RolloutReadService:
    """Apply the shared controller decision to one real read request."""

    def __init__(
        self,
        *,
        controller: RolloutController,
        shadow_read: ShadowReadService,
    ) -> None:
        self.controller = controller
        self.shadow_read = shadow_read

    def read(
        self,
        request: Any,
        *,
        legacy_reader: Callable[[Any], Any],
        vnext_reader: Callable[[Any], Any],
    ) -> RolloutReadResult:
        mode = self.controller.current_mode
        if mode == "legacy":
            return RolloutReadResult(
                response=legacy_reader(request), mode=mode, served_by="legacy"
            )
        if mode == "vnext":
            return RolloutReadResult(
                response=vnext_reader(request), mode=mode, served_by="vnext"
            )

        comparison = self.shadow_read.dual_read(
            request, legacy_reader=legacy_reader, vnext_reader=vnext_reader
        )
        selected_vnext = mode == "canary" and self.controller.choose_vnext(request)
        # A failed canary read is fail-closed to legacy.  The controller remains
        # the only mode/traffic decision maker; this is its safety result.
        serve_vnext = selected_vnext and not comparison.report.vnext_error
        response = (
            comparison.vnext_response
            if serve_vnext and mode == "canary"
            else comparison.legacy_response
        )
        self.controller.record_read_observation(comparison.report)
        return RolloutReadResult(
            response=response,
            mode=mode,
            served_by="vnext" if serve_vnext else "legacy",
            report=comparison.report,
        )


__all__ = [
    "DualReadComparisonReport",
    "DualReadDifference",
    "DualReadResult",
    "RolloutReadResult",
    "RolloutReadService",
    "ShadowReadService",
    "VNextShadowReport",
]
