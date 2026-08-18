"""LifecycleScheduler：周期性执行记忆分层流转（session→mid→long + 降级 + 生命周期检查）。

参照 storage/compensation_task.py 的后台线程模式（REFACTOR_PLAN_V2 §4.4.2）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SchedulerMetrics:
    total_runs: int = 0
    last_run_at: str = ""
    last_duration_ms: float = 0.0
    last_result: dict = field(default_factory=dict)
    last_error: str = ""


class LifecycleScheduler:
    """后台线程周期调用 run_consolidation_cycle()。"""

    def __init__(
        self,
        *,
        session_consolidator,
        memory_consolidator,
        memory_degrader,
        lifecycle_manager,
        interval_seconds: float = 300.0,
        enabled: bool = True,
    ):
        self.session_consolidator = session_consolidator
        self.memory_consolidator = memory_consolidator
        self.memory_degrader = memory_degrader
        self.lifecycle_manager = lifecycle_manager
        self.interval_seconds = max(5.0, float(interval_seconds))
        self.enabled = enabled
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._metrics = SchedulerMetrics()

    @property
    def metrics(self) -> SchedulerMetrics:
        with self._lock:
            return SchedulerMetrics(**self._metrics.__dict__)

    def run_consolidation_cycle(self) -> dict:
        """执行一轮完整的分层流转，返回统计。"""
        result: dict = {}
        try:
            result["sessions_consolidated"] = self.session_consolidator.consolidate_sessions()
            result["episodes_consolidated"] = self.memory_consolidator.consolidate_episodes()
            result["tool_preferences"] = self.memory_consolidator.consolidate_tool_preferences()
            if self.memory_degrader is not None:
                result["degraded"] = self.memory_degrader.degrade_low_health()
            if self.lifecycle_manager is not None:
                result["lifecycle"] = self.lifecycle_manager.run_lifecycle_check()
            logger.info("lifecycle cycle: %s", result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("lifecycle consolidation cycle failed")
            result["error"] = str(exc)
        return result

    def _loop(self) -> None:
        logger.info("lifecycle scheduler started (interval=%ss)", self.interval_seconds)
        while not self._stop_event.wait(self.interval_seconds):
            started = time.perf_counter()
            result = self.run_consolidation_cycle()
            with self._lock:
                self._metrics.total_runs += 1
                self._metrics.last_result = result
                self._metrics.last_duration_ms = round((time.perf_counter() - started) * 1000, 2)
                self._metrics.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
                if "error" in result:
                    self._metrics.last_error = result["error"]
        logger.info("lifecycle scheduler stopped")

    def start(self) -> None:
        if not self.enabled:
            logger.info("lifecycle scheduler is disabled")
            return
        if self._thread is not None and self._thread.is_alive():
            logger.warning("lifecycle scheduler already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="lifecycle_scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
