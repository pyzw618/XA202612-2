"""真机评测 harness 的离线单元测试。

这些测试不访问网络，只覆盖传输层的请求构造/断言、环境指纹比对与数据集
守卫。真机联通性由 ``evaluation/runners/run_live_four_metrics.py`` 的
前置门负责。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.live import LiveClient, fingerprint
from evaluation.live.client import ServedMismatch
from evaluation.live.datasets import (
    DatasetError,
    assert_no_service_derived_labels,
    iter_label_sources,
    load_dataset,
    verify_dataset_hash,
)

STATUS_FIXTURE = {
    "service": "Kylin-MemoryHub",
    "version": "2.0.0",
    "runtime_mode": "production",
    "embedding": {
        "provider": "kylin",
        "dimension": 768,
        "model_name": "ensemble-embd_gte-base_uint8-text",
    },
    "vector_engine": {"provider": "milvus", "collection": "memoryhub", "connected": True},
    "llm": {"provider": "openai_compatible", "model": "qwen-flash"},
    "retrieval": {"type": "MilvusHybridRetriever"},
}


def _client_with(handler) -> LiveClient:
    """构造一个把 ``request`` 换成固定 handler 的客户端（无网络）。"""
    client = LiveClient.__new__(LiveClient)
    client.base_url = "http://example.invalid"
    client.records = []
    client.assert_served = True
    client.timeout_s = 1.0
    client.max_retries = 0
    client._client = None  # type: ignore[assignment]
    client.request = handler  # type: ignore[assignment]
    return client


# ----------------------------------------------------------------- 指纹


def test_fingerprint_passes_on_kylin_milvus_status() -> None:
    fp = fingerprint.build_environment_fingerprint(
        STATUS_FIXTURE, base_url="http://127.0.0.1:8099"
    )
    assert fingerprint.check_fingerprint(fp, fingerprint.PRODUCTION_REQUIREMENTS) == []


def test_fingerprint_reports_each_mismatch() -> None:
    fp = fingerprint.build_environment_fingerprint(STATUS_FIXTURE)
    mismatches = fingerprint.check_fingerprint(
        fp, ["runtime_mode=development", "embedding.provider=mock", "nope.missing=1"]
    )
    assert len(mismatches) == 3
    assert any("runtime_mode" in item for item in mismatches)
    assert any("缺失" in item for item in mismatches)


def test_fingerprint_boolean_normalisation() -> None:
    fp = fingerprint.build_environment_fingerprint(STATUS_FIXTURE)
    assert fingerprint.check_fingerprint(fp, ["vector_engine.connected=True"]) == []
    assert fingerprint.check_fingerprint(fp, ["vector_engine.connected=False"]) != []


def test_flatten_nested_mapping() -> None:
    assert fingerprint.flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": 1}


# ----------------------------------------------------------------- 客户端


def test_search_rejects_non_vnext_served() -> None:
    client = _client_with(lambda *a, **k: (200, {"served": "legacy", "results": []}))
    with pytest.raises(ServedMismatch):
        client.search(user_id="u", query="q")


def test_search_builds_expected_payload_and_records_served() -> None:
    captured: dict = {}

    def handler(method, path, json_body=None, params=None, allow_retry=True):
        captured.update({"method": method, "path": path, "body": json_body})
        return 200, {"served": "vnext", "results": [{"memory_id": "m1"}], "total_count": 1}

    client = _client_with(handler)
    body = client.search(
        user_id="u1", query="q", top_k=7, context={"scene": "office"}, project_id="p1"
    )
    assert body["total_count"] == 1
    assert captured["path"] == "/api/memory/search"
    assert captured["body"]["top_k"] == 7
    assert captured["body"]["context"] == {"scene": "office"}
    assert captured["body"]["project_id"] == "p1"


def test_search_omits_empty_optional_fields() -> None:
    captured: dict = {}

    def handler(method, path, json_body=None, params=None, allow_retry=True):
        captured["body"] = json_body
        return 200, {"served": "vnext", "results": []}

    client = _client_with(handler)
    client.search(user_id="u1", query="q")
    assert "context" not in captured["body"]
    assert "project_id" not in captured["body"]


# ----------------------------------------------------------------- 数据集


def test_label_source_scan_finds_nested_and_listed() -> None:
    dataset = {
        "samples": [
            {"case_id": "a", "label_source": "spec:rule-A"},
            {"case_id": "b", "meta": {"label_source": "observed:run1"}},
        ]
    }
    found = dict(iter_label_sources(dataset))
    assert any("observed:run1" == value for value in found.values())


def test_service_derived_labels_are_rejected() -> None:
    for prefix in ("observed:", "live:", "predicted:", "actual:"):
        with pytest.raises(DatasetError):
            assert_no_service_derived_labels(
                {"samples": [{"label_source": f"{prefix}anything"}]}
            )


def test_spec_labels_are_accepted() -> None:
    assert_no_service_derived_labels(
        {"samples": [{"label_source": "spec:conflict-matrix#coexist"}]}
    )


def test_load_dataset_verifies_hash_and_provenance() -> None:
    dataset, provenance = load_dataset(
        Path("evaluation/datasets/memoryhub_knowledge_retrieval_v1_dev.json")
    )
    assert provenance["hash_verified"] is True
    assert provenance["dataset_drift"] is False
    assert provenance["counts"]["memories"] == len(dataset["memories"])


def test_load_dataset_detects_tampered_hash(tmp_path: Path) -> None:
    target = tmp_path / "memoryhub_knowledge_retrieval_v1_dev.json"
    target.write_text(json.dumps({"metadata": {}, "memories": [], "queries": []}))
    with pytest.raises(DatasetError, match="哈希不符"):
        load_dataset(target)


def test_hash_verification_reports_actual_and_expected() -> None:
    ok, actual, expected = verify_dataset_hash(
        Path("evaluation/datasets/memoryhub_golden_retrieval_v1.json")
    )
    assert ok
    assert actual == expected
