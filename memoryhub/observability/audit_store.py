"""Durable, redacted audit records for management and observability access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from memoryhub.observability.trace_policy import assert_redacted
from memoryhub.storage.models import ObservabilityAuditRow


class AuditStore:
    """Write-only-by-default audit helper; all details are recursively checked."""

    def __init__(self, db=None) -> None:
        self.db = db
        self._records: list[dict[str, Any]] = []

    def record(
        self,
        *,
        action: str,
        tenant_id: str,
        user_id: str,
        actor_id: str,
        category: str = "MANAGEMENT",
        status: str = "SUCCEEDED",
        trace_id: str | None = None,
        task_id: str | None = None,
        event_id: str | None = None,
        memory_id: str | None = None,
        query_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        retention_class: str = "ELEVATED",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        safe_details = dict(details or {})
        assert_redacted(safe_details)
        created_at = datetime.now(timezone.utc)
        if expires_at is None:
            expires_at = created_at + timedelta(days=30)
        item = {
            "audit_id": "audit_" + uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "actor_id": actor_id,
            "action": action,
            "category": category,
            "status": status,
            "trace_id": trace_id,
            "task_id": task_id,
            "event_id": event_id,
            "memory_id": memory_id,
            "query_id": query_id,
            "target_type": target_type,
            "target_id": target_id,
            "details": safe_details,
            "redacted": True,
            "retention_class": retention_class,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        if self.db is None:
            self._records.append(item)
        else:
            with self.db.session() as session:
                session.add(ObservabilityAuditRow(**item))
        return item

    def list_for_tenant(
        self, tenant_id: str, *, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self.db is None:
            records = self._records
        else:
            with self.db.session() as session:
                query = session.query(ObservabilityAuditRow).filter_by(tenant_id=tenant_id)
                if user_id is not None:
                    query = query.filter_by(user_id=user_id)
                rows = query.order_by(
                    ObservabilityAuditRow.created_at, ObservabilityAuditRow.audit_id
                ).all()
                return [self._row_to_dict(row) for row in rows]
        return [
            dict(item)
            for item in records
            if item["tenant_id"] == tenant_id and (user_id is None or item["user_id"] == user_id)
        ]

    def list_by(
        self, field: str, value: str, *, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        allowed = {"trace_id", "task_id", "event_id", "memory_id", "query_id"}
        if field not in allowed:
            raise ValueError(f"unsupported_audit_index:{field}")
        if self.db is None:
            return [
                dict(item)
                for item in self._records
                if item.get(field) == value
                and (tenant_id is None or item["tenant_id"] == tenant_id)
            ]
        with self.db.session() as session:
            column = getattr(ObservabilityAuditRow, field)
            query = session.query(ObservabilityAuditRow).filter(column == value)
            if tenant_id is not None:
                query = query.filter(ObservabilityAuditRow.tenant_id == tenant_id)
            rows = query.order_by(ObservabilityAuditRow.created_at).all()
            return [self._row_to_dict(row) for row in rows]

    def purge_expired(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        if self.db is None:
            before = len(self._records)
            self._records = [
                item for item in self._records
                if item["expires_at"] is None or item["expires_at"] > now
            ]
            return before - len(self._records)
        with self.db.session() as session:
            return int(
                session.query(ObservabilityAuditRow).filter(
                    ObservabilityAuditRow.expires_at.is_not(None),
                    ObservabilityAuditRow.expires_at <= now,
                ).delete(synchronize_session=False)
            )

    @staticmethod
    def _row_to_dict(row: ObservabilityAuditRow) -> dict[str, Any]:
        return {
            "audit_id": row.audit_id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "actor_id": row.actor_id,
            "action": row.action,
            "category": row.category,
            "status": row.status,
            "trace_id": row.trace_id,
            "task_id": row.task_id,
            "event_id": row.event_id,
            "memory_id": row.memory_id,
            "query_id": row.query_id,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "details": dict(row.details or {}),
            "redacted": bool(row.redacted),
            "retention_class": row.retention_class,
            "created_at": row.created_at,
            "expires_at": row.expires_at,
        }


__all__ = ["AuditStore"]
