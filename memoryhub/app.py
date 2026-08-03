"""
FastAPI 应用入口

组装所有模块，启动本地 Memory Service。
"""

import base64
import binascii
import os
import re
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from memoryhub.adapter import schemas as adapter_schemas
from memoryhub.adapter import user_rule_schemas
from memoryhub.adapter.api import router as memory_router
from memoryhub.adapter.schemas import KnowledgeMemory, PreferenceMemory, SearchResult
from memoryhub.config import AppConfig, load_config
from memoryhub.core.safety.user_rules import (
    UserRuleError,
    build_user_rule_service,
)

def _memory_text(memory) -> str:
    """Build shared index text for preference, knowledge, and fact memories."""
    if memory.memory_type == "knowledge":
        from memoryhub.core.memory_write import MemoryWriteService

        return MemoryWriteService.index_text(memory)
    if memory.memory_type == "fact":
        return memory.content
    return memory.text


def _memory_metadata(memory) -> dict:
    """Metadata used by owner, type, confidence, and scope filters."""
    if memory.memory_type == "fact":
        scope = {"scope": memory.scope, "project_id": memory.project_id or ""}
        fact_fields = {
            "subject_id": memory.subject_id,
            "predicate_id": memory.predicate_id,
            "object_id": memory.object_id,
        }
    else:
        scope = memory.scope.model_dump()
        fact_fields = {}
    return {
        "memory_type": memory.memory_type,
        "user_id": memory.user_id,
        "content": _memory_text(memory),
        "confidence": memory.confidence,
        "scope": scope,
        **fact_fields,
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
        for schema_module in (adapter_schemas, user_rule_schemas)
        for candidate in vars(schema_module).values()
        if isinstance(candidate, type) and issubclass(candidate, BaseModel)
        for field_name in candidate.model_fields
    }
)


def _user_rule_master_key_from_env(env_name: str) -> bytes | None:
    """Decode one 32-byte Base64 key without exposing its value in errors."""
    encoded = os.environ.get(env_name, "").strip()
    if not encoded:
        return None
    try:
        key = base64.b64decode(
            encoded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeError, ValueError, binascii.Error):
        return None
    return key if len(key) == 32 else None


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


