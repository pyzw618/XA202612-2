from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "opencode-integration" / "scripts"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS))

from start_memoryhub_server import _build_dev_config  # noqa: E402


def test_dev_config_keeps_all_persistent_safety_state_under_data_dir(
    tmp_path,
    monkeypatch,
) -> None:
    launch_directory = tmp_path / "unrelated-launch-directory"
    launch_directory.mkdir()
    monkeypatch.chdir(launch_directory)
    data_directory = tmp_path / "memoryhub-data"

    config = _build_dev_config(data_directory)

    assert Path(config.storage.db_path) == data_directory / "memoryhub.db"
    assert Path(config.storage.vector_index_path) == data_directory / "vector_index"
    assert Path(config.storage.evidence_path) == data_directory / "evidence"
    assert Path(config.safety.key_store.path) == (
        data_directory / "security" / "safety-keys.json"
    )
    assert Path(config.safety.audit.directory) == data_directory / "safety-audit"
    assert Path(config.safety.quarantine.directory) == (
        data_directory / "review-quarantine"
    )
    assert config.safety.user_rules.enabled is False
