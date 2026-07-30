"""显式遗忘执行器

支持三种模式：
1. 精确 ID 模式：直接删除指定 memory_id
2. 范围删除模式：按 scope 批量删除
3. 自然语言模式：LLM 解析意图后定位并删除（第一版仅提供占位实现）
"""

import re

from memoryhub.adapter.schemas import (
    ForgetRequest,
    ForgetResponse,
    ForgetRecord,
    SceneScope,
)


class MemoryForgetter:
    """
    显式遗忘执行器

    使用方式:
        forgetter = MemoryForgetter(llm_client=llm, storage=db, vector_store=vs, cache=cache)
        result = forgetter.execute(request)
    """

    def __init__(self, llm_client=None, storage=None, vector_store=None, cache=None):
        """
        参数:
            llm_client: LLM 客户端，用于自然语言意图解析
            storage: SQLite/SQLAlchemy 存储层
            vector_store: FAISS 向量存储
            cache: 检索缓存
        """
        self.llm_client = llm_client
        self.storage = storage
        self.vector_store = vector_store
        self.cache = cache

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
            deleted_count = self.delete_memories(target_ids, cascade=request.cascade)

        record = self.create_audit_log(request, target_ids[:deleted_count] if deleted_count else [])

        return ForgetResponse(
            record_id=record.record_id,
            deleted_count=deleted_count,
            deleted_ids=target_ids[:deleted_count] if deleted_count else target_ids,
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

        第一版：基于规则的关键词/类型提取，不调用 LLM。
        """
        instruction = (request.instruction or "").strip()

        if request.target_memory_ids:
            strategy = "exact"
        elif request.target_scope and (request.target_scope.scene or request.target_scope.task_type or request.target_scope.app):
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
        knowledge_hints = ["知识", "工作流", "流程", "模板", "案例", "knowledge", "workflow", "template"]

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

        # 去除标点并分词
        cleaned = re.sub(r"[^\w\s]", " ", instruction)
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

        if strategy == "scope" and request.target_scope:
            return self._locate_by_scope(request.target_scope, intent.get("memory_type", "all"), request.user_id)

        # 自然语言/语义模式：先做关键词匹配，后续可接入 LLM + 向量检索
        return self._locate_by_keywords(intent, request.user_id)

    def _locate_by_scope(self, scope, memory_type: str, user_id: str) -> list[str]:
        """按 scope 批量定位记忆"""
        # PSEUDO-DB: 根据 memory_type 选择 preferences / knowledge / UNION
        #            SELECT memory_id FROM preferences
        #            WHERE user_id=? AND scope_scene=? AND scope_task_type=? AND scope_app=? AND status='active'
        #            UNION
        #            SELECT memory_id FROM knowledge
        #            WHERE user_id=? AND scope_scene=? AND scope_task_type=? AND scope_app=? AND status='active'
        return []

    def _locate_by_keywords(self, intent: dict, user_id: str) -> list[str]:
        """基于关键词匹配定位记忆"""
        keywords = intent.get("target_keywords", [])
        memory_type = intent.get("memory_type", "all")

        # PSEUDO-DB: 查询用户的 active 记忆，按 memory_type 过滤
        # candidates = db.query(...).filter(user_id=user_id, status='active').all()
        candidates = []

        matched = []
        for candidate in candidates:
            content = getattr(candidate, "content", "") or ""
            name = getattr(candidate, "name", "") or ""
            text = f"{name} {content}".lower()
            if any(kw.lower() in text for kw in keywords):
                matched.append(getattr(candidate, "memory_id", ""))

        return matched

    def delete_memories(self, memory_ids: list[str], cascade: bool = True) -> int:
        """
        删除记忆（结构化数据 + 向量索引 + 缓存）。

        第一版采用软删除：status = 'deleted'，后续再物理清理。
        """
        deleted = 0
        for memory_id in memory_ids:
            # PSEUDO-DB: UPDATE preferences SET status='deleted' WHERE memory_id=?
            # PSEUDO-DB: UPDATE knowledge SET status='deleted' WHERE memory_id=?
            deleted += 1

            if cascade:
                # 清理向量索引
                if self.vector_store is not None:
                    # PSEUDO-FAISS: self.vector_store.delete(memory_id)
                    pass

                # 清理检索缓存
                if self.cache is not None:
                    # PSEUDO-CACHE: self.cache.invalidate(memory_id)
                    pass

                # 标记关联冲突记录
                # PSEUDO-DB: UPDATE conflicts SET decision='cleaned' WHERE old_memory_id=? OR new_memory_id=?
                pass

        return deleted

    def create_audit_log(self, request: ForgetRequest, deleted_ids: list[str]) -> ForgetRecord:
        """
        生成遗忘审计日志。
        """
        # PSEUDO-DB: INSERT INTO forget_history (...) VALUES (...)
        return ForgetRecord(
            user_id=request.user_id,
            instruction=request.instruction,
            target_memory_ids=deleted_ids,
            deleted_count=len(deleted_ids),
        )
