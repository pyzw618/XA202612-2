"""Background scheduler and metrics for durable extraction retries."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from memoryhub.core.ingestion.retry import ExtractionRetryRunResult, ExtractionRetryService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionRetryMetrics:
    total_runs: int = 0
    total_claimed: int = 0
    total_succeeded: int = 0
    total_retried: int = 0
    total_dead_lettered: int = 0
    last_run_at: float = 0.0
    last_duration_ms: float = 0.0
    last_error_code: str = ""


class ExtractionRetryTask:
    """Run due extraction tasks on a bounded, stoppable background thread."""

    def __init__(
        self,
        service: ExtractionRetryService,
        *,
        interval_seconds: float = 30.0,
        batch_size: int = 20,
        enabled: bool = True,
    ) -> None:
        self.service = service
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.batch_size = max(1, min(int(batch_size), 200))
        self.enabled = bool(enabled)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._metrics = ExtractionRetryMetrics()
        self._metrics_lock = threading.Lock()

    @property
    def metrics(self) -> ExtractionRetryMetrics:
        with self._metrics_lock:
            return ExtractionRetryMetrics(
                total_runs=self._metrics.total_runs,
                total_claimed=self._metrics.total_claimed,
                total_succeeded=self._metrics.total_succeeded,
                total_retried=self._metrics.total_retried,
                total_dead_lettered=self._metrics.total_dead_lettered,
                last_run_at=self._metrics.last_run_at,
                last_duration_ms=self._metrics.last_duration_ms,
                last_error_code=self._metrics.last_error_code,
            )

    def start(self) -> None:
        if not self.enabled:
            logger.info("extraction retry task is disabled")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="extraction_retry_worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("extraction retry worker did not stop in time")
        self._thread = None

    def run_once(self) -> ExtractionRetryRunResult:
        started = time.perf_counter()
        try:
            result = self.service.run_due(limit=self.batch_size)
        except Exception:
            with self._metrics_lock:
                self._metrics.total_runs += 1
                self._metrics.last_run_at = time.time()
                self._metrics.last_duration_ms = (time.perf_counter() - started) * 1000
                self._metrics.last_error_code = "extraction.retry_worker.failed"
            logger.exception("extraction retry worker run failed")
            return ExtractionRetryRunResult()

        with self._metrics_lock:
            self._metrics.total_runs += 1
            self._metrics.total_claimed += result.claimed
            self._metrics.total_succeeded += result.succeeded
            self._metrics.total_retried += result.retried
            self._metrics.total_dead_lettered += result.dead_lettered
            self._metrics.last_run_at = time.time()
            self._metrics.last_duration_ms = (time.perf_counter() - started) * 1000
            self._metrics.last_error_code = ""
        return result

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self.interval_seconds)
