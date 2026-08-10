from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .api import MemoryHubApi
from .models import (
    ConflictListModel,
    EvalListModel,
    FactListModel,
    FactProposalListModel,
    ForgetListModel,
    KnowledgeListModel,
    MemoryListModel,
    MessageListModel,
    PreferenceListModel,
    RetrievalListModel,
    SafetyRuleListModel,
    ToolCallListModel,
    TurnListModel,
)
from .replay import ReplayError, external_tool_calls, freshen_session, load_replay, mask_for_display


class MemoryHubController(QObject):
    stateChanged = Signal()
    noticeChanged = Signal()
    factDecisionFinished = Signal(str, str)

    def __init__(self, api: MemoryHubApi, demo_path: str | Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self._demo_path = Path(demo_path) if demo_path else self._find_demo_path()
        self._session: dict[str, Any] = {}
        self._index = 0
        self._executed: set[int] = set()
        self._busy = False
        self._online = False
        self._status = "正在检测后端服务…"
        self._notice = ""
        self._write_summary: list[str] = []
        self._last_latency_ms = 0
        self._pending: dict[str, tuple[str, int | None]] = {}
        self._started_at = time.perf_counter()
        self._startup_ms = 0
        self._active_section = "agent"
        self._current_user_id = "default"

        self.turn_model = TurnListModel(self)
        self.message_model = MessageListModel(self)
        self.tool_model = ToolCallListModel(self)
        self.memory_model = MemoryListModel(self)
        self.fact_model = FactProposalListModel(self)
        self.preference_model = PreferenceListModel(self)
        self._preference_loading = False
        self.knowledge_model = KnowledgeListModel(self)
        self._knowledge_loading = False
        self._knowledge_data: list[dict[str, Any]] = []
        self.fact_model_page = FactListModel(self)
        self.retrieval_model = RetrievalListModel(self)
        self.conflict_model = ConflictListModel(self)
        self.forget_model = ForgetListModel(self)
        self.safety_model = SafetyRuleListModel(self)
        self.eval_model = EvalListModel(self)
        self._page_loading = False

        self.api.succeeded.connect(self._on_success)
        self.api.failed.connect(self._on_failure)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5_000)
        self._health_timer.timeout.connect(self.retryBackend)
        # 提示自动消失：4 秒后清除底部 notice
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(4_000)
        self._notice_timer.timeout.connect(self._clear_notice)

    @staticmethod
    def _find_demo_path() -> Path:
        package_demo = Path(__file__).parent / "assets" / "memory-system-long-replay.json"
        if package_demo.exists():
            return package_demo
        return (
            Path(__file__).resolve().parents[1]
            / "frontend"
            / "public"
            / "examples"
            / "memory-system-long-replay.json"
        )

    @Property(QObject, constant=True)
    def turnModel(self) -> QObject:
        return self.turn_model

    @Property(QObject, constant=True)
    def messageModel(self) -> QObject:
        return self.message_model

    @Property(QObject, constant=True)
    def toolModel(self) -> QObject:
        return self.tool_model

    @Property(QObject, constant=True)
    def memoryModel(self) -> QObject:
        return self.memory_model

    @Property(QObject, constant=True)
    def factModel(self) -> QObject:
        return self.fact_model

    @Property(QObject, constant=True)
    def preferenceModel(self) -> QObject:
        return self.preference_model

    @Property(QObject, constant=True)
    def knowledgeModel(self) -> QObject:
        return self.knowledge_model

    @Property(QObject, constant=True)
    def factsModel(self) -> QObject:
        return self.fact_model_page

    @Property(QObject, constant=True)
    def retrievalModel(self) -> QObject:
        return self.retrieval_model

    @Property(QObject, constant=True)
    def conflictsModel(self) -> QObject:
        return self.conflict_model

    @Property(QObject, constant=True)
    def forgetModel(self) -> QObject:
        return self.forget_model

    @Property(QObject, constant=True)
    def safetyModel(self) -> QObject:
        return self.safety_model

    @Property(QObject, constant=True)
    def evaluationModel(self) -> QObject:
        return self.eval_model

    @Property(bool, notify=stateChanged)
    def pageLoading(self) -> bool:
        return self._page_loading

    @Property(bool, notify=stateChanged)
    def preferenceLoading(self) -> bool:
        return self._preference_loading

    @Property(bool, notify=stateChanged)
    def knowledgeLoading(self) -> bool:
        return self._knowledge_loading

    @Property(str, notify=stateChanged)
    def title(self) -> str:
        return str(self._session.get("title") or "尚未载入会话")

    @Property(str, notify=stateChanged)
    def sessionId(self) -> str:
        return str(self._session.get("session_id") or "—")

    @Property(int, notify=stateChanged)
    def currentIndex(self) -> int:
        return self._index

    @Property(int, notify=stateChanged)
    def totalTurns(self) -> int:
        return len(self._session.get("turns") or [])

    @Property(bool, notify=stateChanged)
    def currentExecuted(self) -> bool:
        return self._index in self._executed

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, notify=stateChanged)
    def online(self) -> bool:
        return self._online

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=noticeChanged)
    def notice(self) -> str:
        return self._notice

    @Property(str, notify=stateChanged)
    def writeSummary(self) -> str:
        return "\n".join(self._write_summary) or "本轮尚未写入记忆"

    @Property(int, notify=stateChanged)
    def lastLatencyMs(self) -> int:
        return self._last_latency_ms

    @Property(int, notify=stateChanged)
    def startupMs(self) -> int:
        return self._startup_ms

    @Property(bool, notify=stateChanged)
    def canGoPrevious(self) -> bool:
        return self._index > 0 and not self._busy

    @Property(bool, notify=stateChanged)
    def canGoNext(self) -> bool:
        return self.currentExecuted and self._index + 1 < self.totalTurns and not self._busy

    @Property(str, notify=stateChanged)
    def activeSection(self) -> str:
        return self._active_section

    @Property(int, notify=stateChanged)
    def sectionIndex(self) -> int:
        """主内容 StackLayout 的页面索引，与 Main.qml 子页顺序保持一致。"""
        return {
            "agent": 0,
            "preferences": 1,
            "knowledge": 2,
            "facts": 3,
            "retrieval": 4,
            "conflicts": 5,
            "forget": 6,
            "safety": 7,
            "evaluation": 8,
            "settings": 9,
        }.get(self._active_section, 0)

    @Property(str, notify=stateChanged)
    def currentUserId(self) -> str:
        return self._current_user_id

    @Slot()
    def start(self) -> None:
        self._startup_ms = int((time.perf_counter() - self._started_at) * 1000)
        self.loadDemo()
        self.retryBackend()
        self._health_timer.start()

    @Slot()
    def retryBackend(self) -> None:
        token = self.api.health()
        self._pending[token] = ("health", None)

    @Slot()
    def loadDemo(self) -> None:
        try:
            self._set_session(freshen_session(load_replay(self._demo_path)))
            # 载入“全新会话”：先清空上一轮演示产生的偏好，避免重复累积
            self.clearPreferences()
            self._set_notice("已创建全新的 10 轮测试会话；记忆结果将在逐轮执行后生成。")
        except ReplayError as exc:
            self._set_notice(f"示例加载失败：{exc}")

    @Slot(str)
    def importReplay(self, file_url: str) -> None:
        try:
            path = QUrl(file_url).toLocalFile() if file_url.startswith("file:") else file_url
            self._set_session(freshen_session(load_replay(path)))
            self._set_notice("JSON 已导入。点击“执行本轮”让真实后端处理记忆。")
        except ReplayError as exc:
            self._set_notice(f"导入失败：{exc}")

    def _set_session(self, session: dict[str, Any]) -> None:
        self._session = session
        self._index = 0
        self._executed.clear()
        self._write_summary = []
        self._last_latency_ms = 0
        # 从事件中提取当前会话的用户 ID，供查询管理页使用
        events = session.get("events") or []
        user_id = ""
        for event in events:
            if isinstance(event, dict) and event.get("user_id"):
                user_id = str(event["user_id"])
                break
        self._current_user_id = user_id or "default"
        self._refresh_models()

    @Slot(int)
    def goToTurn(self, index: int) -> None:
        if 0 <= index < self.totalTurns and not self._busy:
            self._index = index
            self._refresh_models()

    @Slot()
    def previousTurn(self) -> None:
        self.goToTurn(self._index - 1)

    @Slot()
    def nextTurn(self) -> None:
        if self.canGoNext:
            self.goToTurn(self._index + 1)

    @Slot()
    def executeCurrent(self) -> None:
        turns = self._session.get("turns") or []
        if self._busy or not turns:
            return
        if not self._online:
            self._set_notice("后端未连接。请先启动 FastAPI 服务，再点击重试。")
            return
        turn = turns[self._index]
        events = []
        seen = set()
        for event in [*self._session.get("events", []), *turn.get("events", [])]:
            event_id = str(event.get("event_id") or "")
            if event.get("turn_id") == turn["turn_id"] and event_id not in seen:
                events.append(event)
                seen.add(event_id)
        first = events[0] if events else {}
        payload = {
            "session_id": self.sessionId,
            "turn_id": turn["turn_id"],
            "user_message": turn["user_message"],
            "retrieval_query": turn.get("retrieval_query") or turn["user_message"],
            "scene": first.get("scene") or "chat",
            "task_type": first.get("task_type") or "memory_demo",
            "events": events,
        }
        self._busy = True
        self._status = "正在执行本轮…"
        self.stateChanged.emit()
        token = self.api.post("step", "/api/agent/step", payload)
        self._pending[token] = ("step", self._index)

    @Slot(int, result="QVariantMap")
    def factAt(self, index: int) -> dict[str, Any]:
        return self.fact_model.get(index)

    @Slot(str, bool, str, str, str)
    def submitFactDecision(
        self,
        proposal_id: str,
        commit: bool,
        scope: str,
        project_id: str,
        resolution: str,
    ) -> None:
        if not proposal_id or self._busy:
            return
        action_type = "fact_commit" if commit else "fact_reject"
        payload = {
            "action_type": action_type,
            "decision": resolution if commit else "用户忽略",
            "payload": (
                {"scope": scope, "project_id": project_id or None, "resolution": resolution or None}
                if commit
                else {"reason": "用户在 QML 客户端中忽略"}
            ),
        }
        self._busy = True
        self.stateChanged.emit()
        token = self.api.post("decision", f"/api/agent/actions/{proposal_id}/decision", payload)
        self._pending[token] = ("decision", None)

    @Slot()
    @Slot(str)
    @Slot(str, str)
    def loadPreferences(self, status: str = "", scene: str = "") -> None:
        if self._preference_loading:
            return
        self._preference_loading = True
        self.stateChanged.emit()
        user_id = self._current_user_id
        # main 后端的 preferences 接口对空的 scene/status 会按“精确匹配空值”过滤，
        # 导致结果为空；因此仅在确实传入了过滤条件时才拼接查询参数。
        params = [f"user_id={user_id}"]
        if scene:
            params.append(f"scene={scene}")
        if status:
            params.append(f"status={status}")
        path = "/api/memory/preferences?" + "&".join(params)
        token = self.api.get("preferences", path)
        self._pending[token] = ("preferences", None)

    @Slot()
    @Slot(str)
    @Slot(str, str)
    def loadKnowledge(self, knowledge_type: str = "", scene: str = "") -> None:
        """加载知识记忆列表。main 的 knowledge 接口在 scene/type 为空时返回全部。"""
        if self._knowledge_loading:
            return
        self._knowledge_loading = True
        self.stateChanged.emit()
        user_id = self._current_user_id
        params = [f"user_id={user_id}"]
        if scene:
            params.append(f"scene={scene}")
        if knowledge_type:
            params.append(f"knowledge_type={knowledge_type}")
        path = "/api/memory/knowledge?" + "&".join(params)
        token = self.api.get("knowledge", path)
        self._pending[token] = ("knowledge", None)

    @Slot(str, str)
    def filterKnowledge(self, type_index: str, keyword: str) -> None:
        """在已加载的知识列表上做本地过滤（类型 + 名称/内容关键词）。"""
        try:
            ti = int(str(type_index) or "0")
        except ValueError:
            ti = 0
        types = {1: "workflow", 2: "case", 3: "template"}
        want_type = types.get(ti, "")
        kw = str(keyword or "").strip().lower()
        out = []
        for item in self._knowledge_data:
            if want_type and str(item.get("knowledge_type") or "") != want_type:
                continue
            if kw:
                hay = f"{item.get('name') or ''} {item.get('content') or ''}".lower()
                if kw not in hay:
                    continue
            out.append(item)
        self.knowledge_model.set_items(self._knowledge_rows(out))

    # ---- 事实记忆 ----
    @Slot()
    def loadFacts(self) -> None:
        if self._page_loading:
            return
        self._page_loading = True
        self.stateChanged.emit()
        path = f"/api/memory/facts?user_id={self._current_user_id}"
        token = self.api.get("facts", path)
        self._pending[token] = ("facts", None)

    # ---- 检索 ----
    @Slot(str)
    def searchMemory(self, query: str) -> None:
        if self._page_loading:
            return
        self._page_loading = True
        self.stateChanged.emit()
        payload = {
            "user_id": self._current_user_id,
            "query": query,
            "context": {"scene": "chat", "task_type": "memory_demo"},
            "top_k": 10,
            "memory_types": ["preference", "knowledge", "fact"],
        }
        token = self.api.post("search", "/api/memory/search", payload)
        self._pending[token] = ("search", None)

    # ---- 冲突处理 ----
    @Slot()
    def loadConflicts(self) -> None:
        if self._page_loading:
            return
        self._page_loading = True
        self.stateChanged.emit()
        path = f"/api/memory/conflicts?user_id={self._current_user_id}"
        token = self.api.get("conflicts", path)
        self._pending[token] = ("conflicts", None)

    @Slot(str, str, str)
    def resolveConflict(self, conflict_id: str, decision: str, reason: str = "") -> None:
        path = f"/api/memory/conflicts/{conflict_id}/resolve"
        payload = {
            "user_id": self._current_user_id,
            "decision": decision,
            "reason": reason or "QML 客户端人工裁决",
        }
        token = self.api.post("resolve_conflict", path, payload)
        self._pending[token] = ("resolve_conflict", conflict_id)

    # ---- 遗忘管理 ----
    @Slot()
    def loadForgetHistory(self) -> None:
        if self._page_loading:
            return
        self._page_loading = True
        self.stateChanged.emit()
        path = f"/api/memory/forget/history?user_id={self._current_user_id}"
        token = self.api.get("forget_history", path)
        self._pending[token] = ("forget_history", None)

    @Slot(str)
    def applyForget(self, instruction: str) -> None:
        payload = {"user_id": self._current_user_id, "instruction": instruction, "cascade": True}
        token = self.api.post("forget", "/api/memory/forget", payload)
        self._pending[token] = ("forget", None)

    # ---- 安全规则 ----
    @Slot()
    def loadSafetyRules(self) -> None:
        if self._page_loading:
            return
        self._page_loading = True
        self.stateChanged.emit()
        path = "/api/memory/safety/user-rules"
        token = self.api.get("safety_rules", path)
        self._pending[token] = ("safety_rules", None)

    # ---- 评测报告 ----
    @Slot()
    def loadEvalReports(self) -> None:
        if self._page_loading:
            return
        self._page_loading = True
        self.stateChanged.emit()
        path = "/api/memory/evaluate/reports"
        token = self.api.get("eval_reports", path)
        self._pending[token] = ("eval_reports", None)

    @Slot(str)
    def clearPreferences(self, user_id: str = "") -> None:
        """清空指定用户（默认当前会话用户）的偏好记忆。"""
        uid = user_id or self._current_user_id
        path = f"/api/agent/preferences?user_id={uid}"
        token = self.api.delete("clear_preferences", path)
        self._pending[token] = ("clear_preferences", None)

    @Slot()
    def openApiDocs(self) -> None:
        QDesktopServices.openUrl(QUrl(f"{self.api.base_url}/docs"))

    @Slot(str)
    def selectSection(self, section: str) -> None:
        self._active_section = section
        labels = {
            "ingestion": "数据接入记录",
            "retrieval": "检索记录",
            "preferences": "偏好记忆",
            "facts": "事实记忆",
            "knowledge": "知识记忆",
            "conflicts": "冲突处理",
            "forget": "遗忘管理",
            "safety": "安全规则",
            "evaluation": "评测报告",
            "settings": "系统设置",
        }
        if section == "preferences":
            self.loadPreferences()
            self._set_notice("已加载偏好记忆。")
        elif section == "knowledge":
            self.loadKnowledge()
            self._set_notice("已加载知识记忆。")
        elif section == "facts":
            self.loadFacts()
            self._set_notice("已加载事实记忆。")
        elif section == "retrieval":
            self._set_notice("输入查询后点击检索，结果来自真实后端。")
        elif section == "conflicts":
            self.loadConflicts()
            self._set_notice("已加载冲突记录。")
        elif section == "forget":
            self.loadForgetHistory()
            self._set_notice("已加载遗忘历史。")
        elif section == "safety":
            self.loadSafetyRules()
            self._set_notice("已加载安全规则。")
        elif section == "evaluation":
            self.loadEvalReports()
            self._set_notice("已加载评测报告。")
        elif section != "agent":
            self._set_notice(f"已切换到{labels.get(section, '功能模块')}；详细管理页将继续复用当前后端接口。")
        self.stateChanged.emit()

    def _on_success(self, token: str, operation: str, body: Any) -> None:
        pending_operation, index = self._pending.pop(token, (operation, None))
        if pending_operation == "health":
            self._online = True
            self._status = "后端已连接"
            self.stateChanged.emit()
            return
        self._online = True
        self._busy = False
        self._status = "后端已连接"
        if pending_operation == "step" and index is not None and isinstance(body, dict):
            self._apply_step(index, body)
            # 底部提示同步展示本轮写入结果，避免用户靠“记忆活动”抽屉才能看到写入摘要
            summary = "；".join(self._write_summary) if self._write_summary else ""
            notice = f"第 {index + 1} 轮执行完成，展示内容来自真实后端。"
            if summary:
                notice += "\n" + summary
            self._set_notice(notice)
        elif pending_operation == "decision" and isinstance(body, dict):
            status = str(body.get("status") or "completed")
            proposal_id = str(body.get("proposal_id") or body.get("action_id") or "")
            self._update_fact_status(proposal_id, status)
            self.factDecisionFinished.emit(proposal_id, status)
            self._set_notice("事实裁决已交给 Agent 处理。")
        elif pending_operation == "preferences" and isinstance(body, list):
            self._preference_loading = False
            self.preference_model.set_items(self._preference_rows(body))
        elif pending_operation == "knowledge" and isinstance(body, list):
            self._knowledge_loading = False
            self._knowledge_data = [dict(item) for item in body]
            self.knowledge_model.set_items(self._knowledge_rows(self._knowledge_data))
        elif pending_operation == "facts" and isinstance(body, list):
            self._page_loading = False
            self.fact_model_page.set_items(self._facts_rows(body))
        elif pending_operation == "search" and isinstance(body, dict):
            self._page_loading = False
            self.retrieval_model.set_items(self._search_rows(body))
            self._set_notice(f"检索完成：{body.get('total_count', 0)} 条候选，{len(body.get('results', []))} 条命中。")
        elif pending_operation == "conflicts" and isinstance(body, list):
            self._page_loading = False
            self.conflict_model.set_items(self._conflict_rows(body))
        elif pending_operation == "resolve_conflict":
            self._page_loading = False
            self.loadConflicts()
            self._set_notice("冲突裁决已提交。")
        elif pending_operation == "forget_history" and isinstance(body, list):
            self._page_loading = False
            self.forget_model.set_items(self._forget_rows(body))
        elif pending_operation == "forget" and isinstance(body, dict):
            self._page_loading = False
            self.loadForgetHistory()
            self._set_notice(f"已遗忘 {body.get('deleted_count', 0)} 条记忆。")
        elif pending_operation == "safety_rules" and isinstance(body, list):
            self._page_loading = False
            self.safety_model.set_items(self._safety_rows(body))
        elif pending_operation == "eval_reports" and isinstance(body, list):
            self._page_loading = False
            self.eval_model.set_items(self._eval_rows(body))
        elif pending_operation == "clear_preferences":
            deleted = int(body.get("deleted", 0)) if isinstance(body, dict) else 0
            if deleted:
                self._set_notice(f"已清空 {deleted} 条偏好记忆，可重新执行演示。")
            self.loadPreferences()
            self.stateChanged.emit()
            return
        self.stateChanged.emit()

    def _on_failure(self, token: str, operation: str, status: int, message: str) -> None:
        pending_operation, _ = self._pending.pop(token, (operation, None))
        if pending_operation == "health" or status == 0:
            self._online = False
            self._status = "后端离线"
        if pending_operation == "preferences":
            self._preference_loading = False
        if pending_operation == "knowledge":
            self._knowledge_loading = False
        if pending_operation in {
            "facts",
            "search",
            "conflicts",
            "resolve_conflict",
            "forget_history",
            "forget",
            "safety_rules",
            "eval_reports",
        }:
            self._page_loading = False
        self._busy = False
        self._set_notice(f"请求失败：{message}")
        self.stateChanged.emit()

    def _apply_step(self, index: int, body: dict[str, Any]) -> None:
        turns = self._session.get("turns") or []
        if not 0 <= index < len(turns):
            return
        turn = turns[index]
        used_ids = {str(item) for item in body.get("used_memory_ids") or []}
        memories = []
        for raw in body.get("candidate_memories") or []:
            item = dict(mask_for_display(raw))
            item["used"] = str(item.get("memory_id") or "") in used_ids
            memories.append(item)
        backend_calls = [dict(mask_for_display(item)) for item in body.get("tool_calls") or []]
        calls = [*external_tool_calls(turn), *backend_calls]
        for sequence, call in enumerate(calls, 1):
            call["sequence"] = sequence
        turn.update(
            tool_calls=calls,
            candidate_memories=memories,
            used_memory_ids=list(used_ids),
            fact_proposals=[
                self._normalize_fact(item) for item in body.get("fact_proposals") or []
            ],
            write_summary=[str(item) for item in body.get("write_summary") or []],
            latency_ms=int(body.get("retrieval_latency_ms") or turn.get("latency_ms") or 0),
        )
        self._executed.add(index)
        self._write_summary = turn["write_summary"]
        self._last_latency_ms = turn["latency_ms"]
        self._refresh_models()

    @staticmethod
    def _normalize_fact(raw: Any) -> dict[str, Any]:
        item = dict(mask_for_display(raw)) if isinstance(raw, dict) else {}
        triple = item.get("raw_triple") if isinstance(item.get("raw_triple"), dict) else item
        admission = item.get("admission") if isinstance(item.get("admission"), dict) else {}
        return {
            "proposal_id": str(item.get("proposal_id") or item.get("candidate_id") or ""),
            "subject": str(triple.get("subject_text") or item.get("subject") or ""),
            "predicate": str(triple.get("predicate_text") or item.get("predicate") or ""),
            "object": str(triple.get("object_text") or item.get("object") or ""),
            "evidence": str(triple.get("evidence") or item.get("evidence") or ""),
            "confidence": float(
                triple.get("confidence")
                or admission.get("confidence")
                or item.get("confidence")
                or 0
            ),
            "admission_reason": str(
                admission.get("reason") or item.get("admission_reason") or "满足事实候选准入条件"
            ),
            "suggested_scope": str(
                admission.get("suggested_scope")
                or item.get("scope_hint")
                or item.get("suggested_scope")
                or "project"
            ),
            "status": str(item.get("status") or "proposed"),
        }

    def _update_fact_status(self, proposal_id: str, status: str) -> None:
        turns = self._session.get("turns") or []
        for turn in turns:
            for proposal in turn.get("fact_proposals") or []:
                if proposal.get("proposal_id") == proposal_id:
                    proposal["status"] = status
        self._refresh_models()

    def _refresh_models(self) -> None:
        turns = self._session.get("turns") or []
        self.turn_model.set_items(
            {
                "turnId": turn.get("turn_id", ""),
                "number": index + 1,
                "preview": str(turn.get("user_message") or "")[:28],
                "state": "done"
                if index in self._executed
                else ("current" if index == self._index else "waiting"),
                "selected": index == self._index,
            }
            for index, turn in enumerate(turns)
        )
        messages = []
        for index, turn in enumerate(turns):
            if index > self._index:
                break
            messages.append(
                {
                    "speaker": "user",
                    "body": turn.get("user_message", ""),
                    "turnId": turn.get("turn_id", ""),
                    "occurredAt": turn.get("occurred_at", ""),
                    "pending": False,
                }
            )
            if index in self._executed:
                messages.append(
                    {
                        "speaker": "assistant",
                        "body": turn.get("assistant_message", ""),
                        "turnId": turn.get("turn_id", ""),
                        "occurredAt": turn.get("occurred_at", ""),
                        "pending": False,
                    }
                )
            elif index == self._index:
                messages.append(
                    {
                        "speaker": "assistant",
                        "body": "执行本轮后显示 Agent 回复",
                        "turnId": turn.get("turn_id", ""),
                        "occurredAt": "",
                        "pending": True,
                    }
                )
        self.message_model.set_items(messages)
        turn = turns[self._index] if turns else {}
        executed = self._index in self._executed
        self.tool_model.set_items(self._tool_rows(turn.get("tool_calls") or []) if executed else [])
        self.memory_model.set_items(
            self._memory_rows(turn.get("candidate_memories") or []) if executed else []
        )
        self.fact_model.set_items(
            self._fact_rows(turn.get("fact_proposals") or []) if executed else []
        )
        self._write_summary = turn.get("write_summary") or [] if executed else []
        self._last_latency_ms = int(turn.get("latency_ms") or 0) if executed else 0
        self.stateChanged.emit()

    @staticmethod
    def _tool_rows(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "callId": str(call.get("call_id") or ""),
                "toolName": str(call.get("tool_name") or "unknown_tool"),
                "status": str(call.get("status") or "success"),
                "sequence": int(call.get("sequence") or index + 1),
                "latencyMs": int(call.get("latency_ms") or 0),
                "argumentsJson": json.dumps(
                    call.get("arguments") or {}, ensure_ascii=False, indent=2
                ),
                "resultJson": json.dumps(call.get("result") or {}, ensure_ascii=False, indent=2),
                "error": str(call.get("error") or ""),
            }
            for index, call in enumerate(calls)
        ]

    @staticmethod
    def _preference_rows(prefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for p in prefs:
            scope = p.get("scope")
            if not isinstance(scope, dict):
                scope = {}
            scope_text = " / ".join(
                part for part in (str(scope.get("scene") or ""), str(scope.get("task_type") or "")) if part
            )
            if not scope_text:
                scope_text = "全局" if p.get("is_global") else "global"
            rows.append(
                {
                    "memoryId": str(p.get("memory_id") or ""),
                    "preferenceType": str(p.get("preference_type") or "other"),
                    "content": str(p.get("text") or p.get("content") or ""),
                    "confidence": float(p.get("confidence") or 0),
                    "scopeText": scope_text,
                    "status": str(p.get("status") or "active"),
                    "level": str(p.get("level") or ""),
                    "version": int(p.get("version") or 1),
                    "createdAt": str(p.get("created_at") or "")[:10],
                    "updatedAt": str(p.get("updated_at") or "")[:10],
                    "evidenceCount": len(p.get("evidences") or []),
                    "tagsText": " · ".join(str(t) for t in p.get("tags") or []),
                    "evidenceJson": json.dumps(
                        p.get("evidences") or [], ensure_ascii=False, indent=2
                    ),
                }
            )
        return rows

    @staticmethod
    def _knowledge_rows(knows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for k in knows:
            scope = k.get("scope")
            if not isinstance(scope, dict):
                scope = {}
            scope_text = " / ".join(
                part
                for part in (str(scope.get("scene") or ""), str(scope.get("task_type") or ""))
                if part
            )
            if not scope_text:
                scope_text = "全局" if k.get("is_global") else "global"
            s = int(k.get("success_count") or 0)
            t = int(k.get("total_count") or 0)
            rows.append(
                {
                    "memoryId": str(k.get("memory_id") or ""),
                    "knowledgeType": str(k.get("knowledge_type") or "workflow"),
                    "name": str(k.get("name") or ""),
                    "content": str(k.get("content") or ""),
                    "confidence": float(k.get("confidence") or 0),
                    "successRate": f"{s}/{t}" if t > 0 else "—",
                    "status": str(k.get("status") or "active"),
                    "level": str(k.get("level") or ""),
                    "version": int(k.get("version") or 1),
                    "createdAt": str(k.get("created_at") or "")[:10],
                    "scopeText": scope_text,
                    "steps": [str(x) for x in k.get("steps") or []],
                    "tools": [str(x) for x in k.get("tools") or []],
                    "toolsText": " · ".join(str(x) for x in k.get("tools") or []),
                    "evidenceCount": len(k.get("evidences") or []),
                }
            )
        return rows

    @staticmethod
    def _facts_rows(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for f in facts:
            rows.append(
                {
                    "factId": str(f.get("fact_id") or f.get("memory_id") or ""),
                    "subject": str(f.get("subject_id") or ""),
                    "predicate": str(f.get("predicate_id") or ""),
                    "objectValue": str(f.get("object_value") or ""),
                    "sourceText": str(f.get("source_text") or ""),
                    "confidence": float(f.get("confidence") or 0),
                    "status": str(f.get("status") or "active"),
                    "scope": str(f.get("scope") or "global"),
                    "projectId": str(f.get("project_id") or "") or "—",
                    "createdAt": str(f.get("created_at") or "")[:10],
                }
            )
        return rows

    @staticmethod
    def _search_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for r in body.get("results") or []:
            rows.append(
                {
                    "memoryId": str(r.get("memory_id") or ""),
                    "memoryType": str(r.get("memory_type") or ""),
                    "content": str(r.get("content") or ""),
                    "score": float(r.get("score") or 0),
                    "source": str(r.get("source") or ""),
                }
            )
        return rows

    @staticmethod
    def _conflict_rows(conf: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for c in conf:
            rows.append(
                {
                    "conflictId": str(c.get("conflict_id") or ""),
                    "oldContent": str(c.get("old_content") or ""),
                    "newContent": str(c.get("new_content") or ""),
                    "memoryType": str(c.get("memory_type") or ""),
                    "decision": str(c.get("decision") or "pending"),
                    "reason": str(c.get("reason") or ""),
                    "createdAt": str(c.get("created_at") or "")[:16],
                }
            )
        return rows

    @staticmethod
    def _forget_rows(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for r in recs:
            rows.append(
                {
                    "recordId": str(r.get("record_id") or ""),
                    "instruction": str(r.get("instruction") or ""),
                    "deletedCount": int(r.get("deleted_count") or 0),
                    "createdAt": str(r.get("created_at") or "")[:16],
                }
            )
        return rows

    @staticmethod
    def _safety_rows(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for r in rules:
            rows.append(
                {
                    "ruleId": str(r.get("rule_id") or ""),
                    "label": str(r.get("label") or ""),
                    "kind": str(r.get("kind") or ""),
                    "effect": str(r.get("effect") or ""),
                    "enabled": bool(r.get("enabled", True)),
                    "revision": int(r.get("revision") or 1),
                    "createdAt": str(r.get("created_at") or "")[:10],
                }
            )
        return rows

    @staticmethod
    def _eval_rows(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for r in reports:
            rows.append(
                {
                    "taskName": str(r.get("task_name") or ""),
                    "totalSamples": int(r.get("total_samples") or 0),
                    "accuracy": float(r.get("accuracy") or 0),
                    "f1": float(r.get("f1") or 0),
                    "avgLatencyMs": float(r.get("avg_latency_ms") or 0),
                }
            )
        return rows

    @staticmethod
    def _memory_rows(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for item in memories:
            scope = item.get("scope")
            if isinstance(scope, dict):
                scope = scope.get("project_id") or scope.get("scene") or "global"
            rows.append(
                {
                    "memoryId": str(item.get("memory_id") or ""),
                    "memoryType": str(item.get("memory_type") or "knowledge"),
                    "knowledgeType": str(item.get("knowledge_type") or ""),
                    "title": str(item.get("title") or "记忆"),
                    "summary": str(item.get("summary") or ""),
                    "relevance": float(item.get("relevance") or 0),
                    "source": str(item.get("source") or "MemoryHub"),
                    "level": str(item.get("level") or "long"),
                    "scope": str(scope or "global"),
                    "tagsText": " · ".join(str(tag) for tag in item.get("tags") or []),
                    "used": bool(item.get("used")),
                }
            )
        return rows

    @staticmethod
    def _fact_rows(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "proposalId": item.get("proposal_id", ""),
                "subject": item.get("subject", ""),
                "predicate": item.get("predicate", ""),
                "objectValue": item.get("object", ""),
                "evidence": item.get("evidence", ""),
                "confidence": float(item.get("confidence") or 0),
                "admissionReason": item.get("admission_reason", ""),
                "suggestedScope": item.get("suggested_scope", "project"),
                "status": item.get("status", "proposed"),
            }
            for item in facts
        ]

    def _set_notice(self, value: str) -> None:
        self._notice = value
        self.noticeChanged.emit()
        self._notice_timer.start()

    def _clear_notice(self) -> None:
        if self._notice:
            self._notice = ""
            self.noticeChanged.emit()
