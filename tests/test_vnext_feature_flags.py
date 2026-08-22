from __future__ import annotations

import pytest

from memoryhub.config import (
    AppConfig,
    EmbeddingConfig,
    ProductionGateError,
    RuntimeConfig,
    VectorEngineConfig,
    VNextConfig,
    validate_production_gate,
)


@pytest.mark.parametrize("mode", ["legacy", "shadow", "dual-read", "vnext"])
def test_non_canary_vnext_modes_are_explicitly_constructible(mode: str) -> None:
    config = VNextConfig(mode=mode)

    assert config.mode == mode
    assert config.canary_percent == 0
    assert config.policy_required is True
    assert config.authority_single_writer is True


@pytest.mark.parametrize("percentage", [5, 25, 50, 100])
def test_canary_mode_accepts_only_documented_percentages(percentage: int) -> None:
    config = VNextConfig(mode="canary", canary_percent=percentage)

    assert config.mode == "canary"
    assert config.canary_percent == percentage


def test_invalid_vnext_mode_and_rollout_are_rejected() -> None:
    with pytest.raises(ValueError, match="vnext.mode must be one of"):
        VNextConfig(mode="unknown")
    with pytest.raises(ValueError, match="one of 5, 25, 50, 100"):
        VNextConfig(mode="canary", canary_percent=10)
    with pytest.raises(ValueError, match="only valid in canary"):
        VNextConfig(mode="vnext", canary_percent=5)


def _production_config(vnext: VNextConfig) -> AppConfig:
    return AppConfig(
        runtime=RuntimeConfig(mode="production", allow_fallback=False),
        vnext=vnext,
        embedding=EmbeddingConfig(provider="kylin", dimension=768),
        vector_engine=VectorEngineConfig(
            provider="milvus", app_id="test-app-id", dimension=768
        ),
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("policy_required", False, "policy_required must be true"),
        ("authority_single_writer", False, "authority_single_writer must be true"),
        ("allow_policy_bypass", True, "allow_policy_bypass must be false"),
    ],
)
def test_production_gate_rejects_unsafe_vnext_flags(
    field: str, value: bool, message: str
) -> None:
    flags = VNextConfig(**{field: value})

    with pytest.raises(ProductionGateError, match=message):
        validate_production_gate(_production_config(flags))


def test_production_canary_keeps_policy_and_single_writer_invariants() -> None:
    flags = VNextConfig(mode="canary", canary_percent=5)

    validate_production_gate(_production_config(flags))
