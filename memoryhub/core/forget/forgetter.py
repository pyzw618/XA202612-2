"""显式遗忘执行器

支持三种模式：
1. 精确 ID 模式：直接删除指定 memory_id
2. 范围删除模式：按 scope 批量删除
3. 自然语言模式：关键词匹配定位并删除
"""

import re
import time
import uuid
from datetime import datetime

from memoryhub.adapter.schemas import (
    ForgetRecord,
    ForgetRequest,
    ForgetResponse,
    MemoryDecision,
    MemoryStatus,
    SceneScope,
)

try:
    import jieba as _JIEBA
except ImportError:  # pragma: no cover
    _JIEBA = None


class MemoryForgetter:
    """
    显式遗忘执行器

    使用方式:
        forgetter = MemoryForgetter(
            llm_client=llm,
            pref_repo=pref_repo,
            know_repo=know_repo,
            vector_store=vs,
            cache=cache,
            db=db,
        )
        result = forgetter.execute(request)
    """

    def __init__(
        self,
        llm_client=None,
        storage=None,
        vector_store=None,
        vector_engine=None,
        cache=None,
        pref_repo=None,
        know_repo=None,
        keyword_search=None,
        memory_lookup=None,
        evidence_store=None,
        conflict_repo=None,
        fact_store=None,
        fact_index_service=None,
        memory_write_service=None,
        db=None,
    ):
        """
        参数:
            llm_client: LLM 客户端，用于自然语言意图解析
            storage: SQLite/SQLAlchemy 存储层（Database 实例，向后兼容）
            vector_store: FAISS 向量存储（development/test 降级路径）
            vector_engine: Milvus 向量引擎（生产路径）
            cache: 检索缓存
            pref_repo: PreferenceRepository 实例
            know_repo: KnowledgeRepository 实例
            db: Database 实例（向后兼容 storage 参数）
        """
        self.llm_client = llm_client
        self.storage = storage or db
        self.vector_store = vector_store
        self.vector_engine = vector_engine
        self.cache = cache
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.keyword_search = keyword_search
        self.memory_lookup = memory_lookup if memory_lookup is not None else {}
        self.evidence_store = evidence_store
        self.conflict_repo = conflict_repo
        self.fact_store = fact_store
        self.fact_index_service = fact_index_service
        self.memory_write_service = memory_write_service
        self._last_deleted_ids: list[str] = []

    def execute(self, request: ForgetRequest) -> ForgetResponse:
        """
        执行精准遗忘

        数据流:
            用户指令 → execute
              → 定位目标记忆
              → 级联删除
              → 生成审计日志
              → 返回结果
        """
        intent = self.parse_intent(request)
        target_ids = self.locate_memories(intent, request)

        deleted_count = 0
        if target_ids:
            deleted_count = self.delete_memories(
                target_ids, cascade=request.cascade, user_id=request.user_id
            )

        deleted_ids = list(self._last_deleted_ids)
        record = self.create_audit_log(request, deleted_ids)

        return ForgetResponse(
            record_id=record.record_id,
            deleted_count=deleted_count,
            deleted_ids=deleted_ids,
            audit_log="forgotten",
        )

    def parse_intent(self, request: ForgetRequest) -> dict:
        """
        解析遗忘意图。

        返回结构:
            {
                "memory_type": "preference" | "knowledge" | "all",
                "target_topic": str,
                "target_keywords": list[str],
                "scope": SceneScope | None,
                "time_range": dict | None,
                "confidence_threshold": float,
                "match_strategy": "semantic" | "keyword" | "exact",
            }

        目前基于规则的关键词/类型提取，不调用 LLM。
        """
        instruction = (request.instruction or "").strip()

        if request.target_memory_ids:
            strategy = "exact"
        elif request.target_project_id or (
            request.target_scope and (
                request.target_scope.scene
                or request.target_scope.task_type
                or request.target_scope.app
            )
        ):
            strategy = "scope"
        else:
            strategy = "semantic"

        memory_type = self._infer_memory_type(instruction)
        keywords = self._extract_keywords(instruction)

        return {
            "memory_type": memory_type,
            "target_topic": instruction,
            "target_keywords": keywords,
            "scope": request.target_scope,
            "time_range": None,
            "confidence_threshold": 0.0,
            "match_strategy": strategy,
        }

    def _infer_memory_type(self, instruction: str) -> str:
        """根据指令关键词推断记忆类型"""
        text = instruction.lower()
        preference_hints = ["偏好", "喜欢", "习惯", "preference", "prefer"]
        knowledge_hints = [
            "知识", "工作流", "流程", "模板", "案例",
            "knowledge", "workflow", "template",
        ]

        for hint in preference_hints:
            if hint in text:
                return "preference"
        for hint in knowledge_hints:
            if hint in text:
                return "knowledge"

        return "all"

    def _extract_keywords(self, instruction: str) -> list[str]:
        """简单提取关键词：去停用词、去标点、保留名词性片段"""
        stop_words = {
            "忘掉", "忘记", "删除", "去除", "清除", "关于", "的", "我",
            "请", "把", "将", "所有", "全部", "那个", "这个", "这些",
            "forget", "delete", "remove", "clear", "about", "my", "the",
        }

        # 去除标点
        cleaned = re.sub(r"[^\w\s]", " ", instruction)
        cleaned = re.sub(r"[^\u4e00-\u9fff\w\s]", " ", cleaned)

        # 中文用 jieba 分词，英文/数字按空白切分，避免"忘掉周报格式偏好"
        # 整句被当成一个关键词导致永远匹配不上记忆内容（FOR-03 定位失败）。
        tokens: list[str] = []
        if _JIEBA is not None:
            for word in _JIEBA.cut(cleaned):
                word = word.strip()
                if word:
                    tokens.append(word)
        else:
            tokens = [t for t in cleaned.split() if t]

        # 过滤停用词和过短的词
        keywords = [t for t in tokens if t.lower() not in stop_words and len(t) >= 2]
        return keywords

    def locate_memories(self, intent: dict, request: ForgetRequest) -> list[str]:
        """
        根据解析的意图定位目标记忆 ID。
        """
        strategy = intent.get("match_strategy", "semantic")

        if strategy == "exact" and request.target_memory_ids:
            return request.target_memory_ids

        if strategy == "scope":
            return self._locate_by_scope(
                request.target_scope or SceneScope(),
                intent.get("memory_type", "all"),
                request.user_id,
                request.target_project_id,
            )

        # 自然语言/关键词模式
        return self._locate_by_keywords(intent, request.user_id)

    def _locate_by_scope(
        self, scope, memory_type: str, user_id: str, project_id: str = ""
    ) -> list[str]:
        """按 scope 批量定位记忆

        对 target_scope 中显式给出的 scene/task_type/app 逐项匹配；
        未给出的维度不参与过滤（空 scene 不会误伤带 scene 的记忆，
        且 app 维度在此统一支持）。
        """
        ids: list[str] = []

        def _matches(mem_scope) -> bool:
            for field in ("scene", "task_type", "app"):
                expected = getattr(scope, field, "") or ""
                actual = getattr(mem_scope, field, "") or ""
                if expected and actual != expected:
                    return False
            return True

        if memory_type in ("preference", "all") and self.pref_repo is not None:
            for p in self.pref_repo.list_all(status="active", user_id=user_id):
                if _matches(p.scope):
                    ids.append(p.memory_id)

        if memory_type in ("knowledge", "all") and self.know_repo is not None:
            for k in self.know_repo.list_all(status="active", user_id=user_id):
                if _matches(k.scope):
                    ids.append(k.memory_id)

        if memory_type in ("fact", "all") and self.fact_store is not None and project_id:
            facts = self.fact_store.list_facts(
                status="active", limit=100000, scope="project",
                project_id=project_id, user_id=user_id,
            )
            ids.extend(f.fact_id for f in facts)

        return ids

    def _locate_by_keywords(self, intent: dict, user_id: str) -> list[str]:
        """基于关键词匹配定位记忆"""
        keywords = intent.get("target_keywords", [])
        memory_type = intent.get("memory_type", "all")
        matched: list[str] = []

        if not keywords:
            return matched

        if memory_type in ("preference", "all") and self.pref_repo is not None:
            prefs = self.pref_repo.get_active(user_id)
            for p in prefs:
                text = (p.text or "").lower()
                if any(kw.lower() in text for kw in keywords):
                    matched.append(p.memory_id)

        if memory_type in ("knowledge", "all") and self.know_repo is not None:
            knows = self.know_repo.list_all(status="active", user_id=user_id)
            for k in knows:
                text = f"{k.name or ''} {k.content or ''}".lower()
                if any(kw.lower() in text for kw in keywords):
                    matched.append(k.memory_id)

        if memory_type in ("fact", "all") and self.fact_store is not None:
            for fact in self.fact_store.list_facts(
                status="active", limit=100000, user_id=user_id
            ):
                text = self.fact_store.render_fact(fact).lower()
                if any(kw.lower() in text for kw in keywords):
                    matched.append(fact.fact_id)

        return matched

    def delete_memories(
        self, memory_ids: list[str], cascade: bool = True, user_id: str = ""
    ) -> int:
        """Soft-delete through domain writers so lineage and outbox remain authoritative."""
        deleted = 0
        self._last_deleted_ids = []
        for memory_id in memory_ids:
            pref_deleted = False
            know_deleted = False
            fact_deleted = False
            if self.pref_repo is not None:
                memory = self.pref_repo.get_by_id(memory_id)
                if memory is not None and (not user_id or memory.user_id == user_id):
                    memory.status = MemoryStatus.DELETED
                    if self.memory_write_service is not None:
                        self.memory_write_service.upsert_memory(
                            memory, action=MemoryDecision.SUPERSEDE
                        )
                        pref_deleted = True
                    else:
                        pref_deleted = self.pref_repo.update_status(
                            memory_id, "deleted", user_id=user_id
                        )
            if self.know_repo is not None:
                memory = self.know_repo.get_by_id(memory_id)
                if memory is not None and (not user_id or memory.user_id == user_id):
                    memory.status = MemoryStatus.DELETED
                    if self.memory_write_service is not None:
                        self.memory_write_service.upsert_memory(
                            memory, action=MemoryDecision.SUPERSEDE
                        )
                        know_deleted = True
                    else:
                        know_deleted = self.know_repo.update_status(
                            memory_id, "deleted", user_id=user_id
                        )
            if self.fact_store is not None:
                fact_deleted = self.fact_store.transition_fact_status(
                    memory_id,
                    "deleted",
                    user_id=user_id or None,
                    transition_action=MemoryDecision.SUPERSEDE.value,
                )
            if not (pref_deleted or know_deleted or fact_deleted):
                continue
            deleted += 1
            self._last_deleted_ids.append(memory_id)
            if cascade and self.memory_write_service is None:
                if self.vector_store is not None:
                    self.vector_store.delete(memory_id)
                if self.vector_engine is not None:
                    self.vector_engine.delete(memory_id)
                if self.keyword_search is not None:
                    self.keyword_search.delete(memory_id)
                self.memory_lookup.pop(memory_id, None)
                if self.evidence_store is not None:
                    self.evidence_store.delete(memory_id)
                if self.conflict_repo is not None:
                    self.conflict_repo.delete_for_memories([memory_id])
                if fact_deleted and hasattr(self.fact_store, "delete_fact_artifacts"):
                    self.fact_store.delete_fact_artifacts([memory_id], user_id)
                projection_version = time.time_ns()
                if pref_deleted and hasattr(self.pref_repo, "mark_indexed"):
                    self.pref_repo.mark_indexed([memory_id], projection_version)
                if know_deleted and hasattr(self.know_repo, "mark_indexed"):
                    self.know_repo.mark_indexed([memory_id], projection_version)
                if fact_deleted and hasattr(self.fact_store, "mark_indexed"):
                    self.fact_store.mark_indexed(memory_id, projection_version, user_id)
                if self.cache is not None:
                    self.cache.invalidate(memory_id)
        if deleted and self.fact_store is not None:
            self.fact_store.prune_orphan_entities(user_id)
        if deleted and cascade and self.memory_write_service is None:
            if self.vector_store is not None and hasattr(self.vector_store, "save"):
                self.vector_store.save()
            if self.vector_engine is not None and hasattr(self.vector_engine, "persist"):
                self.vector_engine.persist()
        return deleted

    def create_audit_log(self, request: ForgetRequest, deleted_ids: list[str]) -> ForgetRecord:
        """
        生成遗忘审计日志并持久化到数据库。
        """
        record = ForgetRecord(
            record_id=f"forget_{uuid.uuid4().hex[:16]}",
            user_id=request.user_id,
            instruction=request.instruction,
            target_memory_ids=deleted_ids,
            deleted_count=len(deleted_ids),
            target_scope=request.target_scope or SceneScope(),
            created_at=datetime.now(),
        )

        # 持久化到 forget_history 表
        if self.storage is not None:
            try:
                from memoryhub.storage.models import ForgetRow

                with self.storage.session() as s:
                    row = ForgetRow(
                        record_id=record.record_id,
                        user_id=record.user_id,
                        instruction=record.instruction,
                        target_memory_ids=record.target_memory_ids,
                        deleted_count=record.deleted_count,
                        created_at=record.created_at,
                    )
                    s.add(row)
                    s.commit()
            except Exception:
                pass

        return record
