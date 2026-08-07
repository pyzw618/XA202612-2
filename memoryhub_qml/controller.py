from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .api import MemoryHubApi
from .models import (
    FactProposalListModel,
    MemoryListModel,
    MessageListModel,
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

        self.turn_model = TurnListModel(self)
        self.message_model = MessageListModel(self)
        self.tool_model = ToolCallListModel(self)
        self.memory_model = MemoryListModel(self)
        self.fact_model = FactProposalListModel(self)

        self.api.succeeded.connect(self._on_success)
        self.api.failed.connect(self._on_failure)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(5_000)
        self._health_timer.timeout.connect(self.retryBackend)

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
    def openApiDocs(self) -> None:
        QDesktopServices.openUrl(QUrl(f"{self.api.base_url}/docs"))

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
            self._set_notice(f"第 {index + 1} 轮执行完成，展示内容来自真实后端。")
        elif pending_operation == "decision" and isinstance(body, dict):
            status = str(body.get("status") or "completed")
            proposal_id = str(body.get("proposal_id") or body.get("action_id") or "")
            self._update_fact_status(proposal_id, status)
            self.factDecisionFinished.emit(proposal_id, status)
            self._set_notice("事实裁决已交给 Agent 处理。")
        self.stateChanged.emit()

    def _on_failure(self, token: str, operation: str, status: int, message: str) -> None:
        pending_operation, _ = self._pending.pop(token, (operation, None))
        if pending_operation == "health" or status == 0:
            self._online = False
            self._status = "后端离线"
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
