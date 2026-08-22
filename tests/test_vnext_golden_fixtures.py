from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from memoryhub.adapter.vnext_schemas import (
    APIError,
    APIErrorCode,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
)
from memoryhub.domain.contracts import (
    Candidate,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
)

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "vnext" / "golden_scenarios.json"
MINIMAL = ROOT / "tests" / "fixtures" / "vnext" / "minimal_contracts.json"
CHECKSUMS = ROOT / "tests" / "fixtures" / "vnext" / "SHA256SUMS.txt"


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_golden_fixture_version_and_hash_are_stable() -> None:
    data = _load()
    assert data["fixture_version"] == "vnext/golden/v1"
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert len(digest) == 64
    expected = CHECKSUMS.read_text(encoding="utf-8").split()[0]
    assert digest == expected
    assert MINIMAL.exists()


def test_normal_case_validates_vnext_request() -> None:
    request = MemoryRetrievalRequest.model_validate(_load()["normal"]["request"])
    assert request.api_version == "vnext/v1"
    assert request.consistency.value == "AUTHORITY_CHECKED"


def test_conflict_candidates_are_review_and_scoped() -> None:
    data = _load()["conflict"]
    left = Candidate.model_validate(data["left"])
    right = Candidate.model_validate(data["right"])
    assert left.status.value == data["expected_action"]
    assert right.status.value == data["expected_action"]
    assert left.normalized_key == right.normalized_key
    assert left.scope == right.scope
    assert left.candidate_id not in {"memory-docx", "memory-pdf"}


def test_sensitive_case_has_review_action_and_no_raw_secret() -> None:
    event_data = _load()["sensitive"]["event"]
    event = MemoryEventContract.model_validate(event_data)
    serialized = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    assert event.policy_action == "REVIEW"
    assert event_data["payload"].keys() == {"content_ref"}
    assert "password" not in serialized.lower()
    assert "api_key" not in serialized.lower()


def test_duplicate_retry_and_expired_version_fail_closed() -> None:
    data = _load()
    duplicate = data["duplicate"]
    assert duplicate["first"] == duplicate["retry"]
    assert duplicate["expected"]["new_evidence_count"] == 0

    with pytest.raises(ValueError):
        MemoryRetrievalRequest.model_validate(data["expired_version"]["request"])
    error = APIError(code=APIErrorCode.VERSION_CONFLICT, message="expired API version")
    assert error.code is APIErrorCode.VERSION_CONFLICT


def test_deleted_memory_and_degraded_response_cannot_look_like_full_success() -> None:
    data = _load()
    deleted = LongTermEnvelope.model_validate(data["deleted"]["memory"])
    response = MemoryRetrievalResponse.model_validate(data["degraded_response"]["response"])

    assert deleted.evolution_status is EvolutionStatus.DELETED
    assert data["deleted"]["expected"]["ordinary_retrieval_allowed"] is False
    assert response.completeness == "PARTIAL"
    assert response.degraded_channels
    assert response.warnings
