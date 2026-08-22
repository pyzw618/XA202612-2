from pathlib import Path

ADR = Path(__file__).parents[1] / "docs" / "design" / "adr" / "ADR-vnext-memory-architecture.md"


def test_vnext_architecture_adr_freezes_authority_and_projection_boundaries() -> None:
    text = ADR.read_text(encoding="utf-8")

    required_terms = (
        "Authority Store",
        "Projection",
        "Canonical Write Path",
        "Canonical Retrieval Path",
        "Policy/Safety gate",
        "idempotency check",
        "Evidence",
        "Lineage",
        "Outbox",
        "vnext/v1",
    )
    for term in required_terms:
        assert term in text


def test_vnext_architecture_adr_lists_forbidden_cross_layer_calls() -> None:
    text = ADR.read_text(encoding="utf-8")

    forbidden_rules = (
        "direct long-term repository save",
        "mutate Authority",
        "write Long-Term Authority",
        "infer or rewrite Authority from index contents",
        "bypass tenant/actor authorization",
        "copy business algorithms",
    )
    for rule in forbidden_rules:
        assert rule in text


def test_vnext_architecture_adr_defines_reversible_rollout_modes() -> None:
    text = ADR.read_text(encoding="utf-8")

    for mode in ("legacy", "shadow", "dual-read", "canary", "vnext"):
        assert f"`{mode}`" in text
    assert "It does not delete or rewrite correct Authority data." in text
