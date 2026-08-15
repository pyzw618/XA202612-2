from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_public_memory_api_and_event_coordinator_have_no_direct_repository_save():
    """Production request paths must route Preference/Knowledge writes through Domain Writer."""
    for relative_path in (
        "memoryhub/adapter/api.py",
        "memoryhub/core/processing.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "pref_repo.save(" not in source
        assert "know_repo.save(" not in source
        assert "repo.save(selected_memory)" not in source


def test_fact_public_insert_sink_is_not_called_outside_fact_store():
    """Fact pipeline must use the private transactional persistence sink."""
    violations = []
    for path in (ROOT / "memoryhub").rglob("*.py"):
        if path.as_posix().endswith("core/fact/store.py"):
            continue
        if ".insert_fact(" in path.read_text(encoding="utf-8"):
            violations.append(path.relative_to(ROOT).as_posix())
    assert violations == []
