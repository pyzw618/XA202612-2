"""Gated vNext rollout and reversible read-path rollback controller."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memoryhub.config import VNextConfig


class RolloutGateError(RuntimeError):
    """A rollout level has not met its observation or safety gate."""


LEVELS = (0, 5, 25, 50, 100)


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

    def __init__(self, config: VNextConfig | None = None) -> None:
        self.config = config or VNextConfig()
        self.current_level = 0
        self.current_mode = "legacy"
        self._observations: dict[int, RolloutObservation] = {}
        self._audits: list[RolloutAudit] = []

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
    ) -> RolloutObservation:
        self._validate_level(level)
        if level == 0:
            raise RolloutGateError("level 0 is the rollback baseline, not a canary window")
        observation = RolloutObservation(
            level=level,
            window_id=window_id or f"window-{level}-{uuid.uuid4().hex[:8]}",
            request_count=request_count,
            policy_leak_count=policy_leak_count,
            cross_tenant_count=cross_tenant_count,
            forget_residual_count=forget_residual_count,
            error_count=error_count,
        )
        self._observations[level] = observation
        return observation

    def advance(self, level: int) -> RolloutAudit:
        self._validate_level(level)
        expected = LEVELS[LEVELS.index(self.current_level) + 1]
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
        self.current_level = level
        self.current_mode = next_mode
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
        self.current_level = target_level
        self.current_mode = next_mode
        return audit

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
        return audit


__all__ = ["LEVELS", "RolloutAudit", "RolloutController", "RolloutGateError", "RolloutObservation"]
