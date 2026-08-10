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
        fact_index_service=None,
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
        self.fact_index_service = fact_index_service
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._metrics = CompensationMetrics()
        self._metrics_lock = threading.Lock()

    @property
    def metrics(self) -> CompensationMetrics:
        """返回补偿任务指标快照。"""
        with self._metrics_lock:
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
        started = time.perf_counter()
        with self._metrics_lock:
            self._metrics.total_runs += 1
            self._metrics.last_error = ""
        result = None
        fact_result = None
        try:
            result = self.sync_service.sync_pending()
        except Exception:
            with self._metrics_lock:
                self._metrics.last_error = "memory_projection.failed"
            logger.exception("memory projection compensation failed")
        if self.fact_index_service is not None:
            try:
                fact_result = self.fact_index_service.sync_pending()
            except Exception:
                with self._metrics_lock:
                    self._metrics.last_error = "fact_projection.failed"
                logger.exception("fact projection compensation failed")
        succeeded = (len(result.succeeded) if result is not None else 0) + (
            len(fact_result.succeeded) if fact_result is not None else 0
        )
        failed_ids = (list(result.failed) if result is not None else []) + (
            list(fact_result.failed) if fact_result is not None else []
        )
        with self._metrics_lock:
            self._metrics.total_succeeded += succeeded
            self._metrics.total_failed += len(failed_ids)
            self._metrics.last_duration_ms = (time.perf_counter() - started) * 1000
            self._metrics.last_run_at = time.time()
            if failed_ids:
                self._metrics.last_error = f"failed ids: {failed_ids}"
        if failed_ids:
            logger.warning(
                "compensation run failed for %d memories: %s",
                len(failed_ids),
                failed_ids,
            )
