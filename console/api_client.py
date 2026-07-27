"""
MemoryHub API 客户端

封装所有对 MemoryHub 后端 REST API 的 HTTP 调用。
后端地址默认 http://localhost:8000。
"""

import httpx
from typing import Optional


class MemoryHubClient:
    """MemoryHub REST API 客户端"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=10.0)

    # ============================================================
    # 核心接口（队长确认的 4 个）
    # ============================================================

    def search(self, query: str, context: dict, top_k: int = 5) -> dict:
        """POST /api/memory/search — 检索记忆"""
        ...

    def get_context(self, query: str, context: dict) -> dict:
        """POST /api/memory/context — 获取可注入 prompt 的记忆文本"""
        ...

    def write_events(self, events: list[dict]) -> dict:
        """POST /api/memory/events — 写入事件（本页面不直接调，预留给 OS Agent）"""
        ...

    def forget(self, instruction: str, user_id: str = "default") -> dict:
        """POST /api/memory/forget — 精准遗忘"""
        ...

    # ============================================================
    # 管理接口
    # ============================================================

    def list_preferences(self, user_id: str = "default", scene: str = "",
                         status: str = "active") -> list[dict]:
        """GET /api/memory/preferences — 列出偏好记忆"""
        ...

    def get_preference(self, memory_id: str) -> dict:
        """GET /api/memory/preferences/{id} — 获取单条偏好"""
        ...

    def get_preference_versions(self, memory_id: str) -> list[dict]:
        """GET /api/memory/preferences/{id}/versions — 获取版本链"""
        ...

    def list_knowledge(self, user_id: str = "default", scene: str = "",
                       knowledge_type: str = "") -> list[dict]:
        """GET /api/memory/knowledge — 列出知识记忆"""
        ...

    def get_knowledge(self, memory_id: str) -> dict:
        """GET /api/memory/knowledge/{id} — 获取单条知识"""
        ...

    def list_conflicts(self, status: str = "pending") -> list[dict]:
        """GET /api/memory/conflicts — 列出冲突"""
        ...

    def resolve_conflict(self, conflict_id: str, decision: str, reason: str = "") -> dict:
        """POST /api/memory/conflicts/{id}/resolve — 解决冲突"""
        ...

    def get_forget_history(self, user_id: str = "default") -> list[dict]:
        """GET /api/memory/forget/history — 遗忘历史"""
        ...

    def run_evaluation(self, task_name: str) -> dict:
        """POST /api/memory/evaluate/{task_name} — 运行评测"""
        ...

    def list_eval_reports(self) -> list[dict]:
        """GET /api/memory/evaluate/reports — 列出评测报告"""
        ...