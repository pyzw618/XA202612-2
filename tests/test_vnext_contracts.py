from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryhub.domain.contracts import (
    Activation,
    ActivationStatus,
    Candidate,
    EpisodeEventContract,
    EpisodeSnapshot,
    Evidence,
    EvolutionAction,
    EvolutionStatus,
    FormationStatus,
    LifecycleLayer,
    Lineage,
    LongTermEnvelope,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
    WorkingPatch,
    WorkingSnapshot,
    map_legacy_memory_level,
    map_legacy_memory_status,
    map_legacy_memory_type,
)

FIXTURE = Path(__file__).parent / "fixtures" / "vnext" / "minimal_contracts.json"


def test_vnext_dimensions_are_orthogonal_and_stable() -> None:
    assert {item.value for item in LifecycleLayer} == {"WORKING", "EPISODE", "LONG_TERM"}
    assert {item.value for item in MemoryType} == {
        "PREFERENCE",
        "SEMANTIC",
        "PROCEDURAL",
        "EPISODIC",
    }
    assert EvolutionAction.SUPERSEDE.value != EvolutionStatus.SUPERSEDED.value
    assert ActivationStatus.IN_CONTEXT.value != LifecycleLayer.WORKING.value


def test_retrieval_intent_has_exactly_seven_unique_values() -> None:
    values = [item.value for item in RetrievalIntent]

    assert len(values) == 7
    assert len(values) == len(set(values))
    assert set(values) == {
        "CURRENT_STATE",
        "TASK_HISTORY",
        "PREFERENCE",
        "SEMANTIC_FACT",
        "PROCEDURE",
        "EXPERIENCE",
        "MIXED",
    }


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("short", LifecycleLayer.WORKING),
        ("mid", LifecycleLayer.EPISODE),
        ("long", LifecycleLayer.LONG_TERM),
    ],
)
def test_legacy_level_maps_only_to_lifecycle_layer(
    legacy: str, expected: LifecycleLayer
) -> None:
    assert map_legacy_memory_level(legacy) is expected


def test_legacy_types_map_to_explicit_memory_types() -> None:
    assert map_legacy_memory_type("preference") is MemoryType.PREFERENCE
    assert map_legacy_memory_type("knowledge", knowledge_type="fact") is MemoryType.SEMANTIC
    assert map_legacy_memory_type("knowledge", knowledge_type="workflow") is MemoryType.PROCEDURAL
    assert map_legacy_memory_type("knowledge", knowledge_type="case") is MemoryType.EPISODIC


def test_legacy_status_does_not_promote_unknown_pending_data() -> None:
    assert map_legacy_memory_status("active") is EvolutionStatus.ACTIVE
    assert map_legacy_memory_status("deleted") is EvolutionStatus.DELETED

    with pytest.raises(ValueError, match="unsupported legacy memory status"):
        map_legacy_memory_status("pending")


def test_unsupported_legacy_values_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported legacy memory level"):
        map_legacy_memory_level("unknown")
    with pytest.raises(ValueError, match="unsupported legacy memory type"):
        map_legacy_memory_type("knowledge", knowledge_type="unknown")


def test_scope_contains_long_term_precedence_and_session_boundary() -> None:
    assert [item.value for item in MemoryScope][:5] == [
        "TASK",
        "PROJECT",
        "APPLICATION",
        "DOMAIN",
        "GLOBAL",
    ]
    assert MemoryScope.SESSION.value == "SESSION"


def test_formation_status_is_distinct_from_evolution_status() -> None:
    assert FormationStatus.CANDIDATE.value == "CANDIDATE"
    assert "CANDIDATE" not in {item.value for item in EvolutionStatus}


def test_minimal_json_fixture_validates_all_vnext_core_objects() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    models = {
        "event": MemoryEventContract,
        "working_patch": WorkingPatch,
        "working_snapshot": WorkingSnapshot,
        "episode_event": EpisodeEventContract,
        "episode_snapshot": EpisodeSnapshot,
        "candidate": Candidate,
        "long_term": LongTermEnvelope,
        "evidence": Evidence,
        "lineage": Lineage,
        "activation": Activation,
    }

    validated = {name: model.model_validate(data[name]) for name, model in models.items()}

    assert all(item.schema_version == "vnext/v1" for item in validated.values())
    assert validated["candidate"].formation_status is FormationStatus.CANDIDATE
    assert validated["long_term"].layer is LifecycleLayer.LONG_TERM
    assert validated["activation"].status is ActivationStatus.IN_CONTEXT


def test_vnext_json_round_trip_preserves_governance_and_version_fields() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    event = MemoryEventContract.model_validate(data["event"])
    dumped = event.model_dump(mode="json")
    round_tripped = MemoryEventContract.model_validate(dumped)

    assert round_tripped.tenant_id == "tenant-a"
    assert round_tripped.schema_version == "vnext/v1"
    assert round_tripped.content_version == 1
    assert round_tripped.policy_action == "ALLOW"


def test_vnext_models_reject_unknown_fields_and_invalid_versions() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["event"]
    data["unexpected"] = "must fail"

    with pytest.raises(ValueError):
        MemoryEventContract.model_validate(data)

    data.pop("unexpected")
    data["schema_version"] = "vnext/v2"
    with pytest.raises(ValueError):
        MemoryEventContract.model_validate(data)
