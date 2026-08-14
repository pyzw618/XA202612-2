from datetime import datetime, timezone

from memoryhub.adapter.schemas import Evidence, PreferenceMemory, PreferenceType
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
