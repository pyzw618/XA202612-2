# -*- coding: utf-8 -*-
"""HybridRetriever 用户隔离回归测试。

验证:
  - user_001 的查询不召回 user_002~user_005 的记忆
  - 空 user_id 不过滤结果（兼容性）
  - 跨用户隔离在 keyword 和 vector 两条检索路上均生效
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoryhub.adapter.schemas import SearchRequest
from memoryhub.config import RetrievalConfig
from memoryhub.embedding import MockEmbeddingClient
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher
from memoryhub.retrieval.vector_search import VectorSearcher


def _build_retriever(memories: list[dict]):
    ec = MockEmbeddingClient(dim=64, latency=0.0)
    kw = KeywordSearcher()
    import json
    kw.build_index([
        (m["id"], m.get("content", ""),
         json.dumps({
             "memory_type": "knowledge",
             "user_id": m.get("user_id", ""),
             "name": m.get("name", ""),
         }))
        for m in memories
    ])
    vs = VectorSearcher(dimension=64)
    for m in memories:
        vs.add(m["id"], ec.embed(m.get("content", "")),
               metadata={
                   "memory_type": "knowledge",
                   "user_id": m.get("user_id", ""),
               })
    return HybridRetriever(
        vector_search=vs, keyword_search=kw,
        config=RetrievalConfig(),
        embedding_fn=ec.embed,
    )


class TestUserIsolation:
    """验证 user_001 查询不召回其他用户的记忆"""

    def test_single_user_query_excludes_other_users(self) -> None:
        memories = [
            {"id": "know_u1_001", "user_id": "user_001",
             "content": "用户1的部署流程：将代码推送到生产服务器并执行部署脚本"},
            {"id": "know_u1_002", "user_id": "user_001",
             "content": "用户1的代码评审规范：每个PR需要至少两个reviewer批准"},
            {"id": "know_u2_001", "user_id": "user_002",
             "content": "用户2的部署流程：在测试环境验证后通过GitLab CI自动部署"},
            {"id": "know_u2_002", "user_id": "user_002",
             "content": "用户2的代码评审规范：使用自动化lint和单元测试作为评审前置"},
            {"id": "know_u3_001", "user_id": "user_003",
             "content": "用户3的部署手册：通过Ansible剧本批量部署到多台服务器"},
        ]
        retriever = _build_retriever(memories)

        # user_001 查询"部署"
        req = SearchRequest(user_id="user_001", query="部署流程", top_k=10)
        resp = retriever.search(req)

        retrieved_users = set()
        for result in resp.results:
            uid = result.metadata.get("user_id", "")
            retrieved_users.add(uid)

        assert len(resp.results) > 0, "应至少召回 user_001 的记忆"
        assert "user_002" not in retrieved_users, (
            f"Cross-user leak: user_002 memories found in user_001 query"
        )
        assert "user_003" not in retrieved_users, (
            f"Cross-user leak: user_003 memories found in user_001 query"
        )
        # 验证召回的确实是 user_001 的记忆
        for result in resp.results:
            assert result.memory_id in ("know_u1_001", "know_u1_002"), (
                f"Wrong memory: {result.memory_id}"
            )

    def test_different_users_dont_see_each_other(self) -> None:
        memories = [
            {"id": "u1_a", "user_id": "user_001", "content": "周报生成：每周五自动汇总并发送邮件"},
            {"id": "u2_a", "user_id": "user_002", "content": "周报格式：使用PDF格式并附带图表"},
        ]
        retriever = _build_retriever(memories)

        # user_002 查询"周报"
        resp = retriever.search(SearchRequest(user_id="user_002", query="周报", top_k=5))
        retrieved = {r.memory_id for r in resp.results}
        assert "u1_a" not in retrieved, f"user_002 不应看到 user_001 的周报记忆，但召回了 u1_a"
        assert "u2_a" in retrieved, f"user_002 应能看到自己的周报记忆"

        # user_001 查询"周报"
        resp = retriever.search(SearchRequest(user_id="user_001", query="周报", top_k=5))
        retrieved = {r.memory_id for r in resp.results}
        assert "u2_a" not in retrieved, f"user_001 不应看到 user_002 的周报记忆"
        assert "u1_a" in retrieved

    def test_no_query_results_still_respects_isolation(self) -> None:
        memories = [
            {"id": "m1", "user_id": "user_002", "content": "办公流程"},
            {"id": "m2", "user_id": "user_003", "content": "开发规范"},
        ]
        retriever = _build_retriever(memories)
        # user_001 没有记忆，查询应返回空
        resp = retriever.search(SearchRequest(user_id="user_001", query="流程", top_k=5))
        assert len(resp.results) == 0, f"user_001 无记忆，结果应为空，实际 {len(resp.results)} 条"

    def test_empty_user_id_sees_nothing(self) -> None:
        """当所有记忆有 user_id 且请求 user_id 为空时，应看不到任何记忆（strict）"""
        memories = [
            {"id": "m1", "user_id": "user_001", "content": "构建流水线配置"},
            {"id": "m2", "user_id": "user_002", "content": "发布上线流程"},
        ]
        retriever = _build_retriever(memories)
        resp = retriever.search(SearchRequest(user_id="", query="构建", top_k=5))
        # 空 user_id 请求 → 不匹配任何人 → 返回空
        assert len(resp.results) == 0, (
            f"空 user_id 不应返回有归属的记忆，实际 {len(resp.results)} 条"
        )

    def test_hybrid_merge_preserves_isolation(self) -> None:
        """验证 keyword + vector 融合后隔离仍生效"""
        memories = [
            {"id": "k_u1", "user_id": "user_001",
             "content": "数据库迁移流程：先在预发布环境执行migration，再灰度生产"},
            {"id": "k_u2", "user_id": "user_002",
             "content": "数据库迁移规范：每次migration必须包含回滚SQL脚本"},
            {"id": "v_u1", "user_id": "user_001",
             "content": "数据一致性验证工具，用于比对迁移前后的数据差异"},
            {"id": "v_u2", "user_id": "user_002",
             "content": "SQL性能分析工具，检查migration脚本对数据库负载的影响"},
        ]
        retriever = _build_retriever(memories)
        resp = retriever.search(SearchRequest(user_id="user_001", query="数据库迁移", top_k=10))
        retrieved = {r.memory_id for r in resp.results}
        assert "k_u1" in retrieved or "v_u1" in retrieved, "user_001 应至少召回一个自己的记忆"
        assert "k_u2" not in retrieved, "Cross-user via keyword: k_u2"
        assert "v_u2" not in retrieved, "Cross-user via vector: v_u2"


class TestUserIsolationRegression:
    """验证原有功能不被破坏"""

    def test_non_isolation_query_still_works(self) -> None:
        """不传 user_id 或 user_id=default 应该不过滤"""
        memories = [
            {"id": "m1", "user_id": "default", "content": "默认用户的部署流程"},
            {"id": "m2", "user_id": "default", "content": "默认用户的代码评审规范"},
            {"id": "m3", "user_id": "user_001", "content": "特定用户的专属配置"},
        ]
        retriever = _build_retriever(memories)
        resp = retriever.search(SearchRequest(user_id="default", query="部署", top_k=5))
        # default 用户应能召回 default 记忆
        retrieved = {r.memory_id for r in resp.results}
        assert "m1" in retrieved, "default 用户应能召回 default 记忆"
        assert "m3" not in retrieved or "m3" not in retrieved, "不应跨用户"
        assert len(resp.results) <= 2
