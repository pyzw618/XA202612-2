from __future__ import annotations

import json
import os
import uuid
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


class MemoryHubApi(QObject):
    succeeded = Signal(str, str, object)
    failed = Signal(str, str, int, str)

    def __init__(self, base_url: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = (
            base_url or os.environ.get("MEMORYHUB_BACKEND_URL") or "http://127.0.0.1:8000"
        ).rstrip("/")
        self.manager = QNetworkAccessManager(self)

    def health(self) -> str:
        return self._send("health", "GET", "/api/health")

    def post(self, operation: str, path: str, payload: dict[str, Any]) -> str:
        return self._send(operation, "POST", path, payload)

    def _send(
        self, operation: str, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> str:
        token = uuid.uuid4().hex
        request = QNetworkRequest(QUrl(f"{self.base_url}{path}"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setTransferTimeout(15_000)
        if method == "GET":
            reply = self.manager.get(request)
        else:
            body = QByteArray(json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"))
            reply = self.manager.post(request, body)
        reply.setProperty("memoryhub_token", token)
        reply.setProperty("memoryhub_operation", operation)
        reply.finished.connect(lambda current=reply: self._finish(current))
        return token

    def _finish(self, reply: QNetworkReply) -> None:
        token = str(reply.property("memoryhub_token"))
        operation = str(reply.property("memoryhub_operation"))
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status_code = int(status) if status is not None else 0
        raw = bytes(reply.readAll())
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}

        if reply.error() == QNetworkReply.NetworkError.NoError and 200 <= status_code < 300:
            self.succeeded.emit(token, operation, body)
        else:
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, list):
                detail = "; ".join(
                    str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                    for item in detail
                )
            message = str(detail or reply.errorString() or f"请求失败 ({status_code})")
            self.failed.emit(token, operation, status_code, message)
        reply.deleteLater()