def create_app(
    config: AppConfig | None = None,
    user_rule_service: object | None = None,
    user_rule_identity_resolver: Callable[[Request], str] | None = None,
    safety_gate: object | None = None,
    event_ingestion_service: object | None = None,
    fact_pipeline: object | None = None,
) -> FastAPI:
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
    if user_rule_identity_resolver is not None and not callable(
        user_rule_identity_resolver
    ):
        raise ValueError("user_rule_identity_resolver must be callable")

    app = FastAPI(
        title="Kylin-MemoryHub",
        description="面向麒麟 OS Agent 的可插拔本地记忆中枢",
        version="0.1.0",
    )
    # Runtime services are application-scoped; tests and embedding applications can
    # inject one explicitly, while the normal server path constructs it at startup.
    app.state.config = config
    app.state.user_rule_service = user_rule_service
    app.state.user_rule_identity_resolver = user_rule_identity_resolver
    app.state.user_rule_service_error = ""
    app.state.owns_user_rule_service = False
    app.state.safety_gate = safety_gate
    app.state.safety_gate_error = ""
    app.state.event_ingestion_service = event_ingestion_service
    app.state.extraction_task_repo = None
    app.state.extraction_retry_service = None
    app.state.memory_write_service = None
    app.state.fact_pipeline = fact_pipeline
    app.state.fact_store = getattr(fact_pipeline, "store", None)
    app.state.fact_index_service = None
    app.state.owns_fact_pipeline = False

    @app.exception_handler(RequestValidationError)
    async def safe_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """避免 FastAPI 的默认 422 响应回显待检测输入和验证上下文。"""
        if request.url.path.startswith("/api/memory/safety/user-rules"):
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "user_rule.invalid_request"}},
            )
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
        # ---- 安全模块：用户自定义规则服务 ----
        if app.state.user_rule_service is None and config.safety.user_rules.enabled:
            app.state.user_rule_service_error = ""
            if app.state.user_rule_identity_resolver is None:
                app.state.user_rule_service_error = "user_rule.identity_unavailable"
            else:
                key = _user_rule_master_key_from_env(
                    config.safety.user_rules.encryption_key_env
                )
                if key is None:
                    app.state.user_rule_service_error = "user_rule.key_unavailable"
                else:
                    try:
                        app.state.user_rule_service = build_user_rule_service(
                            config.storage.db_path,
                            key,
                            key_id=config.safety.user_rules.key_id,
                            max_rules_per_user=(
                                config.safety.user_rules.max_rules_per_user
                            ),
                            max_matcher_chars=(
                                config.safety.user_rules.max_matcher_chars
                            ),
                            allow_advanced_regex=(
                                config.safety.user_rules.allow_advanced_regex
                            ),
                            detector_cache_size=(
                                config.safety.user_rules.detector_cache_size
                            ),
                        )
                    except UserRuleError as exc:
                        app.state.user_rule_service_error = exc.code
                    except Exception:
                        app.state.user_rule_service_error = (
                            "user_rule.service_unavailable"
                        )
                    else:
                        app.state.owns_user_rule_service = True

        # ---- 存储层与检索引擎 ----
        if app.state.user_rule_service_error == "user_rule.key_unavailable":
            return

        import json

        from memoryhub.core.fact import (
            FactIngestionAdapter, FactIndexService, FactMemoryPipeline,
        )
        from memoryhub.core.ingestion.extraction import ExtractionExecutor
        from memoryhub.core.ingestion.quality import QualityScorer
        from memoryhub.core.ingestion.retry import ExtractionRetryService
        from memoryhub.core.ingestion.service import EventIngestionService
        from memoryhub.core.knowledge.extractor import KnowledgeExtractor
        from memoryhub.core.memory_write import MemoryWriteService
        from memoryhub.core.preference.extractor import PreferenceExtractor
        from memoryhub.core.preference.updater import PreferenceUpdater
        from memoryhub.core.safety.detector import SensitiveDetector
        from memoryhub.core.safety.gate import SafetyGateError, SafetyWriteGate
        from memoryhub.embedding import create_embedding_client
        from memoryhub.llm.ollama_client import OllamaClient
        from memoryhub.llm.openai_client import OpenAIClient
        from memoryhub.retrieval.cache import SearchCache
        from memoryhub.retrieval.hybrid import HybridRetriever
        from memoryhub.retrieval.keyword_search import KeywordSearcher
        from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
        from memoryhub.retrieval.reranker import Reranker
        from memoryhub.storage.database import (
            Database,
            EventRepository,
            ExtractionTaskRepository,
            ConflictRepository,
            ForgetRepository,
            KnowledgeRepository,
            PreferenceRepository,
        )
        from memoryhub.storage.vector_engine import create_vector_engine
        from memoryhub.storage.vector_store import VectorStore
        from memoryhub.storage.evidence_store import EvidenceStore

        if app.state.safety_gate is None:
            audit_key = _user_rule_master_key_from_env(config.safety.audit.hmac_key_env)
            quarantine_key = _user_rule_master_key_from_env(
                config.safety.quarantine.encryption_key_env
            )
            if audit_key is None or quarantine_key is None:
                app.state.safety_gate_error = "gate.key_unavailable"
            else:
                try:
                    if app.state.user_rule_service is not None:
                        app.state.safety_gate = SafetyWriteGate.from_user_rule_config(
                            app.state.user_rule_service,
                            config.safety,
                            audit_hmac_key=audit_key,
                            quarantine_key=quarantine_key,
                        )
                    elif config.safety.user_rules.enabled:
                        app.state.safety_gate_error = (
                            app.state.user_rule_service_error
                            or "gate.detector_unavailable"
                        )
                    else:
                        app.state.safety_gate = SafetyWriteGate.from_config(
                            SensitiveDetector.from_config(config.safety),
                            config.safety,
                            audit_hmac_key=audit_key,
                            quarantine_key=quarantine_key,
                        )
                except SafetyGateError as exc:
                    app.state.safety_gate_error = exc.code
                except Exception:
                    app.state.safety_gate_error = "gate.service_unavailable"

        llm_kwargs = {
            "api_base": config.llm.api_base,
            "model": config.llm.model,
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
        }
        llm_provider = config.llm.provider.lower()
        if llm_provider == "openai":
            llm_client = OpenAIClient(api_key=config.llm.api_key, **llm_kwargs)
        elif llm_provider == "ollama":
            llm_client = OllamaClient(**llm_kwargs)
        else:
            raise ValueError(f"unknown llm provider: {config.llm.provider}")

        # 存储层：SQLite 是记忆记录的事实来源，VectorStore 是向量索引的事实来源
        db = Database(db_path=config.storage.db_path)
        db.init_schema()
        pref_repo = PreferenceRepository(db)
        know_repo = KnowledgeRepository(db)
        event_repo = EventRepository(db)
        extraction_task_repo = ExtractionTaskRepository(db)
        conflict_repo = ConflictRepository(db)
        forget_repo = ForgetRepository(db)

        if app.state.fact_pipeline is None:
            app.state.fact_pipeline = FactMemoryPipeline(
                db_path=config.storage.db_path, llm_client=llm_client,
            )
            app.state.owns_fact_pipeline = True
        fact_store = app.state.fact_pipeline.store
        facts = fact_store.list_facts(status="active", limit=100000)

        memories = [*pref_repo.list_all(), *know_repo.list_all(), *facts]
        memory_lookup = {m.memory_id: m for m in memories}

        embedding_kwargs = {"dim": config.embedding.dimension}
        if config.embedding.model_name:
            embedding_kwargs["model_name"] = config.embedding.model_name
        if config.embedding.so_path:
            embedding_kwargs["so_path"] = config.embedding.so_path
        embedding_provider = config.embedding.provider
        embedding_client = create_embedding_client(
            provider=embedding_provider if embedding_provider != "auto" else None,
            **embedding_kwargs,
        )

        # 向量引擎分支：faiss 走本地 VectorStore；milvus/milvus_mock 走麒麟向量引擎
        engine_provider = config.vector_engine.provider
        vector_store = None
        vector_engine = None
        vector_search_adapter = None

        if engine_provider == "faiss":
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
            vector_search_adapter = _VectorStoreSearchAdapter(vector_store, memory_lookup)
        elif engine_provider in ("milvus", "milvus_mock"):
            engine_kwargs = {
                "host": config.vector_engine.host,
                "port": config.vector_engine.port,
                "collection": config.vector_engine.collection,
                "dimension": embedding_client.get_dimension(),
            }
            if config.vector_engine.so_path:
                engine_kwargs["so_path"] = config.vector_engine.so_path
            vector_engine = create_vector_engine(engine_provider, **engine_kwargs)
            # 启动时对存量记忆全量 insert（重复插入视为更新）
            for memory in memories:
                text = _memory_text(memory)
                vector_engine.insert(
                    memory.memory_id,
                    text,
                    embedding_client.embed(text),
                    metadata=_memory_metadata(memory),
                )
        else:
            raise ValueError(f"unknown vector_engine provider: {engine_provider}")

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
        app.state.pref_repo = pref_repo
        app.state.know_repo = know_repo
        app.state.event_repo = event_repo
        app.state.extraction_task_repo = extraction_task_repo
        app.state.conflict_repo = conflict_repo
        app.state.forget_repo = forget_repo
        app.state.search_cache = cache
        app.state.keyword_search = keyword_search
        app.state.memory_lookup = memory_lookup
        app.state.embedding_client = embedding_client
        app.state.llm_client = llm_client
        app.state.vector_store = vector_store
        app.state.vector_engine = vector_engine
        app.state.evidence_store = EvidenceStore(config.storage.evidence_path)
        app.state.fact_store = fact_store
        app.state.fact_index_service = FactIndexService(
            fact_store=fact_store,
            vector_store=vector_store,
            vector_engine=vector_engine,
            keyword_search=keyword_search,
            memory_lookup=memory_lookup,
            search_cache=cache,
            embedding_client=embedding_client,
        )
        app.state.fact_pipeline.index_service = app.state.fact_index_service
        for fact in facts:
            app.state.fact_index_service.sync_fact(fact)

        app.state.memory_write_service = MemoryWriteService(
            pref_repo=pref_repo,
            know_repo=know_repo,
            vector_store=vector_store,
            vector_engine=vector_engine,
            keyword_search=keyword_search,
            memory_lookup=memory_lookup,
            search_cache=cache,
            embedding_client=embedding_client,
            evidence_store=app.state.evidence_store,
        )
        pref_repo.write_service = app.state.memory_write_service
        know_repo.write_service = app.state.memory_write_service
        preference_extractor = PreferenceExtractor(llm_client=llm_client)
        preference_updater = PreferenceUpdater(
            llm_client=llm_client,
            pref_repo=pref_repo,
            conflict_repo=conflict_repo,
            write_service=app.state.memory_write_service,
        )
        knowledge_extractor = KnowledgeExtractor(llm_client=llm_client)
        fact_ingestion_adapter = FactIngestionAdapter(app.state.fact_pipeline)
        extraction_executor = ExtractionExecutor(
            memory_write_service=app.state.memory_write_service,
            preference_extractor=preference_extractor,
            preference_updater=preference_updater,
            knowledge_extractor=knowledge_extractor,
            fact_ingestion_adapter=fact_ingestion_adapter,
        )
        if (
            app.state.event_ingestion_service is None
            and app.state.safety_gate is not None
        ):
            app.state.event_ingestion_service = EventIngestionService(
                event_repo=event_repo,
                safety_gate=app.state.safety_gate,
                quality_scorer=QualityScorer(),
                memory_write_service=app.state.memory_write_service,
                preference_extractor=preference_extractor,
                preference_updater=preference_updater,
                knowledge_extractor=knowledge_extractor,
                fact_ingestion_adapter=fact_ingestion_adapter,
                extraction_task_repo=extraction_task_repo,
                extraction_executor=extraction_executor,
            )
        retry_executor = getattr(
            app.state.event_ingestion_service,
            "extraction_executor",
            extraction_executor,
        )
        app.state.extraction_retry_service = ExtractionRetryService(
            task_repo=extraction_task_repo,
            event_repo=event_repo,
            executor=retry_executor,
        )
        if vector_engine is not None:
            app.state.retriever = MilvusHybridRetriever(
                engine=vector_engine,
                embedding_fn=embedding_client.embed,
                config=config.retrieval,
                memory_lookup=memory_lookup,
                fact_store=fact_store,
            )
        else:
            app.state.retriever = HybridRetriever(
                vector_search=vector_search_adapter,
                keyword_search=keyword_search,
                reranker=Reranker(),
                cache=cache,
                config=config.retrieval,
                embedding_fn=embedding_client.embed,
                memory_lookup=memory_lookup,
                fact_store=fact_store,
            )

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时释放资源"""
        # 关闭安全模块
        if app.state.owns_user_rule_service:
            close = getattr(app.state.user_rule_service, "close", None)
            try:
                if callable(close):
                    close()
            except Exception:
                pass
            finally:
                app.state.user_rule_service = None
                app.state.owns_user_rule_service = False
        # 保存向量索引并关闭数据库
        if app.state.owns_fact_pipeline:
            owned_fact_pipeline = getattr(app.state, "fact_pipeline", None)
            if owned_fact_pipeline is not None:
                try:
                    owned_fact_pipeline.close()
                finally:
                    app.state.fact_pipeline = None
                    app.state.fact_store = None
                    app.state.owns_fact_pipeline = False
        vector_store = getattr(app.state, "vector_store", None)
        if vector_store is not None:
            vector_store.save()
        vector_engine = getattr(app.state, "vector_engine", None)
        if vector_engine is not None:
            try:
                vector_engine.persist()
            finally:
                vector_engine.close()
            app.state.vector_engine = None
        db = getattr(app.state, "db", None)
        if db is not None:
            db.close()

    return app


# 用于直接运行: uvicorn memoryhub.app:app --reload
app = create_app()
