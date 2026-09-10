"""真机 HTTP 评测支撑包。

本包只通过 HTTP 访问已部署的 MemoryHub 服务（kylin embedding + Milvus），
**不** import ``memoryhub.*`` 的运行时对象，避免把进程内 mock 配置的结果
误当成真机结果。

与 ``evaluation/metrics/`` 的区别：
- ``evaluation/metrics/`` 是进程内评估器，用于单元测试与确定性回归；
- ``evaluation/live/`` 是端到端评估器，用于生产验收，报告证据等级为
  ``LIVE_HTTP``。
"""

from __future__ import annotations

from evaluation.live.client import LiveClient, LiveClientError
from evaluation.live.datasets import DatasetError, load_dataset
from evaluation.live.fingerprint import (
    PRODUCTION_REQUIREMENTS,
    FingerprintMismatch,
    assert_fingerprint,
    build_environment_fingerprint,
    check_fingerprint,
    check_preconditions,
    read_system_status,
)

__all__ = [
    "LiveClient",
    "LiveClientError",
    "DatasetError",
    "FingerprintMismatch",
    "PRODUCTION_REQUIREMENTS",
    "assert_fingerprint",
    "build_environment_fingerprint",
    "check_fingerprint",
    "check_preconditions",
    "load_dataset",
    "read_system_status",
]
