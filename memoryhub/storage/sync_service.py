"""
SQLite ↔ Milvus 写入同步与补偿服务

SQLite 作为记忆记录的唯一事实源；Milvus 作为可重建的检索投影。
本服务负责：
  1. 新记忆写入 SQLite 后，生成 embedding 并 upsert 到 Milvus；
  2. 写入失败时标记 pending_index，由补偿任务重试；
  3. 遗忘时先在 SQLite 软删除，再删除 Milvus 向量，最后失效缓存；
  4. 启动时仅同步 pending_index 记录，禁止全量重建。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
)
from memoryhub.storage.database import (
    KnowledgeRepository,
    PreferenceRepository,
)

if TYPE_CHECKING:
    from memoryhub.config import AppConfig
    from memoryhub.embedding.base import BaseEmbeddingClient
    from memoryhub.retrieval.cache import SearchCache
    from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
    from memoryhub.storage.vector_engine.base import BaseVectorEngine

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """一次同步/补偿任务的结果统计。"""

    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: int = 0
    duration_ms: float = 0.0


class MemorySyncService:
    """
    记忆写入与向量索引同步服务。

    使用方式:
        service = MemorySyncService(
            pref_repo=pref_repo,
            know_repo=know_repo,
            embedding_client=embedding_client,
            vector_engine=vector_engine,
            cache=cache,
            retriever=retriever,
            index_version=index_version,
        )
        ok, memory_id = service.index_memory(memory)
        service.delete_memory(memory_id)
        result = service.sync_pending()
    """

    def __init__(
        self,
        pref_repo: PreferenceRepository,
        know_repo: KnowledgeRepository,
        embedding_client: BaseEmbeddingClient,
        vector_engine: BaseVectorEngine | None,
        cache: SearchCache | None = None,
        retriever: MilvusHybridRetriever | None = None,
        index_version: int = 1,
        config: AppConfig | None = None,
    ):
        """
        参数:
            pref_repo: 偏好记忆仓储
            know_repo: 知识记忆仓储
            embedding_client: Embedding 客户端
            vector_engine: 向量引擎（生产环境要求 milvus）
            cache: 检索结果缓存；为 None 时跳过缓存失效
            retriever: 生产环境检索器；用于更新其 index_version
            index_version: 当前向量索引版本号
            config: 应用配置
        """
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.embedding_client = embedding_client
        self.vector_engine = vector_engine
        self.cache = cache
        self.retriever = retriever
        self.index_version = index_version
        self.config = config

    # ---- 公开接口 ----

    def index_memory(self, memory: PreferenceMemory | KnowledgeMemory) -> tuple[bool, str]:
        """
        写入/更新单条记忆，并同步到 Milvus。

        流程:
            1. 先写入 SQLite（pending_index=True）
            2. 生成稠密向量与稀疏向量所需文本
            3. upsert 到 Milvus
            4. 成功：标记 index_version、pending_index=False，失效缓存
            5. 失败：保留 pending_index=True，由补偿任务重试

        返回:
            (sqlite_success, memory_id)
        """
        memory_id = memory.memory_id
        try:
            self._save_to_sqlite(memory)
        except Exception:
            logger.exception("sqlite write failed for memory %s", memory_id)
            return False, memory_id

        # SQLite 已持久化；后续 Milvus 失败可通过 pending_index 补偿
        vector_ok = self._upsert_to_vector_engine(memory)
        if vector_ok:
            self._mark_indexed([memory_id])
        else:
            logger.warning(
                "vector engine upsert failed for memory %s, marked pending_index", memory_id
            )

        # 无论 Milvus 是否成功，都尝试失效该记忆相关的检索缓存
        self._invalidate_cache_for(memory_id)
        return True, memory_id

    def delete_memory(self, memory_id: str) -> bool:
        """
        删除/遗忘单条记忆。

        流程:
            1. 先在 SQLite 中标记 status='deleted'
            2. 从 Milvus 删除向量记录
            3. 失效检索缓存
        """
        sqlite_ok = self._mark_deleted_in_sqlite(memory_id)
        if not sqlite_ok:
            logger.warning("sqlite soft-delete failed for memory %s", memory_id)
            return False

        if self.vector_engine is not None:
            try:
                self.vector_engine.delete(memory_id)
            except Exception:
                logger.exception("vector engine delete failed for memory %s", memory_id)
                # SQLite 已标记删除，向量删除失败会在下次补偿或启动时重试
                # （Milvus 侧可由Milvus根据主键幂等删除，重复删除无害）

        self._invalidate_cache_for(memory_id)
        return True

    def sync_pending(self) -> SyncResult:
        """
        扫描 SQLite 中的 pending_index 记录，补偿同步到 Milvus。

        返回:
            SyncResult，包含成功、失败的 memory_id 列表
        """
        start = time.perf_counter()
        result = SyncResult()

        pending = [*self.pref_repo.list_pending(), *self.know_repo.list_pending()]
        if not pending:
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result

        # 新写入导致索引版本变化；同步成功后统一使用该版本号
        self.index_version += 1
        current_version = self.index_version

        # 批量 upsert 以提高效率
        batch_items = []
        memory_map: dict[str, PreferenceMemory | KnowledgeMemory] = {}
        for memory in pending:
            text = self._memory_text(memory)
            try:
                vector = self.embedding_client.embed(text)
            except Exception:
                logger.exception("embedding failed for pending memory %s", memory.memory_id)
                result.failed.append(memory.memory_id)
                continue
            batch_items.append(
                (
                    memory.memory_id,
                    text,
                    vector,
                    self._memory_metadata(memory),
                )
            )
            memory_map[memory.memory_id] = memory

        if not batch_items:
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result

        failed_ids: list[str] = []
        if self.vector_engine is not None:
            try:
                failed_ids = self.vector_engine.upsert_batch(batch_items)
            except Exception:
                logger.exception("vector engine upsert_batch failed")
                failed_ids = [item[0] for item in batch_items]
        else:
            failed_ids = [item[0] for item in batch_items]

        succeeded_ids = [m_id for m_id in memory_map if m_id not in failed_ids]
        if succeeded_ids:
            self._mark_indexed(succeeded_ids, version=current_version)
            for m_id in succeeded_ids:
                self._invalidate_cache_for(m_id)
                result.succeeded.append(m_id)

        for m_id in failed_ids:
            result.failed.append(m_id)

        # 更新 retriever 的索引版本号，使旧版本缓存自然失效
        self._bump_retriever_version()

        result.duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "pending_index sync completed: succeeded=%d failed=%d duration_ms=%.2f",
            len(result.succeeded),
            len(result.failed),
            result.duration_ms,
        )
        return result

    def repair_at_startup(self) -> SyncResult:
        """启动时修复：仅同步 pending_index 记录，禁止全量重建。"""
        logger.info("startup repair: syncing pending_index records")
        return self.sync_pending()

    # ---- 内部 ----

    def _save_to_sqlite(self, memory: PreferenceMemory | KnowledgeMemory) -> None:
        """保存记忆到 SQLite；新写入标记 pending_index=True。"""
        if isinstance(memory, PreferenceMemory):
            self.pref_repo.save(memory)
        else:
            self.know_repo.save(memory)

    def _upsert_to_vector_engine(
        self, memory: PreferenceMemory | KnowledgeMemory
    ) -> bool:
        """生成 embedding 并 upsert 到向量引擎。返回是否成功。"""
        if self.vector_engine is None:
            return False
        text = self._memory_text(memory)
        try:
            vector = self.embedding_client.embed(text)
        except Exception:
            logger.exception("embedding failed for memory %s", memory.memory_id)
            return False
        try:
            self.vector_engine.upsert(
                memory.memory_id,
                text,
                vector,
                metadata=self._memory_metadata(memory),
            )
        except Exception:
            logger.exception("vector engine upsert failed for memory %s", memory.memory_id)
            return False
        return True

    def _mark_indexed(self, memory_ids: list[str], version: int | None = None) -> None:
        """标记指定记忆已同步到向量索引。"""
        if version is None:
            self.index_version += 1
            version = self.index_version
        pref_ids = []
        know_ids = []
        for m_id in memory_ids:
            # 通过查询判断类型，避免依赖 memory_type 字符串
            if self.pref_repo.get_by_id(m_id) is not None:
                pref_ids.append(m_id)
            elif self.know_repo.get_by_id(m_id) is not None:
                know_ids.append(m_id)
        try:
            if pref_ids:
                self.pref_repo.mark_indexed(pref_ids, version)
            if know_ids:
                self.know_repo.mark_indexed(know_ids, version)
        except Exception:
            logger.exception("mark_indexed failed for %s", memory_ids)
            # SQLite 标记失败但 Milvus 已写入：记录补偿任务，避免幽灵向量
            # 这里保留 pending_index=True，让补偿任务下次重试
            raise

    def _mark_deleted_in_sqlite(self, memory_id: str) -> bool:
        """在 SQLite 中软删除记忆。"""
        try:
            self.pref_repo.update_status(memory_id, "deleted")
            self.know_repo.update_status(memory_id, "deleted")
            return True
        except Exception:
            logger.exception("sqlite soft-delete failed for memory %s", memory_id)
            return False

    def _invalidate_cache_for(self, memory_id: str) -> None:
        """使包含指定记忆 ID 的检索缓存失效。"""
        if self.cache is not None:
            try:
                self.cache.invalidate(memory_id)
            except Exception:
                logger.exception("cache invalidation failed for memory %s", memory_id)

    def _bump_retriever_version(self) -> None:
        """更新生产环境检索器的 index_version，使旧缓存键失效。"""
        if self.retriever is not None:
            try:
                self.retriever.index_version = str(self.index_version)
            except Exception:
                logger.exception("failed to bump retriever index_version")

    @staticmethod
    def _memory_text(memory: PreferenceMemory | KnowledgeMemory) -> str:
        """用于建索引的记忆文本。"""
        if memory.memory_type == "knowledge":
            return f"{memory.name} {memory.content}".strip()
        return memory.text

    @staticmethod
    def _memory_metadata(memory: PreferenceMemory | KnowledgeMemory) -> dict:
        """检索过滤所需的元数据。"""
        return {
            "memory_type": memory.memory_type,
            "content": MemorySyncService._memory_text(memory),
            "confidence": memory.confidence,
            "scope": memory.scope.model_dump(),
        }
