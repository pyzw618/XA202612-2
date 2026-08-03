"""
pending_index 异步补偿任务

定时扫描 SQLite 中 pending_index=True 的记录，尝试重新生成 embedding
并 upsert 到 Milvus；成功后标记为已同步并失效相关缓存。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memoryhub.storage.sync_service import MemorySyncService

logger = logging.getLogger(__name__)


@dataclass
class CompensationMetrics:
    """补偿任务运行指标。"""

    total_runs: int = 0
    total_succeeded: int = 0
    total_failed: int = 0
    last_run_at: float = 0.0
    last_duration_ms: float = 0.0
    last_error: str = ""


class PendingIndexCompensationTask:
    """
    pending_index 补偿任务。

    使用方式:
        task = PendingIndexCompensationTask(sync_service, interval_seconds=30)
        task.start()
        ...
        task.stop()
    """

    def __init__(
        self,
        sync_service: MemorySyncService,
        interval_seconds: float = 30.0,
        enabled: bool = True,
    ):
        """
        参数:
            sync_service: MemorySyncService 实例
            interval_seconds: 补偿扫描间隔（秒）
            enabled: 是否启用后台补偿；生产/测试环境建议启用
        """
        self.sync_service = sync_service
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.enabled = enabled
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._metrics = CompensationMetrics()

    @property
    def metrics(self) -> CompensationMetrics:
        """返回补偿任务指标快照。"""
        return CompensationMetrics(
            total_runs=self._metrics.total_runs,
            total_succeeded=self._metrics.total_succeeded,
            total_failed=self._metrics.total_failed,
            last_run_at=self._metrics.last_run_at,
            last_duration_ms=self._metrics.last_duration_ms,
            last_error=self._metrics.last_error,
        )

    def start(self) -> None:
        """启动后台补偿线程。"""
        if not self.enabled:
            logger.info("pending_index compensation task is disabled")
            return
        if self._thread is not None and self._thread.is_alive():
            logger.warning("compensation task already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="pending_index_compensation",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "pending_index compensation task started (interval=%.1fs)",
            self.interval_seconds,
        )

    def stop(self) -> None:
        """停止后台补偿线程。"""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("compensation task thread did not stop in time")
        self._thread = None
        logger.info("pending_index compensation task stopped")

    def run_once(self) -> None:
        """手动执行一次补偿扫描（主要用于测试）。"""
        self._execute_sync()

    def _run_loop(self) -> None:
        """后台循环。"""
        while not self._stop_event.is_set():
            self._execute_sync()
            # 使用 Event.wait 以便 stop() 可中断等待
            self._stop_event.wait(self.interval_seconds)

    def _execute_sync(self) -> None:
        """执行一次同步并更新指标。"""
        self._metrics.total_runs += 1
        self._metrics.last_error = ""
        try:
            result = self.sync_service.sync_pending()
            self._metrics.total_succeeded += len(result.succeeded)
            self._metrics.total_failed += len(result.failed)
            self._metrics.last_duration_ms = result.duration_ms
            self._metrics.last_run_at = time.time()
            if result.failed:
                self._metrics.last_error = f"failed ids: {result.failed}"
                logger.warning(
                    "compensation run failed for %d memories: %s",
                    len(result.failed),
                    result.failed,
                )
        except Exception as exc:
            self._metrics.last_error = str(exc)
            logger.exception("compensation run encountered error")
