"""Process-local coordination for SQLite files shared by MemoryHub services."""

from __future__ import annotations

import os
import threading
from pathlib import Path

_registry_guard = threading.Lock()
_database_locks: dict[str, threading.RLock] = {}


def sqlite_database_lock(database_path: str | Path) -> threading.RLock:
    """Return the process-wide re-entrant lock for ``database_path``.

    File paths are normalized so relative and absolute aliases share a lock.
    Separate ``:memory:`` databases do not share storage and get private locks.
    """

    path_text = os.fspath(database_path)
    if path_text == ":memory:":
        return threading.RLock()
    key = os.path.normcase(str(Path(path_text).expanduser().absolute()))
    with _registry_guard:
        return _database_locks.setdefault(key, threading.RLock())
