from __future__ import annotations

import json

from memoryhub_client.config import ClientConfig, current_user_id
from memoryhub_mcp.config import load_config as load_mcp_config


def _clean_identity_env(monkeypatch, tmp_path) -> None:
    for name in (
        "MEMORYHUB_USER_ID",
        "SUDO_USER",
        "USER",
        "LOGNAME",
        "USERNAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def test_current_user_uses_linux_login(monkeypatch, tmp_path):
    _clean_identity_env(monkeypatch, tmp_path)
    monkeypatch.setenv("USER", "ethan")
    assert current_user_id() == "ethan"


def test_current_user_uses_sudo_invoker_instead_of_root(monkeypatch, tmp_path):
    _clean_identity_env(monkeypatch, tmp_path)
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("SUDO_USER", "ethan")
    assert current_user_id() == "ethan"


def test_client_and_mcp_share_configured_memory_user(monkeypatch, tmp_path):
    _clean_identity_env(monkeypatch, tmp_path)
    monkeypatch.setenv("USER", "ethan")
    config_dir = tmp_path / "config" / "memoryhub"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"user_id": "global"}), encoding="utf-8"
    )

    assert ClientConfig.load(cwd=tmp_path).user_id == "global"
    assert load_mcp_config().user_id == "global"


def test_client_and_mcp_default_to_same_linux_user(monkeypatch, tmp_path):
    _clean_identity_env(monkeypatch, tmp_path)
    monkeypatch.setenv("USER", "ethan")

    assert ClientConfig.load(cwd=tmp_path).user_id == "ethan"
    assert load_mcp_config().user_id == "ethan"
