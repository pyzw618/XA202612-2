"""
数据库表结构定义 (DDL)。

MemoryHub 5 张表:
  events         — 原始事件（Agent 上报的每一条操作记录）
  preferences    — 偏好记忆（用户的格式偏好、工具选择等）
  knowledge      — 知识记忆（学到的工作流、案例、模板）
  conflicts      — 冲突记录（新旧偏好矛盾的裁决结果）
  forget_history — 遗忘审计（用户要求"忘掉"的记录）
"""

# ============================================================
# 表 1: events — 原始事件
# ============================================================
CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT '',
    session_id      TEXT NOT NULL DEFAULT '',
    task_id         TEXT NOT NULL DEFAULT '',
    event_type      TEXT NOT NULL DEFAULT 'tool_call',
    source          TEXT NOT NULL DEFAULT 'os_agent',
    content         TEXT NOT NULL DEFAULT '{}',
    scene           TEXT NOT NULL DEFAULT '',
    task_type       TEXT NOT NULL DEFAULT '',
    quality_score   REAL NOT NULL DEFAULT 0.0,
    sensitive_level TEXT NOT NULL DEFAULT 'NONE',
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_scene ON events(scene, task_type);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
"""

# ============================================================
# 表 2: preferences — 偏好记忆
# ============================================================
CREATE_PREFERENCES = """
CREATE TABLE IF NOT EXISTS preferences (
    memory_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT '',
    preference_type TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    embedding       BLOB,
    scope_scene     TEXT NOT NULL DEFAULT '',
    scope_task_type TEXT NOT NULL DEFAULT '',
    scope_app       TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'active',
    level           TEXT NOT NULL DEFAULT 'short',
    occur_count     INTEGER NOT NULL DEFAULT 1,
    version         INTEGER NOT NULL DEFAULT 1,
    parent_id       TEXT,
    evidence_ids    TEXT NOT NULL DEFAULT '[]',
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pref_user ON preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_pref_type ON preferences(preference_type);
CREATE INDEX IF NOT EXISTS idx_pref_status ON preferences(status);
CREATE INDEX IF NOT EXISTS idx_pref_level ON preferences(level);
CREATE INDEX IF NOT EXISTS idx_pref_scope ON preferences(scope_scene, scope_task_type);
CREATE INDEX IF NOT EXISTS idx_pref_confidence ON preferences(confidence);
"""

# ============================================================
# 表 3: knowledge — 知识记忆
# ============================================================
CREATE_KNOWLEDGE = """
CREATE TABLE IF NOT EXISTS knowledge (
    memory_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT '',
    knowledge_type  TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    embedding       BLOB,
    steps           TEXT NOT NULL DEFAULT '[]',
    tools           TEXT NOT NULL DEFAULT '[]',
    template_body   TEXT,
    scope_scene     TEXT NOT NULL DEFAULT '',
    scope_task_type TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 0.0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    total_count     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active',
    evidence_ids    TEXT NOT NULL DEFAULT '[]',
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_know_user ON knowledge(user_id);
CREATE INDEX IF NOT EXISTS idx_know_type ON knowledge(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_know_status ON knowledge(status);
CREATE INDEX IF NOT EXISTS idx_know_confidence ON knowledge(confidence);
"""

# ============================================================
# 表 4: conflicts — 冲突记录
# ============================================================
CREATE_CONFLICTS = """
CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id     TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT '',
    memory_type     TEXT NOT NULL DEFAULT '',
    old_memory_id   TEXT NOT NULL,
    new_memory_id   TEXT NOT NULL,
    old_content     TEXT NOT NULL DEFAULT '',
    new_content     TEXT NOT NULL DEFAULT '',
    decision        TEXT NOT NULL DEFAULT 'pending',
    reason          TEXT NOT NULL DEFAULT '',
    resolved_by     TEXT NOT NULL DEFAULT 'auto',
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conflict_user ON conflicts(user_id);
CREATE INDEX IF NOT EXISTS idx_conflict_decision ON conflicts(decision);
CREATE INDEX IF NOT EXISTS idx_conflict_created ON conflicts(created_at);
"""

# ============================================================
# 表 5: forget_history — 遗忘审计日志
# ============================================================
CREATE_FORGET_HISTORY = """
CREATE TABLE IF NOT EXISTS forget_history (
    forget_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT '',
    instruction     TEXT NOT NULL DEFAULT '',
    deleted_type    TEXT NOT NULL DEFAULT '',
    deleted_count   INTEGER NOT NULL DEFAULT 0,
    deleted_ids     TEXT NOT NULL DEFAULT '[]',
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forget_user ON forget_history(user_id);
CREATE INDEX IF NOT EXISTS idx_forget_created ON forget_history(created_at);
"""

# ============================================================
# 汇总
# ============================================================
ALL_TABLES = [
    ("events", CREATE_EVENTS),
    ("preferences", CREATE_PREFERENCES),
    ("knowledge", CREATE_KNOWLEDGE),
    ("conflicts", CREATE_CONFLICTS),
    ("forget_history", CREATE_FORGET_HISTORY),
]
