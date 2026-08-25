"""Gated vNext rollout and reversible read-path rollback controller."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memoryhub.config import VNextConfig


class RolloutGateError(RuntimeError):
    """A rollout level has not met its observation or safety gate."""


LEVELS = (0, 5, 25, 50, 100)


class RolloutRepository:
    """SQLite adapter for rollout-only state and redacted audit data."""

    STATE_ID = "default"

    def __init__(self, db: Any) -> None:
        self.db = db

    def load(self) -> tuple[Any | None, list[Any], list[Any]]:
        from memoryhub.storage.models import (
            RolloutAuditRow,
            RolloutObservationRow,
            RolloutStateRow,
        )

        with self.db.session() as session:
            state_row = session.get(RolloutStateRow, self.STATE_ID)
            state = (
                {
                    "current_level": state_row.current_level,
                    "current_mode": state_row.current_mode,
                    "rollback_window_minutes": state_row.rollback_window_minutes,
                }
                if state_row is not None
                else None
            )
            observations = session.query(RolloutObservationRow).order_by(
                RolloutObservationRow.level.asc(),
                RolloutObservationRow.observed_at.asc(),
            ).all()
            observation_data = [
                {
                    "level": row.level,
                    "window_id": row.window_id,
                    "request_count": row.request_count,
                    "policy_leak_count": row.policy_leak_count,
                    "cross_tenant_count": row.cross_tenant_count,
                    "forget_residual_count": row.forget_residual_count,
                    "error_count": row.error_count,
                    "observed_at": row.observed_at,
                }
                for row in observations
            ]
            audits = session.query(RolloutAuditRow).order_by(
                RolloutAuditRow.recorded_at.asc()
            ).all()
            audit_data = [
                {
                    "audit_id": row.audit_id,
                    "action": row.action,
                    "previous_level": row.previous_level,
                    "next_level": row.next_level,
                    "previous_mode": row.previous_mode,
                    "next_mode": row.next_mode,
                    "window_id": row.window_id,
                    "reason": row.reason,
                    "rollback_window_minutes": row.rollback_window_minutes,
                    "metrics": dict(row.metrics or {}),
                    "recorded_at": row.recorded_at,
                }
                for row in audits
            ]
            return state, observation_data, audit_data

    def save_state(self, *, level: int, mode: str, rollback_window_minutes: int) -> None:
        from datetime import datetime

        from memoryhub.storage.models import RolloutStateRow

        with self.db.session() as session:
            row = session.get(RolloutStateRow, self.STATE_ID)
            if row is None:
                row = RolloutStateRow(state_id=self.STATE_ID)
                session.add(row)
            row.current_level = level
            row.current_mode = mode
            row.rollback_window_minutes = rollback_window_minutes
            row.updated_at = datetime.now()

    def save_observation(self, observation: "RolloutObservation") -> None:
        from datetime import datetime

        from memoryhub.storage.models import RolloutObservationRow

        with self.db.session() as session:
            row = session.get(RolloutObservationRow, observation.window_id)
            if row is None:
                row = RolloutObservationRow(window_id=observation.window_id)
                session.add(row)
            row.level = observation.level
            row.request_count = observation.request_count
            row.policy_leak_count = observation.policy_leak_count
            row.cross_tenant_count = observation.cross_tenant_count
            row.forget_residual_count = observation.forget_residual_count
            row.error_count = observation.error_count
            row.observed_at = datetime.fromisoformat(observation.observed_at)

    def save_audit(self, audit: "RolloutAudit") -> None:
        from datetime import datetime

        from memoryhub.storage.models import RolloutAuditRow

        with self.db.session() as session:
            session.add(
                RolloutAuditRow(
                    audit_id=audit.audit_id,
                    action=audit.action,
                    previous_level=audit.previous_level,
                    next_level=audit.next_level,
                    previous_mode=audit.previous_mode,
                    next_mode=audit.next_mode,
                    window_id=audit.window_id,
                    reason=audit.reason,
                    rollback_window_minutes=audit.rollback_window_minutes,
                    metrics=audit.metrics,
                    recorded_at=datetime.fromisoformat(audit.recorded_at),
                )
            )


@dataclass(frozen=True, slots=True)
class RolloutObservation:
    level: int
    window_id: str
    request_count: int
    policy_leak_count: int = 0
    cross_tenant_count: int = 0
    forget_residual_count: int = 0
    error_count: int = 0
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def passed(self) -> bool:
        return (
            self.request_count >= 1
            and self.policy_leak_count == 0
            and self.cross_tenant_count == 0
            and self.forget_residual_count == 0
            and self.error_count == 0
        )

    @property
    def cross_tenant_leak_count(self) -> int:
        """Compatibility alias used by safety-gate callers."""
        return self.cross_tenant_count


@dataclass(frozen=True, slots=True)
class RolloutAudit:
    audit_id: str
    action: str
    previous_level: int
    next_level: int
    previous_mode: str
    next_mode: str
    window_id: str
    reason: str
    rollback_window_minutes: int
    metrics: dict[str, int]
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RolloutController:
    """Advance only through observed safe levels and preserve rollback evidence."""

    def __init__(
        self,
        config: VNextConfig | None = None,
        *,
        db: Any | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self.config = config or VNextConfig()
        self._repository = RolloutRepository(db) if db is not None else None
        self._state_path = Path(state_path) if state_path is not None else None
        self._lock = threading.RLock()
        self.current_level = self._configured_level()
        self.current_mode = self.config.mode
        self._observations: dict[int, RolloutObservation] = {}
        self._audits: list[RolloutAudit] = []
        self._restore()

    @property
    def audits(self) -> list[RolloutAudit]:
        return list(self._audits)

    @property
    def observations(self) -> list[RolloutObservation]:
        return list(self._observations.values())

    def observe(
        self,
        level: int,
        *,
        request_count: int,
        policy_leak_count: int = 0,
        cross_tenant_count: int = 0,
        forget_residual_count: int = 0,
        error_count: int = 0,
        window_id: str | None = None,
        allow_baseline: bool = False,
    ) -> RolloutObservation:
        self._validate_level(level)
        if level == 0 and not allow_baseline:
            raise RolloutGateError("level 0 is the rollback baseline, not a canary window")
        counters = (request_count, policy_leak_count, cross_tenant_count,
                    forget_residual_count, error_count)
        if any(type(value) is not int or value < 0 for value in counters):
            raise RolloutGateError("rollout observation counters must be non-negative integers")
        with self._lock:
            previous = self._observations.get(level)
            selected_window = window_id or (previous.window_id if previous else None)
            if previous is not None and (window_id is None or window_id == previous.window_id):
                observation = RolloutObservation(
                    level=level,
                    window_id=previous.window_id,
                    request_count=previous.request_count + request_count,
                    policy_leak_count=previous.policy_leak_count + policy_leak_count,
                    cross_tenant_count=previous.cross_tenant_count + cross_tenant_count,
                    forget_residual_count=previous.forget_residual_count + forget_residual_count,
                    error_count=previous.error_count + error_count,
                )
            else:
                observation = RolloutObservation(
                    level=level,
                    window_id=selected_window or f"window-{level}-{uuid.uuid4().hex[:8]}",
                    request_count=request_count,
                    policy_leak_count=policy_leak_count,
                    cross_tenant_count=cross_tenant_count,
                    forget_residual_count=forget_residual_count,
                    error_count=error_count,
                )
            self._observations[level] = observation
            self._persist_observation(observation)
        return observation

    def advance(self, level: int) -> RolloutAudit:
        self._validate_level(level)
        try:
            expected = LEVELS[LEVELS.index(self.current_level) + 1]
        except (ValueError, IndexError) as exc:
            raise RolloutGateError("rollout is already at the maximum level") from exc
        if level != expected:
            raise RolloutGateError(f"rollout must advance from {self.current_level} to {expected}")
        observation = self._observations.get(level)
        if observation is None:
            raise RolloutGateError(f"level {level} has no observation window")
        if observation.request_count < self.config.observation_window_requests:
            raise RolloutGateError(
                f"level {level} requires "
                f"{self.config.observation_window_requests} observed requests"
            )
        if not observation.passed:
            raise RolloutGateError(f"level {level} failed a zero-tolerance safety gate")
        next_mode = "vnext" if level == 100 else "canary"
        audit = self._record(
            action="CUTOVER",
            previous_level=self.current_level,
            next_level=level,
            previous_mode=self.current_mode,
            next_mode=next_mode,
            window_id=observation.window_id,
            reason="observation_window_passed",
            observation=observation,
        )
        with self._lock:
            self.current_level = level
            self.current_mode = next_mode
            self._persist_state()
        return audit

    def rollback(self, *, reason: str, target_level: int = 0) -> RolloutAudit:
        self._validate_level(target_level)
        if target_level >= self.current_level:
            raise RolloutGateError("rollback target must be below current rollout level")
        next_mode = "legacy" if target_level == 0 else "canary"
        observation = self._observations.get(self.current_level)
        audit = self._record(
            action="ROLLBACK",
            previous_level=self.current_level,
            next_level=target_level,
            previous_mode=self.current_mode,
            next_mode=next_mode,
            window_id=observation.window_id if observation else "rollback-window",
            reason=reason,
            observation=observation,
        )
        with self._lock:
            self.current_level = target_level
            self.current_mode = next_mode
            self._persist_state()
        return audit

    def choose_vnext(self, request: Any) -> bool:
        """Choose canary traffic deterministically by tenant/user identity."""
        if self.current_mode in {"vnext"}:
            return True
        if self.current_mode != "canary":
            return False
        percent = self.current_level or self.config.canary_percent
        if percent <= 0:
            return False
        tenant_id = str(getattr(request, "tenant_id", ""))
        user_id = str(getattr(request, "user_id", ""))
        bucket = int.from_bytes(
            __import__("hashlib").sha256(f"{tenant_id}:{user_id}".encode()).digest()[:8],
            "big",
        ) % 100
        return bucket < percent

    def record_read_observation(self, report: Any) -> RolloutObservation | None:
        """Convert a redacted read comparison into the active window counters."""
        if self.current_level <= 0:
            level = 0
        else:
            level = self.current_level
        differences = getattr(report, "differences", ())
        return self.observe(
            level,
            request_count=1,
            policy_leak_count=int(getattr(report, "policy_leak_count", 0)),
            cross_tenant_count=int(getattr(report, "cross_tenant_count", 0)),
            forget_residual_count=int(getattr(report, "forget_leak_count", 0)),
            error_count=int(bool(getattr(report, "vnext_error", "")))
            + sum(1 for item in differences if getattr(item, "kind", "") == "OBSERVATION_ERROR"),
            allow_baseline=level == 0,
        )

    def rollback_window_active(self, *, now: datetime | None = None) -> bool:
        if not self._audits:
            return False
        last = self._audits[-1]
        if last.action != "CUTOVER":
            return False
        recorded = datetime.fromisoformat(last.recorded_at)
        return (now or datetime.now(timezone.utc)) <= recorded + timedelta(
            minutes=self.config.rollback_window_minutes
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_level": self.current_level,
            "current_mode": self.current_mode,
            "rollback_window_minutes": self.config.rollback_window_minutes,
            "observations": [asdict(item) for item in self.observations],
            "audits": [asdict(item) for item in self._audits],
            "redacted": True,
            "authority_mutations": 0,
        }

    def write_snapshot(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _configured_level(self) -> int:
        if self.config.mode == "canary":
            return self.config.canary_percent
        if self.config.mode == "vnext":
            return 100
        return 0

    def _restore(self) -> None:
        if self._repository is not None:
            state, observations, audits = self._repository.load()
            if state is not None:
                self.current_level = int(state["current_level"])
                self.current_mode = str(state["current_mode"])
                self.config.rollback_window_minutes = int(
                    state["rollback_window_minutes"]
                )
            self._observations = {
                int(row["level"]): RolloutObservation(
                    level=int(row["level"]), window_id=row["window_id"],
                    request_count=int(row["request_count"]),
                    policy_leak_count=int(row["policy_leak_count"]),
                    cross_tenant_count=int(row["cross_tenant_count"]),
                    forget_residual_count=int(row["forget_residual_count"]),
                    error_count=int(row["error_count"]),
                    observed_at=row["observed_at"].replace(tzinfo=timezone.utc).isoformat(),
                ) for row in observations
            }
            self._audits = [
                RolloutAudit(
                    audit_id=row["audit_id"], action=row["action"],
                    previous_level=int(row["previous_level"]), next_level=int(row["next_level"]),
                    previous_mode=row["previous_mode"], next_mode=row["next_mode"],
                    window_id=row["window_id"], reason=row["reason"],
                    rollback_window_minutes=int(row["rollback_window_minutes"]),
                    metrics=dict(row["metrics"] or {}),
                    recorded_at=row["recorded_at"].replace(tzinfo=timezone.utc).isoformat(),
                ) for row in audits
            ]
        elif self._state_path is not None and self._state_path.exists():
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.current_level = int(data.get("current_level", self.current_level))
            self.current_mode = str(data.get("current_mode", self.current_mode))
            self._observations = {
                int(item["level"]): RolloutObservation(**item)
                for item in data.get("observations", [])
            }
            self._audits = [RolloutAudit(**item) for item in data.get("audits", [])]

    def _persist_state(self) -> None:
        if self._repository is not None:
            self._repository.save_state(
                level=self.current_level,
                mode=self.current_mode,
                rollback_window_minutes=self.config.rollback_window_minutes,
            )
        if self._state_path is not None:
            self.write_snapshot(self._state_path)

    def _persist_observation(self, observation: RolloutObservation) -> None:
        if self._repository is not None:
            self._repository.save_observation(observation)
        if self._state_path is not None:
            self.write_snapshot(self._state_path)

    @staticmethod
    def _validate_level(level: int) -> None:
        if level not in LEVELS:
            raise RolloutGateError("rollout level must be one of 0, 5, 25, 50, 100")

    def _record(
        self,
        *,
        action: str,
        previous_level: int,
        next_level: int,
        previous_mode: str,
        next_mode: str,
        window_id: str,
        reason: str,
        observation: RolloutObservation | None,
    ) -> RolloutAudit:
        metrics = {
            "request_count": observation.request_count if observation else 0,
            "policy_leak_count": observation.policy_leak_count if observation else 0,
            "cross_tenant_count": observation.cross_tenant_count if observation else 0,
            "forget_residual_count": observation.forget_residual_count if observation else 0,
            "error_count": observation.error_count if observation else 0,
        }
        audit = RolloutAudit(
            audit_id=f"rollout-{uuid.uuid4().hex}",
            action=action,
            previous_level=previous_level,
            next_level=next_level,
            previous_mode=previous_mode,
            next_mode=next_mode,
            window_id=window_id,
            reason=reason,
            rollback_window_minutes=self.config.rollback_window_minutes,
            metrics=metrics,
        )
        self._audits.append(audit)
        if self._repository is not None:
            self._repository.save_audit(audit)
        if self._state_path is not None:
            self.write_snapshot(self._state_path)
        return audit


__all__ = [
    "LEVELS", "RolloutAudit", "RolloutController", "RolloutGateError",
    "RolloutObservation", "RolloutRepository",
]
