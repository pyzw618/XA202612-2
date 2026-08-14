from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    ConflictDecision,
    ConflictRecord,
    Evidence,
    PreferenceMemory,
    PreferenceType,
)
from memoryhub.core.conflict.resolver import ConflictResolver
from memoryhub.core.preference.updater import PreferenceUpdater


def _preference(memory_id: str, text: str, event_id: str) -> PreferenceMemory:
    return PreferenceMemory(
        memory_id=memory_id,
        user_id="user-1",
        preference_type=PreferenceType.OUTPUT_STYLE,
        text=text,
        payload={"target": "style", "value": "A"},
        extract_source="explicit_feedback",
        evidences=[
            Evidence(
                event_id=event_id,
                evidence_id=f"ev-{event_id}",
                content=text,
                timestamp=datetime.now(timezone.utc),
            )
        ],
    )


def test_contextual_similar_preference_reinforces_evidence_without_overwrite():
    updater = PreferenceUpdater()
    original = _preference("pref-a", "I like A", "evt-a")
    contextual = _preference("pref-context", "I like A, but my friend likes B", "evt-b")

    assert updater.add(original) == "pref-a"
    assert updater.add(contextual) == "pref-a"

    active = updater._get("pref-a")
    assert active is not None
    assert active.text == "I like A"
    assert active.version == 1
    assert {e.event_id for e in active.evidences} == {"evt-a", "evt-b"}
    assert updater._get("pref-context") is None


class _PreferenceRepo:
    def __init__(self, items):
        self.items = {item.memory_id: item for item in items}

    def get_by_id(self, memory_id):
        return self.items.get(memory_id)


class _WriteService:
    def __init__(self, preferences):
        self.pref_repo = _PreferenceRepo(preferences)
        self.know_repo = None
        self.saved = []

    def upsert_memory(self, memory):
        self.pref_repo.items[memory.memory_id] = memory
        self.saved.append(memory)


def _pref(memory_id, value, event_id):
    return PreferenceMemory(
        memory_id=memory_id,
        user_id="user-1",
        text=f"Prefer {value}",
        payload={"target": "format", "value": value},
        root_id=memory_id,
        evidences=[
            Evidence(
                evidence_id=f"ev-{event_id}",
                event_id=event_id,
                content=f"Prefer {value}",
                timestamp=datetime.now(timezone.utc),
            )
        ],
    )


def test_generic_override_creates_versioned_successor_with_merged_evidence():
    old = _pref("pref-old", "markdown", "event-old")
    incoming = _pref("pref-new", "html", "event-new")
    service = _WriteService([old])
    conflict = ConflictRecord(
        user_id="user-1",
        old_memory_id=old.memory_id,
        new_memory_id=incoming.memory_id,
        memory_type="preference",
        old_content=old.text,
        new_content=incoming.text,
        reason="explicit_feedback and same target",
    )

    resolved = ConflictResolver(write_service=service).resolve(conflict, old, incoming)

    successor = service.pref_repo.get_by_id("pref-new")
    assert resolved.decision is ConflictDecision.OVERRIDE
    assert service.pref_repo.get_by_id("pref-old").status.value == "archived"
    assert successor.parent_id == "pref-old"
    assert successor.root_id == "pref-old"
    assert successor.version == 2
    assert {item.event_id for item in successor.evidences} == {"event-old", "event-new"}
