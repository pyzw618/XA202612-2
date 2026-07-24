from __future__ import annotations

import ctypes
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from memoryhub.adapter.schemas import MemoryEvent
from memoryhub.embedding.kylin_client import (
    DEFAULT_DIM,
    KylinEmbeddingClient,
    KylinEmbeddingError,
)


_CANARY = "TOP_SECRET_CANARY_7319"


class _FakeCFunction:
    def __init__(self, function: Callable[..., Any]):
        self._function = function
        self.argtypes: list[Any] = []
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self._function(*args)


def _client_with_library(library: object) -> KylinEmbeddingClient:
    client = object.__new__(KylinEmbeddingClient)
    client._model_name = "test"
    client._dim = DEFAULT_DIM
    client._lib = library
    client._session = ctypes.c_void_p(1)
    client._so_path = None
    return client


def test_memory_event_validation_string_does_not_echo_input() -> None:
    with pytest.raises(ValidationError) as caught:
        MemoryEvent.model_validate(
            {
                "event_id": "evt_safe_error",
                "source_type": "tool_result",
                "event_type": "tool_result",
                "source_hash": "a" * 64,
                "quality": {
                    "score": 1.0,
                    "status": "accepted",
                    "completeness": 1.0,
                    "validity": 1.0,
                    "consistency": 1.0,
                    "freshness": 1.0,
                },
                "tool_calls": [
                    {
                        "call_id": "call_1",
                        "tool_name": "test",
                        "status": _CANARY,
                        "sequence": 1,
                    }
                ],
            }
        )

    assert _CANARY not in str(caught.value)
    assert _CANARY not in repr(caught.value)


def test_request_validation_response_does_not_echo_input_or_context(caplog) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from memoryhub.app import create_app

    request = {
        "events": [
            {
                "event_id": "evt_safe_error",
                "source_type": "tool_result",
                "event_type": "tool_result",
                "user_id": "u1",
                "occurred_at": "2026-07-24T00:00:00Z",
                "text": "safe",
                "payload": {},
                "tool_calls": [
                    {
                        "call_id": "call_1",
                        "tool_name": "test",
                        "arguments": {},
                        "result": None,
                        "status": _CANARY,
                        "sequence": 1,
                        "error": "",
                    }
                ],
                "schema_version": "1.1",
                "source_hash": "a" * 64,
                "redactions": [],
                "quality": {
                    "score": 1.0,
                    "status": "accepted",
                    "completeness": 1.0,
                    "validity": 1.0,
                    "consistency": 1.0,
                    "freshness": 1.0,
                    "issues": [],
                },
                _CANARY: "extra input must not become a location",
            }
        ]
    }

    response = TestClient(create_app()).post("/api/memory/events", json=request)

    assert response.status_code == 422
    assert _CANARY not in response.text
    assert _CANARY not in caplog.text
    assert set(response.json()) == {"detail"}
    for error in response.json()["detail"]:
        assert set(error) == {"type", "loc"}
        assert "input" not in error
        assert "msg" not in error
        assert "ctx" not in error
        assert "body" not in error


def test_embedding_call_failure_uses_a_stable_non_leaking_error(caplog) -> None:
    library = type(
        "FailingLibrary",
        (),
        {"text_embedding": _FakeCFunction(lambda *_args: False)},
    )()
    client = _client_with_library(library)

    with pytest.raises(
        KylinEmbeddingError, match=r"^embedding\.call_failed$"
    ) as caught:
        client.embed(_CANARY)

    assert _CANARY not in str(caught.value)
    assert _CANARY not in repr(caught.value)
    assert _CANARY not in caplog.text
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_embedding_symbol_lookup_failure_uses_a_stable_non_leaking_error(
    caplog,
) -> None:
    class HostileLibrary:
        @property
        def text_embedding(self) -> object:
            raise RuntimeError(_CANARY)

    client = _client_with_library(HostileLibrary())

    with pytest.raises(
        KylinEmbeddingError, match=r"^embedding\.backend_error$"
    ) as caught:
        client.embed(_CANARY)

    assert _CANARY not in str(caught.value)
    assert _CANARY not in repr(caught.value)
    assert _CANARY not in caplog.text
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_embedding_backend_message_is_never_exposed(caplog) -> None:
    message_calls = 0

    def embed(_session: object, _text: bytes, result_pointer: object) -> bool:
        ctypes.cast(result_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = (
            ctypes.c_void_p(1)
        )
        return True

    def message(_result: object) -> bytes:
        nonlocal message_calls
        message_calls += 1
        return _CANARY.encode()

    library = type(
        "ErrorLibrary",
        (),
        {
            "text_embedding": _FakeCFunction(embed),
            "embedding_result_get_error_code": _FakeCFunction(lambda _result: 73),
            "embedding_result_get_error_message": _FakeCFunction(message),
            "embedding_result_destroy": _FakeCFunction(lambda _result: None),
        },
    )()
    client = _client_with_library(library)

    with pytest.raises(KylinEmbeddingError, match=r"^embedding\.sdk_error$") as caught:
        client.embed(_CANARY)

    assert message_calls == 0
    assert _CANARY not in str(caught.value)
    assert _CANARY not in repr(caught.value)
    assert _CANARY not in caplog.text
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
