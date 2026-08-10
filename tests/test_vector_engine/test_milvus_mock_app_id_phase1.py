"""阶段一：mock 集成链路使用与真实 SDK 相同的 app_id 参数契约。"""

from memoryhub.storage.vector_engine import create_vector_engine


def test_milvus_mock_connect_requires_explicit_app_id() -> None:
    engine = create_vector_engine(
        provider="milvus_mock",
        app_id="test-app-id",
        collection="phase1_contract",
        dimension=768,
    )
    engine.close()
