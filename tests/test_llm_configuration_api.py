from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig, load_config


def _client(tmp_path) -> tuple[TestClient, object]:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """llm:\n  provider: \"retired_local\"\n  api_base: \"https://old.example/v1\"\n  api_key: \"old-key\"\n  model: \"old-model\"\n""",
        encoding="utf-8",
    )
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "memoryhub.db"),
            vector_index_path=str(tmp_path / "vector"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
        config_path=str(config_path),
    )
    config.llm.api_base = "https://old.example/v1"
    config.llm.api_key = "old-key"
    config.llm.model = "old-model"
    return TestClient(create_app(config)), config_path


def test_cloud_llm_config_is_write_only_and_persisted(tmp_path) -> None:
    client, config_path = _client(tmp_path)
    with client:
        response = client.put(
            "/api/memory/system/llm",
            json={
                "api_base": "https://cloud.example/v1/",
                "api_key": "secret-value",
                "model": "cloud-model",
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["restart_required"] is True
        assert result["llm"] == {
            "provider": "openai_compatible",
            "api_base": "https://cloud.example/v1",
            "model": "cloud-model",
            "api_key_configured": True,
        }
        assert "secret-value" not in response.text

        visible = client.get("/api/memory/system/config")
        assert visible.status_code == 200
        assert visible.json()["llm"] == {
            "provider": "openai_compatible",
            "api_base": "https://cloud.example/v1",
            "model": "cloud-model",
            "api_key_configured": True,
        }

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["llm"] == {
        "api_base": "https://cloud.example/v1",
        "api_key": "secret-value",
        "model": "cloud-model",
    }


def test_cloud_llm_config_requires_https_and_a_key(tmp_path) -> None:
    client, _ = _client(tmp_path)
    with client:
        insecure = client.put(
            "/api/memory/system/llm",
            json={"api_base": "http://localhost:11434/v1", "model": "model"},
        )
        assert insecure.status_code == 422
        assert insecure.json()["detail"]["code"] == "llm.api_base_must_be_https"

    no_key_config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "missing-key.db"),
            vector_index_path=str(tmp_path / "missing-key-vector"),
            evidence_path=str(tmp_path / "missing-key-evidence"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(no_key_config)) as no_key_client:
        response = no_key_client.put(
            "/api/memory/system/llm",
            json={"api_base": "https://cloud.example/v1", "model": "model"},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "llm.api_key_required"


def test_load_config_honors_llm_api_environment_variables(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "llm:\n  provider: \"retired_local\"\n  api_base: \"https://yaml.example/v1\"\n  api_key: \"yaml-key\"\n  model: \"yaml-model\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_API_BASE", "https://env.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    config = load_config(str(config_path))

    assert config.config_path == str(config_path.resolve())
    assert config.llm.api_base == "https://env.example/v1"
    assert config.llm.api_key == "env-key"
    assert config.llm.model == "env-model"
