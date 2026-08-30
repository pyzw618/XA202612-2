"""
FastAPI 应用入口

组装所有模块，启动本地 Memory Service。
"""

import base64
import binascii
import logging
import os
import re
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from memoryhub.adapter import schemas as adapter_schemas
from memoryhub.adapter import user_rule_schemas
from memoryhub.adapter.agent_api import root_router as agent_root_router
from memoryhub.adapter.agent_api import router as agent_router
from memoryhub.adapter.api import router as memory_router
from memoryhub.adapter.management_api import router as management_router
from memoryhub.adapter.memory_v2_api import router as memory_v2_router
from memoryhub.adapter.schemas import SearchResult
from memoryhub.adapter.service import MemoryService
from memoryhub.adapter.vnext_api import router as memory_vnext_router
from memoryhub.config import AppConfig, load_config, validate_production_runtime
from memoryhub.core.safety.user_rules import (
    UserRuleError,
    build_user_rule_service,
)

logger = logging.getLogger(__name__)


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
        "status": (
            memory.status.value
            if hasattr(memory.status, "value")
            else str(memory.status)
        ),
        "scope": scope,
        **fact_fields,
    }


def _max_index_version(db) -> int:
    """获取 SQLite 中已同步记忆的当前最大 index_version（不存在时返回 1）。"""
    from sqlalchemy import func

    from memoryhub.storage.models import KnowledgeRow, PreferenceRow

    with db.session() as s:
        pref_max = s.query(func.max(PreferenceRow.index_version)).scalar() or 0
        know_max = s.query(func.max(KnowledgeRow.index_version)).scalar() or 0
    return max(int(pref_max), int(know_max), 1)


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
    memory_service: object | None = None,
) -> FastAPI:
    """
    创建 FastAPI 应用

    参数:
        config: 应用配置，为 None 时使用默认配置

    返回:
        FastAPI 实例

    初始化流程:
        1. 加载配置
        2. 初始化存储层（SQLite + 向量引擎）
        3. 初始化 LLM / Embedding 客户端
        4. 注册路由
        5. 注册生命周期钩子

    注意:
        生产模式（runtime.mode=production）下仅允许装配 MilvusHybridRetriever；
        FAISS / HybridRetriever / KeywordSearcher 仅在 development/test 或显式
        故障诊断场景下作为降级路径保留。
    """
    if config is None:
        config = load_config()
    if user_rule_identity_resolver is not None and not callable(
        user_rule_identity_resolver
    ):
        raise ValueError("user_rule_identity_resolver must be callable")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await startup()
        try:
            yield
        finally:
            await shutdown()

    app = FastAPI(
        title="Kylin-MemoryHub",
        description="面向麒麟 OS Agent 的可插拔本地记忆中枢",
        version="0.1.0",
        lifespan=lifespan,
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
    app.state.safety_key_store_path = ""
    app.state.safety_key_sources = ()
    app.state.event_ingestion_service = event_ingestion_service
    app.state.extraction_task_repo = None
    app.state.extraction_retry_service = None
    app.state.extraction_retry_task = None
    app.state.formation_worker = None
    app.state.memory_write_service = None
    app.state.memory_service = memory_service
    app.state.owns_memory_service = False
    app.state.rollout_controller = None
    app.state.shadow_read_service = None
    app.state.rollout_read_service = None

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
    app.include_router(agent_router)
    app.include_router(agent_root_router)
    app.include_router(management_router)
    app.include_router(memory_v2_router)
    app.include_router(memory_vnext_router)

    # 注册生命周期
    async def startup():
        """应用启动时初始化各组件"""
        # ---- 安全模块：端侧持久密钥 ----
        # 测试/嵌入方显式注入完整 gate 时不触碰主机密钥存储；正常 REST
        # 启动路径统一在这里完成首次生成、外部密钥导入和重启复用。
        key_resolution = None
        needs_managed_keys = app.state.safety_gate is None or (
            app.state.user_rule_service is None
            and config.safety.user_rules.enabled
            and app.state.user_rule_identity_resolver is not None
        )
        if needs_managed_keys:
            from memoryhub.core.safety.key_store import (
                SafetyKeyStoreError,
                provision_safety_keys,
            )

            try:
                key_resolution = provision_safety_keys(config)
            except SafetyKeyStoreError as exc:
                app.state.safety_gate_error = exc.code
                logger.error("memoryhub_safety_key_store_unavailable code=%s", exc.code)
                raise RuntimeError(exc.code) from None
            app.state.safety_key_store_path = str(key_resolution.key_file)
            app.state.safety_key_sources = key_resolution.sources

        # ---- 安全模块：用户自定义规则服务 ----
        if app.state.user_rule_service is None and config.safety.user_rules.enabled:
            app.state.user_rule_service_error = ""
            if app.state.user_rule_identity_resolver is None:
                app.state.user_rule_service_error = "user_rule.identity_unavailable"
            else:
                key = (
                    key_resolution.key("user_rule")
                    if key_resolution is not None
                    else _user_rule_master_key_from_env(
                        config.safety.user_rules.encryption_key_env
                    )
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

        # ---- 最小 Memory Service（REST adapter 的垂直切片） ----
        if app.state.memory_service is None:
            app.state.memory_service = MemoryService(config.storage.db_path)
            app.state.memory_service.start()
            app.state.owns_memory_service = True

        import json

        from memoryhub.core.ingestion.extraction import ExtractionExecutor
        from memoryhub.core.ingestion.quality import QualityScorer
        from memoryhub.core.ingestion.retry import ExtractionRetryService
        from memoryhub.core.ingestion.service import EventIngestionService
        from memoryhub.core.knowledge.extractor import KnowledgeExtractor
        from memoryhub.core.knowledge.handler import KnowledgeMemoryHandler
        from memoryhub.core.knowledge.updater import KnowledgeUpdater
        from memoryhub.core.memory_write import MemoryWriteService
        from memoryhub.core.preference.extractor import PreferenceExtractor
        from memoryhub.core.preference.handler import PreferenceMemoryHandler
        from memoryhub.core.preference.updater import PreferenceUpdater
        from memoryhub.core.safety.detector import SensitiveDetector
        from memoryhub.core.safety.gate import SafetyGateError, SafetyWriteGate
        from memoryhub.embedding import create_embedding_client
        from memoryhub.llm.openai_client import OpenAIClient
        from memoryhub.retrieval.cache import SearchCache
        from memoryhub.retrieval.hybrid import HybridRetriever
        from memoryhub.retrieval.keyword_search import KeywordSearcher
        from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
        from memoryhub.retrieval.reranker import Reranker
        from memoryhub.storage.compensation_task import (
            PendingIndexCompensationTask,
        )
        from memoryhub.storage.database import (
            ConflictRepository,
            Database,
            EventRepository,
            ExtractionTaskRepository,
            ForgetRepository,
            KnowledgeRepository,
            MidTermMemoryRepository,
            PreferenceRepository,
            ShortTermMemoryRepository,
        )
        from memoryhub.storage.evidence_store import EvidenceStore
        from memoryhub.storage.sync_service import MemorySyncService
        from memoryhub.storage.vector_engine import create_vector_engine
        from memoryhub.storage.vector_store import VectorStore

        if app.state.safety_gate is None:
            audit_key = (
                key_resolution.key("audit_hmac")
                if key_resolution is not None
                else _user_rule_master_key_from_env(config.safety.audit.hmac_key_env)
            )
            quarantine_key = (
                key_resolution.key("quarantine")
                if key_resolution is not None
                else _user_rule_master_key_from_env(
                    config.safety.quarantine.encryption_key_env
                )
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
        # Memory extraction uses a cloud OpenAI-compatible API exclusively.
        llm_client = OpenAIClient(api_key=config.llm.api_key, **llm_kwargs)

        # 存储层：SQLite 是记忆记录的事实来源，VectorStore 是向量索引的事实来源
        db = Database(db_path=config.storage.db_path)
        db.init_schema()
        pref_repo = PreferenceRepository(db)
        know_repo = KnowledgeRepository(db)
        event_repo = EventRepository(db)
        extraction_task_repo = ExtractionTaskRepository(db)
        conflict_repo = ConflictRepository(db)
        forget_repo = ForgetRepository(db)

        memories = [*pref_repo.list_all(), *know_repo.list_all()]
        memory_lookup = {m.memory_id: m for m in memories}

        embedding_kwargs = {"dim": config.embedding.dimension}
        if config.embedding.model_name:
            embedding_kwargs["model_name"] = config.embedding.model_name
        if config.embedding.so_path:
            embedding_kwargs["so_path"] = config.embedding.so_path
        embedding_kwargs["query_timeout_ms"] = config.embedding.query_timeout_ms
        embedding_provider = config.embedding.provider
        embedding_client = create_embedding_client(
            provider=embedding_provider if embedding_provider != "auto" else None,
            **embedding_kwargs,
        )

        # 向量引擎分支：生产模式仅允许真实 Milvus；development/test 保留 faiss 降级路径
        engine_provider = config.vector_engine.provider
        vector_store = None
        vector_engine = None
        vector_search_adapter = None

        if config.runtime.is_production and engine_provider != "milvus":
            from memoryhub.config import ProductionGateError

            raise ProductionGateError(
                f"production requires vector_engine.provider='milvus', got {engine_provider!r}"
            )

        # 索引版本号：从 SQLite 中已同步记录的最大版本开始；后续写入会递增
        index_version = _max_index_version(db)

        if engine_provider == "faiss":
            logger.warning(
                "app_faiss_fallback_path_selected: "
                "provider=faiss is only allowed in development/test "
                "or explicit diagnostic scenarios"
            )
            # FAISS 索引：优先从磁盘加载；为空时按记忆文本重新 embedding 全量重建
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
            vector_search_adapter = _VectorStoreSearchAdapter(
                vector_store, memory_lookup
            )
        elif engine_provider in ("milvus", "milvus_mock"):
            engine_kwargs = {
                "app_id": config.vector_engine.app_id,
                "host": config.vector_engine.host,
                "port": config.vector_engine.port,
                "collection": config.vector_engine.collection,
                "dimension": embedding_client.get_dimension(),
                "search_timeout_ms": config.vector_engine.search_timeout_ms,
            }
            if config.vector_engine.so_path:
                engine_kwargs["so_path"] = config.vector_engine.so_path
            vector_engine = create_vector_engine(engine_provider, **engine_kwargs)
        else:
            raise ValueError(f"unknown vector_engine provider: {engine_provider}")

        # 生产模式运行时门禁：校验 SDK/引擎可用性与实际维度
        validate_production_runtime(config, embedding_client, vector_engine)

        # 检索缓存（生产与 development/test 共用）
        cache = SearchCache(
            max_size=config.storage.cache_max_size,
            ttl_seconds=config.retrieval.cache_ttl_seconds,
        )

        keyword_search = None
        if not (config.runtime.is_production or vector_engine is not None):
            keyword_search = KeywordSearcher()
            if memories:
                keyword_search.build_index(
                    [
                        (
                            memory.memory_id,
                            _memory_text(memory),
                            json.dumps(_memory_metadata(memory), ensure_ascii=False),
                        )
                        for memory in memories
                    ]
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
        from memoryhub.observability import (
            AuditStore,
            InfrastructureMetrics,
            TraceSamplingPolicy,
            TraceStore,
        )

        # A single redacted trace store associates S5 diagnostics across write,
        # retrieval, Forget and infrastructure paths. It is observability only,
        # never an Authority data store.
        app.state.trace_store = TraceStore(
            db=db, sampling_policy=TraceSamplingPolicy()
        )
        app.state.infrastructure_metrics = InfrastructureMetrics(db=db)
        app.state.audit_store = AuditStore(db)

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
            conflict_repo=conflict_repo,
            safety_gate=app.state.safety_gate,
            require_safety=config.runtime.is_production,
            # Production persistence ends at the durable outbox; the worker owns
            # vector/keyword/cache projection. Development keeps synchronous
            # projection for interactive diagnostics and legacy tests.
            project_immediately=not config.runtime.is_production,
        )
        pref_repo.write_service = app.state.memory_write_service
        know_repo.write_service = app.state.memory_write_service

        # vNext canonical write service: all production write paths must delegate here.
        from memoryhub.application.canonical_write import CanonicalWriteService
        from memoryhub.application.episode_service import EpisodeService
        from memoryhub.application.event_gateway import EventGateway
        from memoryhub.application.safety_policy_adapter import build_safety_policy
        from memoryhub.application.working_service import WorkingService
        from memoryhub.domain.long_term import LongTermAuthorityFacade
        from memoryhub.storage.authority_repository import AuthorityRepository
        from memoryhub.storage.vnext_repositories import (
            EpisodeRepository,
            WorkingStateRepository,
        )

        authority_repository = AuthorityRepository(
            db=db,
            preference_repository=pref_repo,
            knowledge_repository=know_repo,
        )
        authority_facade = LongTermAuthorityFacade(authority_repository)
        event_gateway = EventGateway(
            db=db,
            policy=build_safety_policy(app.state.safety_gate),
        )
        app.state.canonical_write_service = CanonicalWriteService(
            db=db,
            event_gateway=event_gateway,
            working_service=WorkingService(WorkingStateRepository(db)),
            episode_service=EpisodeService(EpisodeRepository(db)),
            extraction_tasks=extraction_task_repo,
            authority_facade=authority_facade,
            memory_write_service=app.state.memory_write_service,
            formation_mode=config.vnext.formation_mode,
        )
        app.state.episode_service = app.state.canonical_write_service.episode_service

        # vNext unified retrieval service: all read entrypoints delegate here.
        from memoryhub.adapter.retrieval_executor import build_channel_executors
        from memoryhub.application.retrieval_service import RetrievalService
        from memoryhub.storage.vnext_repositories import (
            ActivationRepository,
            RetrievalLogRepository,
        )

        app.state.retrieval_service = RetrievalService(
            channel_executors=build_channel_executors(app.state),
            activation_repository=ActivationRepository(db),
            retrieval_log_repository=RetrievalLogRepository(db),
            trace_store=app.state.trace_store,
        )
        # One application-scoped controller and one shadow service own every
        # production read decision.  Their state is rollout-only and durable;
        # Authority records are never changed by rollback.
        from memoryhub.application.rollout_service import RolloutController
        from memoryhub.application.shadow_read_service import (
            RolloutReadService,
            ShadowReadService,
        )

        app.state.rollout_controller = RolloutController(config.vnext, db=db)
        app.state.shadow_read_service = ShadowReadService(
            trace_store=app.state.trace_store
        )
        app.state.rollout_read_service = RolloutReadService(
            controller=app.state.rollout_controller,
            shadow_read=app.state.shadow_read_service,
        )
        from memoryhub.application.dashboard_service import DashboardService
        from memoryhub.application.diagnostic_service import DiagnosticService
        from memoryhub.application.forget_service import ForgetService
        app.state.forget_service = ForgetService(
            db,
            authority_repository,
            trace_store=app.state.trace_store,
            audit_store=app.state.audit_store,
        )
        app.state.diagnostic_service = DiagnosticService(
            db, trace_store=app.state.trace_store, audit_store=app.state.audit_store
        )
        app.state.dashboard_service = DashboardService(
            trace_store=app.state.trace_store,
            metrics=app.state.infrastructure_metrics,
            db=db,
            audit_store=app.state.audit_store,
        )

        # 前端 agent 演示适配层：事件处理协调器（依赖 memory_write_service 同步检索索引）
        from memoryhub.core.processing import EventProcessingCoordinator

        app.state.event_processor = EventProcessingCoordinator(
            pref_repo=pref_repo,
            know_repo=know_repo,
            # Use the configured cloud LLM for assisted preference/knowledge extraction.
            llm_client=llm_client,
            safety_config=config.safety,
            conflict_repo=conflict_repo,
            memory_write_service=app.state.memory_write_service,
        )
        preference_extractor = PreferenceExtractor(llm_client=llm_client)
        preference_updater = PreferenceUpdater(
            llm_client=llm_client,
            pref_repo=pref_repo,
            conflict_repo=conflict_repo,
            write_service=app.state.memory_write_service,
        )
        knowledge_extractor = KnowledgeExtractor(llm_client=llm_client)
        preference_handler = PreferenceMemoryHandler(
            preference_extractor, preference_updater
        )
        knowledge_handler = KnowledgeMemoryHandler(
            knowledge_extractor,
            KnowledgeUpdater(
                write_service=app.state.memory_write_service,
                merge_config=config.knowledge_merge,
                conflict_repo=conflict_repo,
            ),
        )
        extraction_executor = ExtractionExecutor(
            memory_write_service=app.state.memory_write_service,
            preference_extractor=preference_extractor,
            preference_updater=preference_updater,
            knowledge_extractor=knowledge_extractor,
            knowledge_merge_config=config.knowledge_merge,
            conflict_repo=conflict_repo,
            preference_handler=preference_handler,
            knowledge_handler=knowledge_handler,
        )
        from memoryhub.application.formation_worker import FormationWorker
        from memoryhub.application.reflection_service import (
            ReflectionService,
            StructuredReflectionModel,
        )

        app.state.reflection_service = ReflectionService(
            model=StructuredReflectionModel(app.state.llm_client)
        )
        app.state.formation_worker = FormationWorker(
            db,
            task_repository=extraction_task_repo,
            event_repository=event_repo,
            canonical_write_service=app.state.canonical_write_service,
            mode=config.vnext.formation_mode,
            reflection_service=app.state.reflection_service,
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
                extraction_task_repo=extraction_task_repo,
                extraction_executor=extraction_executor,
                short_term_repo=(
                    ShortTermMemoryRepository(db)
                    if config.memory_tier.enabled
                    else None
                ),
                short_ttl_hours=config.memory_tier.short_ttl_hours,
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
            vnext_executor=app.state.formation_worker,
        )
        from memoryhub.core.ingestion.retry_task import ExtractionRetryTask

        app.state.extraction_retry_task = ExtractionRetryTask(
            app.state.extraction_retry_service,
            interval_seconds=config.extraction_retry.interval_seconds,
            batch_size=config.extraction_retry.batch_size,
            enabled=config.extraction_retry.enabled,
        )
        app.state.extraction_retry_task.start()

        # 记忆分层流转调度（REFACTOR_PLAN_V2 §4.4）：session→mid→long + 降级 + 生命周期检查
        if config.memory_tier.enabled:
            from memoryhub.core.knowledge.workflow_miner import WorkflowMiner
            from memoryhub.core.lifecycle.degrader import MemoryDegrader
            from memoryhub.core.lifecycle.manager import LifecycleManager
            from memoryhub.core.lifecycle.memory_consolidator import MemoryConsolidator
            from memoryhub.core.lifecycle.scheduler import LifecycleScheduler
            from memoryhub.core.lifecycle.session_consolidator import SessionConsolidator
            from memoryhub.core.preference.tool_miner import ToolPreferenceMiner

            st_repo = ShortTermMemoryRepository(db)
            mt_repo = MidTermMemoryRepository(db)
            # 暴露给检索级联（REFACTOR_PLAN_V2 §4.4.3 / I-4）：带 session_id 的
            # /search 需注入会话短期工作记忆与中期情景，再做长期混合。
            app.state.short_term_repo = st_repo
            app.state.mid_term_repo = mt_repo
            session_consolidator = SessionConsolidator(
                short_term_repo=st_repo, mid_term_repo=mt_repo, event_repo=event_repo
            )
            memory_consolidator = MemoryConsolidator(
                mid_term_repo=mt_repo,
                event_repo=event_repo,
                extraction_executor=extraction_executor,
                preference_updater=preference_updater,
                tool_miner=ToolPreferenceMiner(),
                workflow_miner=WorkflowMiner(),
            )
            memory_degrader = MemoryDegrader(
                pref_repo=pref_repo, know_repo=know_repo,
                mid_term_repo=mt_repo, write_service=app.state.memory_write_service,
                threshold=config.memory_tier.degrade_health_threshold,
            )
            app.state.lifecycle_scheduler = LifecycleScheduler(
                session_consolidator=session_consolidator,
                memory_consolidator=memory_consolidator,
                memory_degrader=memory_degrader,
                lifecycle_manager=LifecycleManager(
                    pref_repo=pref_repo, know_repo=know_repo
                ),
                interval_seconds=config.memory_tier.consolidate_interval_seconds,
                enabled=config.memory_tier.scheduler_enabled,
            )
            app.state.lifecycle_scheduler.start()

        # 用户遗忘规则（REFACTOR_PLAN_V2 §4.5.2 / I-13）：存用户自定义的
        # "删除所有涉及 X 的记忆"类主题规则，遗忘执行前并入意图关键词。
        from memoryhub.core.forget.rules import ForgetRuleService

        app.state.forget_rule_service = ForgetRuleService(
            database_path=config.storage.db_path
        )

        if config.runtime.is_production or vector_engine is not None:
            # 生产路径：仅装配 MilvusHybridRetriever，不构建 KeywordSearcher / HybridRetriever
            retriever = MilvusHybridRetriever(
                engine=vector_engine,
                embedding_fn=embedding_client.embed,
                config=config.retrieval,
                runtime_config=config.runtime,
                memory_lookup=memory_lookup,
                cache=cache,
                index_version=str(index_version),
            )
        else:
            # development/test 降级路径：构建 KeywordSearcher / HybridRetriever（FAISS + BM25）
            logger.warning(
                "app_hybrid_retriever_fallback_selected: "
                "HybridRetriever is only allowed in development/test "
                "or explicit diagnostic scenarios"
            )
            assert keyword_search is not None
            retriever = HybridRetriever(
                vector_search=vector_search_adapter,
                keyword_search=keyword_search,
                reranker=Reranker(),
                cache=cache,
                config=config.retrieval,
                embedding_fn=embedding_client.embed,
                memory_lookup=memory_lookup,
            )

        # 写入同步服务：SQLite 事实源 ↔ 当前运行时检索投影
        sync_service = MemorySyncService(
            pref_repo=pref_repo,
            know_repo=know_repo,
            embedding_client=embedding_client,
            vector_engine=vector_engine,
            cache=cache,
            retriever=(
                retriever if isinstance(retriever, MilvusHybridRetriever) else None
            ),
            index_version=index_version,
            config=config,
            memory_write_service=app.state.memory_write_service,
        )

        # 可靠 outbox 先补投影；pending_index 仍作为历史写入的短期恢复兼容。
        from memoryhub.storage.projection_outbox import ProjectionOutboxWorker

        projection_outbox_worker = ProjectionOutboxWorker(
            pref_repo=pref_repo,
            know_repo=know_repo,
            memory_write_service=app.state.memory_write_service,
            metrics=app.state.infrastructure_metrics,
            trace_store=app.state.trace_store,
        )
        projection_outbox_worker.run_once()

        # 启动时仅同步历史 pending_index 记录，禁止全量重建。
        sync_service.repair_at_startup()

        # 后台任务优先 drain durable outbox，再补偿历史 pending_index。
        compensation_task = PendingIndexCompensationTask(
            sync_service=sync_service,
            interval_seconds=30.0,
            enabled=vector_engine is not None or keyword_search is not None,
            projection_outbox_worker=projection_outbox_worker,
        )
        compensation_task.start()

        app.state.db = db
        app.state.pref_repo = pref_repo
        app.state.know_repo = know_repo
        app.state.vector_store = vector_store
        app.state.vector_engine = vector_engine
        app.state.embedding_client = embedding_client
        app.state.cache = cache
        app.state.retriever = retriever
        app.state.sync_service = sync_service
        app.state.projection_outbox_worker = projection_outbox_worker
        app.state.compensation_task = compensation_task

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
        # 停止抽取重试任务
        extraction_retry_task = getattr(app.state, "extraction_retry_task", None)
        if extraction_retry_task is not None:
            try:
                extraction_retry_task.stop()
            except Exception:
                logger.exception("failed to stop extraction retry task")
            app.state.extraction_retry_task = None

        # 停止 pending_index 补偿任务
        compensation_task = getattr(app.state, "compensation_task", None)
        if compensation_task is not None:
            try:
                compensation_task.stop()
            except Exception:
                pass
            app.state.compensation_task = None

        # 停止记忆分层流转调度
        lifecycle_scheduler = getattr(app.state, "lifecycle_scheduler", None)
        if lifecycle_scheduler is not None:
            try:
                lifecycle_scheduler.stop()
            except Exception:
                pass
            app.state.lifecycle_scheduler = None

        # 关闭最小 Memory Service
        if app.state.owns_memory_service:
            memory_service = getattr(app.state, "memory_service", None)
            if memory_service is not None:
                try:
                    memory_service.close()
                except Exception:
                    logger.exception("failed to close memory service")
                finally:
                    app.state.memory_service = None
                    app.state.owns_memory_service = False

        # 保存向量索引并关闭数据库
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
        embedding_client = getattr(app.state, "embedding_client", None)
        if embedding_client is not None:
            close = getattr(embedding_client, "close", None)
            try:
                if callable(close):
                    close()
            except Exception:
                pass
            finally:
                app.state.embedding_client = None

    return app


# 用于直接运行: uvicorn memoryhub.app:app --reload
app = create_app()
