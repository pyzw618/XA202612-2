"""阶段一：vector engine app_id 配置与 C ABI 回归契约。"""

from __future__ import annotations

from ctypes import c_char_p, c_int, c_void_p
from pathlib import Path

import pytest

from memoryhub.config import VectorEngineConfig, load_config
from memoryhub.storage.vector_engine._milvus_ctypes import (
    _MilvusCAPI,
    vector_engine_t,
)


class _FakeCFunction:
    """可记录函数签名和调用参数的 ctypes 函数替身。"""

    def __init__(self) -> None:
        self.restype = None
        self.argtypes = None
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> int:
        self.calls.append(args)
        return 0


class _FakeCDLL:
    def __init__(self) -> None:
        self._functions: dict[str, _FakeCFunction] = {}

    def __getattr__(self, name: str) -> _FakeCFunction:
        function = self._functions.setdefault(name, _FakeCFunction())
        return function


class TestVectorEngineAppIdConfiguration:
    def test_vector_engine_config_exposes_app_id(self) -> None:
        config = VectorEngineConfig(provider="milvus", app_id="test-app-id")

        assert config.app_id == "test-app-id"

    def test_yaml_preserves_milvus_app_id(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "vector_engine:\n"
            "  provider: milvus\n"
            "  app_id: test-app-id\n",
            encoding="utf-8",
        )

        config = load_config(str(config_path))

        assert config.vector_engine.app_id == "test-app-id"

    def test_yaml_preserves_kylin_local_vector_settings(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "vector_engine:\n"
            "  provider: milvus\n"
            "  app_id: kylin-memoryhub\n"
            "  local_socket: true\n"
            "  db_path: ~/.local/share/MemoryHub/data/vector-engine.db\n",
            encoding="utf-8",
        )

        config = load_config(str(config_path))

        assert config.vector_engine.local_socket is True
        assert config.vector_engine.db_path.endswith("vector-engine.db")

    @pytest.mark.parametrize("app_id", ["", " ", "\t\n"])
    def test_milvus_rejects_blank_app_id_before_engine_creation(
        self, app_id: str
    ) -> None:
        with pytest.raises(ValueError, match=r"vector_engine\.app_id"):
            VectorEngineConfig(provider="milvus", app_id=app_id)


class TestMilvusCAPIAppIdABI:
    def _api_with_fake_cdll(self) -> tuple[_MilvusCAPI, _FakeCDLL]:
        library = _FakeCDLL()
        api = object.__new__(_MilvusCAPI)
        api._lib = library
        api._bind()
        return api, library

    def test_connect_declares_four_arguments_in_sdk_order(self) -> None:
        api, library = self._api_with_fake_cdll()

        assert library.vector_engine_connect.argtypes == [
            vector_engine_t,
            c_char_p,
            c_char_p,
            c_int,
        ]

    def test_connect_forwards_utf8_app_id_before_host_and_port(self) -> None:
        api, library = self._api_with_fake_cdll()
        handle = c_void_p(123)

        api.connect(handle, "测试-app-id", "127.0.0.1", 19530)

        assert library.vector_engine_connect.calls == [
            (handle, "测试-app-id".encode("utf-8"), b"127.0.0.1", 19530)
        ]

    def test_empty_host_selects_kylin_local_socket(self) -> None:
        api, library = self._api_with_fake_cdll()
        handle = c_void_p(123)

        api.connect(handle, "kylin-memoryhub", "", 19530)

        assert library.vector_engine_connect.calls == [
            (handle, b"kylin-memoryhub", b"", 19530)
        ]

    def test_load_db_file_forwards_persistence_options(self) -> None:
        api, library = self._api_with_fake_cdll()
        handle = c_void_p(123)

        api.load_db_file(
            handle,
            "/home/test/.local/share/MemoryHub/data/vector-engine.db",
            encrypt=True,
            key="secret",
        )

        assert library.vector_engine_load_db_file.calls == [
            (
                handle,
                b"/home/test/.local/share/MemoryHub/data/vector-engine.db",
                1,
                b"secret",
            )
        ]
