"""
MemoryHub API 客户端

封装所有对 MemoryHub 后端 REST API 的 HTTP 调用。
后端地址默认 http://localhost:8000。
"""

from typing import Optional

import httpx


class MemoryHubClient:
    """MemoryHub REST API 客户端"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=10.0)

    def _get(
        self, path: str, params: dict | None = None, headers: dict | None = None
    ) -> dict | list[dict]:
        """GET 请求，自动处理错误。"""
        url = f"{self.base_url}/api/memory{path}"
        try:
            resp = self._client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            return {"error": str(e), "status_code": getattr(e, "response", None) and e.response.status_code}

    def _post(
        self, path: str, json_data: dict, headers: dict | None = None
    ) -> dict:
        """POST 请求，自动处理错误。"""
        url = f"{self.base_url}/api/memory{path}"
        try:
            resp = self._client.post(url, json=json_data, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            return {"error": str(e), "status_code": getattr(e, "response", None) and e.response.status_code}

    def _patch(
        self, path: str, json_data: dict, headers: dict | None = None
    ) -> dict:
        """PATCH 请求，自动处理错误。"""
        url = f"{self.base_url}/api/memory{path}"
        try:
            resp = self._client.patch(url, json=json_data, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            return {"error": str(e), "status_code": getattr(e, "response", None) and e.response.status_code}

    def _delete(
        self, path: str, params: dict | None = None, headers: dict | None = None
    ) -> dict:
        """DELETE 请求，自动处理错误。"""
        url = f"{self.base_url}/api/memory{path}"
        try:
            resp = self._client.delete(url, params=params, headers=headers)
            resp.raise_for_status()
            # 204 No Content
            if resp.status_code == 204:
                return {"success": True}
            return resp.json()
        except httpx.HTTPError as e:
            return {"error": str(e), "status_code": getattr(e, "response", None) and e.response.status_code}

    def _user_header(self, user_id: str) -> dict:
        """构造 X-MemoryHub-User 请求头"""
        return {"X-MemoryHub-User": user_id}

    # ============================================================
    # 核心接口（队长确认的 4 个）
    # ============================================================

    def search(
        self,
        query: str,
        context: dict | None = None,
        top_k: int = 5,
        memory_types: list[str] | None = None,
        min_confidence: float = 0.0,
        user_id: str = "default",
    ) -> dict:
        """
        POST /api/memory/search — 混合检索记忆

        参数:
            query: 检索查询文本
            context: 场景作用域 {"scene": "office", "task_type": "office.weekly_report", "app": "os_agent"}
            top_k: 返回结果数量
            memory_types: 过滤 ["preference", "knowledge"]
            min_confidence: 最低置信度阈值
            user_id: 用户 ID

        返回:
            {"results": [...], "preferences": [...], "knowledge": [...], "latency_ms": 0, "total_count": 0}
        """
        body = {
            "user_id": user_id,
            "query": query,
            "context": context or {},
            "top_k": top_k,
            "memory_types": memory_types or ["preference", "knowledge"],
            "min_confidence": min_confidence,
        }
        return self._post("/search", body)

    def get_context(self, query: str, context: dict | None = None,
                    user_id: str = "default") -> dict:
        """
        POST /api/memory/context — 获取可注入 prompt 的记忆文本

        与 search 类似，但返回可直接拼接进 Agent 上下文的文本。
        """
        body = {
            "user_id": user_id,
            "query": query,
            "context": context or {},
        }
        return self._post("/context", body)

    def write_events(self, events: list[dict]) -> dict:
        """
        POST /api/memory/events — 写入事件（本页面不直接调，预留给 OS Agent）

        返回:
            {"accepted": 0, "rejected": 0, "event_ids": [...]}
        """
        return self._post("/events", {"events": events})

    def forget(self, instruction: str, user_id: str = "default",
               target_scope: dict | None = None) -> dict:
        """
        POST /api/memory/forget — 精准遗忘

        参数:
            instruction: 自然语言遗忘指令，如 "忘掉我关于周报格式的偏好"
            user_id: 用户 ID
            target_scope: 可选的场景范围限制

        返回:
            {"record_id": "", "deleted_count": 0, "deleted_ids": [...], "audit_log": ""}
        """
        body: dict = {
            "user_id": user_id,
            "instruction": instruction,
        }
        if target_scope:
            body["target_scope"] = target_scope
        return self._post("/forget", body)

    # ============================================================
    # 管理接口 — 偏好
    # ============================================================

    def list_preferences(
        self, user_id: str = "default", scene: str = "", status: str = "active"
    ) -> list[dict]:
        """GET /api/memory/preferences — 列出偏好记忆"""
        return self._get("/preferences", {"user_id": user_id, "scene": scene, "status": status})  # type: ignore[return-value]

    def get_preference(self, memory_id: str, user_id: str = "default") -> dict:
        """GET /api/memory/preferences/{id} — 获取单条偏好详情"""
        return self._get(
            f"/preferences/{memory_id}", {"user_id": user_id}
        )  # type: ignore[return-value]

    def get_preference_versions(self, memory_id: str) -> list[dict]:
        """GET /api/memory/preferences/{id}/versions — 获取版本历史链"""
        return self._get(f"/preferences/{memory_id}/versions")  # type: ignore[return-value]

    # ============================================================
    # 管理接口 — 知识
    # ============================================================

    def list_knowledge(
        self, user_id: str = "default", scene: str = "", knowledge_type: str = ""
    ) -> list[dict]:
        """GET /api/memory/knowledge — 列出知识记忆"""
        return self._get("/knowledge", {  # type: ignore[return-value]
            "user_id": user_id, "scene": scene, "knowledge_type": knowledge_type
        })

    def get_knowledge(self, memory_id: str, user_id: str = "default") -> dict:
        """GET /api/memory/knowledge/{id} — 获取单条知识详情"""
        return self._get(
            f"/knowledge/{memory_id}", {"user_id": user_id}
        )  # type: ignore[return-value]

    # ============================================================
    # 管理接口 — 冲突
    # ============================================================

    def list_conflicts(
        self, status: str = "pending", user_id: str = "default"
    ) -> list[dict]:
        """GET /api/memory/conflicts — 列出当前用户的冲突记录"""
        return self._get(
            "/conflicts", {"status": status, "user_id": user_id}
        )  # type: ignore[return-value]

    def resolve_conflict(self, conflict_id: str, decision: str,
                         reason: str = "", user_id: str = "default") -> dict:
        """
        POST /api/memory/conflicts/{id}/resolve — 手动解决冲突

        参数:
            conflict_id: 冲突 ID
            decision: "override" | "merge" | "coexist" | "pending"
            reason: 处理原因说明
        """
        return self._post(f"/conflicts/{conflict_id}/resolve", {
            "user_id": user_id, "decision": decision, "reason": reason
        })

    # ============================================================
    # 管理接口 — 遗忘
    # ============================================================

    def get_forget_history(self, user_id: str = "default") -> list[dict]:
        """GET /api/memory/forget/history — 遗忘操作历史"""
        return self._get("/forget/history", {"user_id": user_id})  # type: ignore[return-value]

    # ============================================================
    # 管理接口 — 评测
    # ============================================================

    def run_evaluation(self, task_name: str, dataset_path: str = "") -> dict:
        """
        POST /api/memory/evaluate/{task_name} — 运行评测

        参数:
            task_name: "preference" | "retrieval" | "conflict" | "latency"
            dataset_path: 数据集路径（可选）
        """
        return self._post(f"/evaluate/{task_name}", {"dataset_path": dataset_path})

    def list_eval_reports(self) -> list[dict]:
        """GET /api/memory/evaluate/reports — 列出历史评测报告"""
        return self._get("/evaluate/reports")  # type: ignore[return-value]

    # ============================================================
    # 管理接口 — 反馈
    # ============================================================

    def submit_feedback(self, memory_id: str, feedback_text: str,
                        action: str = "update", user_id: str = "default") -> dict:
        """
        POST /api/memory/feedback — 提交用户反馈

        参数:
            memory_id: 关联的记忆 ID
            feedback_text: 反馈文本
            action: "update" | "confirm" | "reject"
        """
        return self._post("/feedback", {
            "user_id": user_id,
            "memory_id": memory_id,
            "feedback_text": feedback_text,
            "action": action,
        })

    # ============================================================
    # 管理接口 — 用户安全规则 (CRUD)
    # ============================================================

    def list_user_rules(self, user_id: str = "default",
                        include_deleted: bool = False) -> list[dict]:
        """
        GET /api/memory/safety/user-rules — 列出用户自定义敏感规则

        需要 X-MemoryHub-User 请求头。
        返回安全元数据（不含 matcher 密文）。
        """
        params = {"include_deleted": include_deleted}
        return self._get("/safety/user-rules", params, self._user_header(user_id))  # type: ignore[return-value]

    def get_user_rule(self, rule_id: str, user_id: str = "default") -> dict:
        """
        GET /api/memory/safety/user-rules/{rule_id} — 获取单条规则
        """
        return self._get(
            f"/safety/user-rules/{rule_id}", None, self._user_header(user_id)
        )  # type: ignore[return-value]

    def create_user_rule(
        self,
        label: str,
        kind: str,
        effect: str,
        matcher: str,
        case_sensitive: bool = False,
        enabled: bool = True,
        user_id: str = "default",
    ) -> dict:
        """
        POST /api/memory/safety/user-rules — 创建规则

        参数:
            label: 规则标签（如 "API Key"）
            kind: "literal" | "advanced_regex"
            effect: "mask_match" | "drop_event"
            matcher: 匹配模式（密文，仅写入不回传）
            case_sensitive: 是否区分大小写
            enabled: 是否启用
        """
        body = {
            "label": label,
            "kind": kind,
            "effect": effect,
            "matcher": matcher,
            "case_sensitive": case_sensitive,
            "enabled": enabled,
        }
        return self._post("/safety/user-rules", body, self._user_header(user_id))

    def update_user_rule(
        self,
        rule_id: str,
        expected_revision: int,
        user_id: str = "default",
        **updates,
    ) -> dict:
        """
        PATCH /api/memory/safety/user-rules/{rule_id} — 更新规则

        参数:
            rule_id: 规则 ID
            expected_revision: 乐观锁版本号（必填）
            **updates: 可选字段 label, kind, effect, matcher, case_sensitive, enabled
        """
        body = {"expected_revision": expected_revision}
        body.update({k: v for k, v in updates.items() if v is not None})
        return self._patch(
            f"/safety/user-rules/{rule_id}", body, self._user_header(user_id)
        )

    def delete_user_rule(
        self, rule_id: str, expected_revision: int, user_id: str = "default"
    ) -> dict:
        """
        DELETE /api/memory/safety/user-rules/{rule_id} — 删除规则（软删除）

        参数:
            rule_id: 规则 ID
            expected_revision: 乐观锁版本号（必填）
        """
        return self._delete(
            f"/safety/user-rules/{rule_id}",
            {"expected_revision": expected_revision},
            self._user_header(user_id),
        )

    def close(self):
        """关闭 HTTP 客户端"""
        self._client.close()
