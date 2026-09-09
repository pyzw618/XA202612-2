"""Retrieval Planner: maps a routed intent to a multi-channel recall plan.

The planner is stateless and algorithm-free; it only decides *which* channels
are necessary for an intent and how their results should be scoped.  Actual
execution of the plan is performed by the retrieval service built in later
S3 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoryhub.adapter.vnext_schemas import ConsistencyMode, MemoryRetrievalRequest
from memoryhub.domain.contracts import LifecycleLayer, MemoryType, RetrievalIntent
from memoryhub.retrieval.intent_router import RoutedIntent


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """A deterministic, explainable recall plan for one retrieval request."""

    intent: RetrievalIntent
    enabled_channels: list[str] = field(default_factory=list)
    required_layers: list[LifecycleLayer] = field(default_factory=list)
    required_types: list[MemoryType] = field(default_factory=list)
    authority_checked: bool = False
    top_k: int = 5
    vector_top_k: int = 10
    keyword_top_k: int = 10
    metadata_filter: dict[str, Any] = field(default_factory=dict)
    degraded_channels: list[str] = field(default_factory=list)
    reason: str = ""


class RetrievalPlanner:
    """Translate a routed intent into a channel plan with safe fallbacks.

    Channel names:
        * ``vector``      -- dense/semantic search (Milvus/FAISS)
        * ``keyword``     -- sparse/BM25 search
        * ``metadata``    -- scope/type/status filtering
        * ``working``     -- current working state direct lookup
        * ``episode``     -- task episode history lookup
        * ``authority``   -- Authority-checked read of Long-Term memory

    The planner is intentionally conservative: it enables only the channels that
    are strictly necessary for the intent, and degrades gracefully when a
    required channel is unavailable.
    """

    ALL_CHANNELS: tuple[str, ...] = (
        "vector",
        "keyword",
        "metadata",
        "working",
        "episode",
        "authority",
    )

    # Which channels each non-MIXED intent needs.  Long-Term intents share the
    # same base set (vector/keyword/metadata/authority) because any of them may
    # surface the correct memory; current-state and task-history are narrower.
    _INTENT_CHANNELS: dict[RetrievalIntent, list[str]] = {
        RetrievalIntent.CURRENT_STATE: ["working", "metadata"],
        RetrievalIntent.TASK_HISTORY: ["episode", "metadata"],
        RetrievalIntent.PREFERENCE: ["vector", "keyword", "metadata", "authority"],
        RetrievalIntent.SEMANTIC_FACT: ["vector", "keyword", "metadata", "authority"],
        RetrievalIntent.PROCEDURE: ["vector", "keyword", "metadata", "authority"],
        RetrievalIntent.EXPERIENCE: ["vector", "keyword", "metadata", "authority", "episode"],
        RetrievalIntent.MIXED: list(ALL_CHANNELS),
    }

    def __init__(
        self,
        *,
        available_channels: list[str] | None = None,
        production_mode: bool = False,
        production_requires_milvus: bool = True,
    ) -> None:
        self.available_channels = set(available_channels or list(self.ALL_CHANNELS))
        self.production_mode = production_mode
        self.production_requires_milvus = production_requires_milvus

    def plan(
        self,
        request: MemoryRetrievalRequest,
        routed: RoutedIntent,
    ) -> RetrievalPlan:
        """Create a recall plan from a vNext request and its routed intent."""
        requested_channels = list(self._INTENT_CHANNELS.get(routed.intent, list(self.ALL_CHANNELS)))
        # The legacy REST/MCP contract already enters vNext through a composite
        # legacy retriever exposed as the vector channel. Running all vNext
        # channels again changes projection and filtering semantics, so keep
        # that compatibility request on its single delegated channel.
        if request.legacy_compatibility and "vector" in self.available_channels:
            requested_channels = ["vector"]

        # Authority-checked consistency always adds an authority read.
        authority_checked = request.consistency is ConsistencyMode.AUTHORITY_CHECKED
        if authority_checked and "authority" not in requested_channels:
            requested_channels.append("authority")

        enabled, degraded = self._split_channels(requested_channels)

        # Production gate: vector search must use Milvus unless explicitly
        # degraded.  If vector is unavailable in production, record it as
        # degraded rather than silently switching to FAISS.
        if self.production_mode and self.production_requires_milvus:
            if "vector" in enabled and not self._has_milvus():
                enabled.remove("vector")
                if "vector" not in degraded:
                    degraded.append("vector")

        # If a current-state or task-history channel is degraded, broadening to
        # long-term channels is a safe fallback that still respects scope.
        if routed.intent in (RetrievalIntent.CURRENT_STATE, RetrievalIntent.TASK_HISTORY):
            enabled = self._ensure_fallback_channels(enabled, degraded)

        top_k = max(1, min(100, request.page_size))
        candidate_multiplier = 2

        layers = list(request.requested_layers or routed.target_layers)
        if not layers:
            layers = self._default_layers_for_intent(routed.intent)

        types = list(request.requested_types or routed.target_types)
        if request.memory_types and not request.requested_types:
            requested = {str(value).strip().lower() for value in request.memory_types}
            type_map = {
                "preference": MemoryType.PREFERENCE,
                "knowledge": MemoryType.SEMANTIC,
                "fact": MemoryType.SEMANTIC,
                "semantic": MemoryType.SEMANTIC,
                "procedural": MemoryType.PROCEDURAL,
                "episodic": MemoryType.EPISODIC,
            }
            types = list(dict.fromkeys(type_map[value] for value in requested if value in type_map))
        if routed.intent is RetrievalIntent.MIXED and not types:
            types = list(MemoryType)

        metadata_filter = self._build_metadata_filter(request, layers, types)

        return RetrievalPlan(
            intent=routed.intent,
            enabled_channels=enabled,
            required_layers=layers,
            required_types=types,
            authority_checked=authority_checked,
            top_k=top_k,
            vector_top_k=top_k * candidate_multiplier,
            keyword_top_k=top_k * candidate_multiplier,
            metadata_filter=metadata_filter,
            degraded_channels=degraded,
            reason=self._reason(routed, enabled, degraded, authority_checked),
        )

    def _split_channels(self, requested: list[str]) -> tuple[list[str], list[str]]:
        enabled = [ch for ch in requested if ch in self.available_channels]
        degraded = [ch for ch in requested if ch not in self.available_channels]
        return enabled, degraded

    def _ensure_fallback_channels(self, enabled: list[str], degraded: list[str]) -> list[str]:
        """For state/history queries, keep at least metadata + authority readable
        when those channels are actually available."""
        fallback = list(enabled)
        for ch in ("metadata", "authority"):
            if ch in self.available_channels and ch not in fallback and ch not in degraded:
                fallback.append(ch)
        return fallback

    @staticmethod
    def _default_layers_for_intent(intent: RetrievalIntent) -> list[LifecycleLayer]:
        return {
            RetrievalIntent.CURRENT_STATE: [LifecycleLayer.WORKING],
            RetrievalIntent.TASK_HISTORY: [LifecycleLayer.EPISODE],
        }.get(intent, [LifecycleLayer.LONG_TERM])

    @staticmethod
    def _build_metadata_filter(
        request: MemoryRetrievalRequest,
        layers: list[LifecycleLayer],
        types: list[MemoryType],
    ) -> dict[str, Any]:
        filter_map: dict[str, Any] = {}
        if request.scope_level is not None:
            filter_map["scope_level"] = request.scope_level.value
        if request.scope:
            filter_map["scope"] = request.scope
        if layers:
            filter_map["layers"] = [layer.value for layer in layers]
        if types:
            filter_map["types"] = [memory_type.value for memory_type in types]
        if request.memory_types:
            filter_map["requested_types"] = list(request.memory_types)
        if request.min_confidence > 0:
            filter_map["min_confidence"] = request.min_confidence
        if request.scenes:
            filter_map["scenes"] = list(request.scenes)
        if request.task_types:
            filter_map["task_types"] = list(request.task_types)
        if request.tenant_id:
            filter_map["tenant_id"] = request.tenant_id
        if request.user_id:
            filter_map["user_id"] = request.user_id
        return filter_map

    @staticmethod
    def _has_milvus() -> bool:
        """Best-effort probe; the runtime vector engine may still be unavailable."""
        try:
            from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever  # noqa: F401

            return True
        except Exception:
            return False

    @staticmethod
    def _reason(
        routed: RoutedIntent,
        enabled: list[str],
        degraded: list[str],
        authority_checked: bool,
    ) -> str:
        parts = [
            f"intent={routed.intent.value}",
            f"confidence={routed.confidence}",
            f"channels={'+'.join(enabled)}",
        ]
        if degraded:
            parts.append(f"degraded={'+'.join(degraded)}")
        if authority_checked:
            parts.append("authority_checked=true")
        return "; ".join(parts)


__all__ = ["RetrievalPlan", "RetrievalPlanner"]
