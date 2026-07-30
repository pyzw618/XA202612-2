"""
Storage 子包 — 数据库管理 + 5 张表 + Repository 层 + 证据链 + 生命周期。

用法:
    from src.storage import DatabaseManager, EventRepository, PreferenceRepository

    db = DatabaseManager()
    event_repo = EventRepository(db)
    pref_repo = PreferenceRepository(db)
"""

from .database import DatabaseManager
from .models import EventRow, PreferenceRow, KnowledgeRow, ConflictRow, ForgetRow
from .repositories import (
    EventRepository,
    PreferenceRepository,
    KnowledgeRepository,
    ConflictRepository,
    ForgetRepository,
)
from .evidence_store import EvidenceStore
from .lifecycle import LifecycleManager, PROMOTE_THRESHOLDS
from .manager import MemoryManager
