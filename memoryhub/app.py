"""
FastAPI 应用入口

组装所有模块，启动本地 Memory Service。
"""

import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from memoryhub.adapter import schemas as adapter_schemas
from memoryhub.adapter.api import router as memory_router
from memoryhub.adapter.schemas import KnowledgeMemory, PreferenceMemory, SearchResult
from memoryhub.config import AppConfig, load_config


def _memory_text(memory: PreferenceMemory | KnowledgeMemory) -> str:
    """用于建索引的记忆文本：知识记忆拼上名称，偏好记忆用正文"""
    if memory.memory_type == "knowledge":
        return f"{memory.name} {memory.content}".strip()
    return memory.content


def _memory_metadata(memory: PreferenceMemory | KnowledgeMemory) -> dict:
    """检索结果随行的元数据（融合过滤依赖 memory_type/confidence/scope）"""
    return {
        "memory_type": memory.memory_type,
        "content": _memory_text(memory),
        "confidence": memory.confidence,
        "scope": memory.scope.model_dump(),
    }


class _VectorStoreSearchAdapter:
    """把 storage 层 VectorStore 适配成检索层的向量检索接口。

    VectorStore 是向量索引的事实来源；memory_type/scope 等元数据以
    SQLite（memory_lookup）为准，检索时现场补齐。
    """

    def __init__(self, store, memory_lookup: dict):
        self._store = store
        self._lookup = memory_lookup

    def search(self, query_vector: list[float], top_k: int = 5) -> list[SearchResult]:
        hits = self._store.search(query_vector, top_k)
        results: list[SearchResult] = []
        for memory_id, score in hits:
            memory = self._lookup.get(memory_id)
            metadata = _memory_metadata(memory) if memory is not None else {}
            results.append(
                SearchResult(
                    memory_id=memory_id,
                    memory_type=metadata.get("memory_type", ""),
                    content=metadata.get("content", ""),
                    score=float(score),
                    source="vector",
                    metadata=metadata,
                )
            )
        return results


_SAFE_ERROR_TYPE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SAFE_LOCATION_SEGMENTS = frozenset(
    {"body", "query", "path", "header", "cookie"}
    | {
        field_name
        for candidate in vars(adapter_schemas).values()
        if isinstance(candidate, type) and issubclass(candidate, BaseModel)
        for field_name in candidate.model_fields
    }
)


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    """只投影由服务端 schema 控制的错误类型和位置。"""
    projected: list[dict[str, object]] = []
    for error in exc.errors():
        error_type = error.get("type")
        if (
            not isinstance(error_type, str)
            or _SAFE_ERROR_TYPE.fullmatch(error_type) is None
        ):
            error_type = "validation_error"

        location: list[str | int] = []
        for segment in error.get("loc", ()):
            if type(segment) is int and segment >= 0:
                location.append(segment)
            elif isinstance(segment, str) and segment in _SAFE_LOCATION_SEGMENTS:
                location.append(segment)
            else:
                location.append("<field>")
        projected.append({"type": error_type, "loc": location})
    return projected


def create_app(config: AppConfig | None = None) -> FastAPI:
    """
    创建 FastAPI 应用

    参数:
        config: 应用配置，为 None 时使用默认配置

    返回:
        FastAPI 实例

    初始化流程:
        1. 加载配置
        2. 初始化存储层（SQLite + FAISS）
        3. 初始化 LLM / Embedding 客户端
        4. 注册路由
        5. 注册生命周期钩子
    """
    if config is None:
        config = load_config()

    app = FastAPI(
        title="Kylin-MemoryHub",
        description="面向麒麟 OS Agent 的可插拔本地记忆中枢",
        version="0.1.0",
    )

    @app.exception_handler(RequestValidationError)
    async def safe_request_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """避免 FastAPI 的默认 422 响应回显待检测输入和验证上下文。"""
        return JSONResponse(
            status_code=422,
            content={"detail": _safe_validation_errors(exc)},
        )

    # CORS（开发时允许前端跨域）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(memory_router)

    # 注册生命周期
    @app.on_event("startup")
    async def startup():
        """应用启动时初始化各组件"""
        import json

        from memoryhub.embedding import create_embedding_client
        from memoryhub.retrieval.cache import SearchCache
        from memoryhub.retrieval.hybrid import HybridRetriever
        from memoryhub.retrieval.keyword_search import KeywordSearcher
        from memoryhub.retrieval.reranker import Reranker
        from memoryhub.storage.database import (
            Database,
            KnowledgeRepository,
            PreferenceRepository,
        )
        from memoryhub.storage.vector_store import VectorStore

        # 存储层：SQLite 是记忆记录的事实来源，VectorStore 是向量索引的事实来源
        db = Database(db_path=config.storage.db_path)
        db.init_schema()
        pref_repo = PreferenceRepository(db)
        know_repo = KnowledgeRepository(db)

        # 全量加载活跃记忆，构建 memory_id → 记忆对象 的映射
        memories = [*pref_repo.list_all(), *know_repo.list_all()]
        memory_lookup = {m.memory_id: m for m in memories}

        embedding_client = create_embedding_client(dim=config.embedding.dimension)

        # 向量索引：优先从磁盘加载；为空时按记忆文本重新 embedding 全量重建
        vector_store = VectorStore(
            index_path=config.storage.vector_index_path,
            dimension=embedding_client.get_dimension(),
        )
        vector_store.init_index()
        if vector_store.index.ntotal == 0 and memories:
            for memory in memories:
                vector_store.add(
                    memory.memory_id, embedding_client.embed(_memory_text(memory))
                )
            vector_store.save()

        # 关键词索引：BM25 索引可重建，启动时从 SQLite 全量构建
        keyword_search = KeywordSearcher()
        if memories:
            keyword_search.build_index(
                [
                    (
                        m.memory_id,
                        _memory_text(m),
                        json.dumps(_memory_metadata(m), ensure_ascii=False),
                    )
                    for m in memories
                ]
            )

        cache = SearchCache(
            max_size=config.storage.cache_max_size,
            ttl_seconds=config.retrieval.cache_ttl_seconds,
        )

        app.state.db = db
        app.state.vector_store = vector_store
        app.state.retriever = HybridRetriever(
            vector_search=_VectorStoreSearchAdapter(vector_store, memory_lookup),
            keyword_search=keyword_search,
            reranker=Reranker(),
            cache=cache,
            config=config.retrieval,
            embedding_fn=embedding_client.embed,
            memory_lookup=memory_lookup,
        )

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时保存向量索引并释放数据库连接"""
        vector_store = getattr(app.state, "vector_store", None)
        if vector_store is not None:
            vector_store.save()
        db = getattr(app.state, "db", None)
        if db is not None:
            db.close()

    return app


# 用于直接运行: uvicorn memoryhub.app:app --reload
app = create_app()
