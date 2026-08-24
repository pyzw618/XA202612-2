from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_public_memory_api_and_event_coordinator_have_no_direct_repository_save():
    """Production request paths must route Preference/Knowledge writes through Domain Writer."""
    for relative_path in (
        "memoryhub/adapter/api.py",
        "memoryhub/adapter/service.py",
        "memoryhub/core/processing.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "pref_repo.save(" not in source
        assert "know_repo.save(" not in source
        assert "repo.save(selected_memory)" not in source


def test_adapter_layer_has_no_direct_memory_repository_save():
    """The whole REST adapter must never persist memory via repositories directly
    (event/vector saves are allowed; memory writes go through the unified writer)."""
    violations = []
    for path in (ROOT / "memoryhub" / "adapter").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pattern in ("pref_repo.save(", "know_repo.save(", "repo.save(selected_memory)"):
            if pattern in source:
                violations.append((path.relative_to(ROOT).as_posix(), pattern))
    assert violations == []


def test_fact_legacy_insert_sink_removed_with_fact_module():
    """legacy FactStore.insert_fact 已随 core/fact 删除，全库零残留。"""
    violations = []
    for path in (ROOT / "memoryhub").rglob("*.py"):
        if ".insert_fact(" in path.read_text(encoding="utf-8"):
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []


def test_vnext_canonical_endpoint_has_no_direct_repository_writes():
    """vNext canonical write endpoint must route every durable mutation through
    CanonicalWriteService; it must never touch ORM rows or repository save methods."""
    source = (ROOT / "memoryhub" / "adapter" / "vnext_api.py").read_text(encoding="utf-8")
    forbidden = (
        "EventRow",
        "WorkingStateRow",
        "EpisodeRow",
        "IdempotencyRecordRow",
        "session.add(",
        "session.commit(",
        "session.delete(",
        "db.session",
        ".save(",
    )
    found = [p for p in forbidden if p in source]
    assert found == [], f"vnext_api.py direct write patterns: {found}"


def test_agent_replay_and_step_delegate_to_canonical_write_service():
    """Agent replay/step must call canonical_write_service.write and never fall back to
    direct event repository saves in the execute path."""
    source = (ROOT / "memoryhub" / "adapter" / "agent_api.py").read_text(encoding="utf-8")
    assert "canonical.write(" in source or "canonical_write_service.write(" in source
    # Ensure the replay/step routes do not contain a direct event repo save.
    replay_start = source.find("@router.post(\"/replay\")")
    step_start = source.find("@router.post(\"/step\")")
    actions_start = source.find("@router.post(\"/actions/{action_id}/decision\")")
    replay_body = source[replay_start:step_start]
    step_body = source[step_start:actions_start]
    for body, name in ((replay_body, "replay"), (step_body, "step")):
        assert "canonical_write_service" in body
        assert "repo.batch_save(" not in body
        assert "EventRow" not in body
        assert "session.add(" not in body


def test_agent_integration_entrypoints_call_rest_not_repositories():
    """CLI, MCP and SDK must build REST payloads through MemoryHubClient rather than
    importing or calling repository classes directly."""
    violations = []
    for relative_path in (
        "agent-integration/memoryhub_client/client.py",
        "agent-integration/memoryhub_mcp/tools.py",
        "agent-integration/memoryhub_cli/cli.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in ("EventRow", "WorkingStateRow", "EpisodeRow", "IdempotencyRecordRow",
                        "session.add(", "session.commit(", "session.delete(", ".save("):
            if pattern in source:
                violations.append((relative_path, pattern))
    assert violations == []
