"""
精准遗忘模块

支持自然语言驱动的记忆遗忘操作。
"""

from memoryhub.adapter.schemas import (
    ForgetRequest,
    ForgetResponse,
    ForgetRecord,
    SceneScope,
)


class MemoryForgetter:
    """
    精准遗忘执行器

    使用方式:
        forgetter = MemoryForgetter(llm_client=llm, storage=store)
        result = forgetter.execute(request)
    """

    def __init__(self, llm_client=None, storage=None, vector_store=None, cache=None):
        """
        参数:
            llm_client: LLM 客户端，用于意图解析
            storage: SQLite 存储层
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
              → parse_intent: 解析遗忘意图
              → locate_memories: 定位目标记忆
              → delete_memories: 删除记忆
              → clean_vector_index: 清理向量索引
              → clean_cache: 清理缓存
              → create_audit_log: 生成审计日志
              → 返回结果

        参数:
            request: 遗忘请求

        返回:
            ForgetResponse: 遗忘结果
        """
        raise NotImplementedError

    def parse_intent(self, instruction: str) -> dict:
        """
        解析自然语言遗忘指令

        参数:
            instruction: 用户指令，如 "忘掉我关于周报格式的偏好"

        返回:
            {
                "memory_type": "preference" | "knowledge" | "all",
                "target_topic": "周报格式",
                "scope": SceneScope,
                "confidence": 0.9
            }
        """
        raise NotImplementedError

    def locate_memories(self, intent: dict, user_id: str) -> list[str]:
        """
        根据解析的意图定位目标记忆 ID

        参数:
            intent: parse_intent 的返回结果
            user_id: 用户 ID

        返回:
            目标记忆 ID 列表
        """
        raise NotImplementedError

    def delete_memories(self, memory_ids: list[str]) -> int:
        """
        删除记忆（结构化数据 + 向量索引 + 缓存）

        数据流:
            memory_ids → delete_memories
              → 删除 SQLite 记录
              → 删除 FAISS 向量
              → 清除相关缓存

        参数:
            memory_ids: 待删除的记忆 ID 列表

        返回:
            成功删除的数量
        """
        raise NotImplementedError

    def create_audit_log(self, request: ForgetRequest, deleted_ids: list[str]) -> ForgetRecord:
        """
        生成遗忘审计日志

        参数:
            request: 原始遗忘请求
            deleted_ids: 实际删除的记忆 ID 列表

        返回:
            ForgetRecord 审计记录
        """
        raise NotImplementedError
