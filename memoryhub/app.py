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
from memoryhub.config import AppConfig, load_config


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
        import os

        from memoryhub.embedding import create_embedding_client
        from memoryhub.retrieval.cache import SearchCache
        from memoryhub.retrieval.hybrid import HybridRetriever
        from memoryhub.retrieval.keyword_search import KeywordSearcher
        from memoryhub.retrieval.reranker import Reranker
        from memoryhub.retrieval.vector_search import VectorSearcher

        # TODO: 初始化数据库（storage 层实现后接入 Repository 与 memory_lookup）

        embedding_client = create_embedding_client(dim=config.embedding.dimension)

        vector_search = VectorSearcher(
            index_path=config.storage.vector_index_path,
            dimension=embedding_client.get_dimension(),
        )
        if os.path.exists(config.storage.vector_index_path):
            vector_search.load_index()

        keyword_search = KeywordSearcher()

        cache = SearchCache(
            max_size=config.storage.cache_max_size,
            ttl_seconds=config.retrieval.cache_ttl_seconds,
        )

        app.state.retriever = HybridRetriever(
            vector_search=vector_search,
            keyword_search=keyword_search,
            reranker=Reranker(),
            cache=cache,
            config=config.retrieval,
            embedding_fn=embedding_client.embed,
        )

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时释放资源"""
        # TODO: 关闭数据库连接、保存向量索引等
        pass

    return app


# 用于直接运行: uvicorn memoryhub.app:app --reload
app = create_app()
