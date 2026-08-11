from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "claudecode-integration" / "scripts" / "start_memoryhub_server.py"
sys.path.insert(0, str(REPO_ROOT))
spec = importlib.util.spec_from_file_location("claude_start_memoryhub_server", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

_ENV_NAMES = (
    "MEMORYHUB_AUDIT_HMAC_KEY",
    "MEMORYHUB_QUARANTINE_KEY",
    "MEMORYHUB_USER_RULE_KEY",
)


def test_dev_config_uses_one_stable_data_root(tmp_path) -> None:
    config = module._build_dev_config(tmp_path / "memoryhub-data")
    root = tmp_path / "memoryhub-data"

    assert Path(config.storage.db_path) == root / "memoryhub.db"
    assert Path(config.safety.key_store.path) == (
        root / "security" / "safety-keys.json"
    )
    assert Path(config.safety.audit.directory) == root / "safety-audit"
    assert Path(config.safety.quarantine.directory) == root / "review-quarantine"


def test_old_dev_key_file_is_imported_without_generating_new_values(tmp_path) -> None:
    previous = {name: os.environ.get(name) for name in _ENV_NAMES}
    for name in _ENV_NAMES:
        os.environ.pop(name, None)
    values = {
        name: base64.b64encode(bytes([index]) * 32).decode("ascii")
        for index, name in enumerate(_ENV_NAMES, start=1)
    }
    legacy = tmp_path / "dev-safety-keys.json"
    legacy.write_text(json.dumps(values), encoding="utf-8")
    try:
        module._import_legacy_dev_keys(tmp_path)
        assert {name: os.environ[name] for name in _ENV_NAMES} == values
        from memoryhub.core.safety.key_store import provision_safety_keys

        resolution = provision_safety_keys(module._build_dev_config(tmp_path))
        assert resolution.key_file == tmp_path / "security" / "safety-keys.json"
        assert resolution.key_file.is_file()
    finally:
        for name in _ENV_NAMES:
            os.environ.pop(name, None)
            if previous[name] is not None:
                os.environ[name] = previous[name]
