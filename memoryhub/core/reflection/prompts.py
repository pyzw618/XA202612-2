"""Versioned reflection prompts.

The prompt instructs the model to produce only a Candidate staging object.
Writing to long-term Authority is explicitly forbidden here and is enforced
by the ReflectionService implementation.
"""

from __future__ import annotations

from typing import Any

PROMPT_VERSION: str = "reflection/v1"


_REFLECTION_PROMPT_TEMPLATE = """You are a memory formation assistant.

Your job is to inspect the current task context and decide whether a new
staging Candidate memory should be created.  You must NOT write or commit
to long-term memory.  You may only return a Candidate description.

Input fields:
- tenant_id: {tenant_id}
- user_id: {user_id}
- task_id: {task_id}
- episode_id: {episode_id}
- event_id: {event_id}
- requested_memory_type: {requested_memory_type}
- scope_hint: {scope_hint}
- payload_summary: {payload_summary}
- working_state_snapshot: {working_state_snapshot}
- episode_history_summary: {episode_history_summary}

Rules:
1. If the event is a strong, task-scoped preference (e.g. "use DOCX for Project-A
   reports"), return a Candidate with memory_type=PREFERENCE and scope_level=TASK
   or PROJECT, never GLOBAL unless the user explicitly names a global rule.
2. If the event is a repeated successful procedure, return memory_type=PROCEDURAL.
3. If the event is a factual claim, return memory_type=SEMANTIC. Its claim must
   contain subject, predicate, and object_value (and may also retain statement).
   Never put the whole sentence into one of those three fields.
4. If the event is episodic, return memory_type=EPISODIC.
5. If you are uncertain, return status=REVIEW and lower confidence.
6. Do not fabricate multiple independent evidences from the same event.

Output a JSON object with these fields:
- candidate_id (string)
- memory_type (one of PREFERENCE, SEMANTIC, PROCEDURAL, EPISODIC)
- normalized_key (short stable key, e.g. "format:docx:project-a")
- claim (object with the extracted content)
- scope_level (one of TASK, PROJECT, APPLICATION, DOMAIN, GLOBAL, SESSION)
- scope (the concrete scope value, e.g. "PROJECT:project-a")
- confidence (0.0-1.0)
- utility (0.0-1.0)
- stability (0.0-1.0)
- reason (short explanation)
- evidence_refs (list of event ids that support this candidate)
- supporting_episode_ids (list of episode ids)
- status (ACCUMULATING or REVIEW)
"""


def render_reflection_prompt(input_data: dict[str, Any]) -> str:
    """Render the current prompt version with the supplied input fields."""

    return _REFLECTION_PROMPT_TEMPLATE.format(
        tenant_id=input_data.get("tenant_id", ""),
        user_id=input_data.get("user_id", ""),
        task_id=input_data.get("task_id", ""),
        episode_id=input_data.get("episode_id", ""),
        event_id=input_data.get("event_id", ""),
        requested_memory_type=input_data.get("requested_memory_type", ""),
        scope_hint=input_data.get("scope_hint", ""),
        payload_summary=input_data.get("payload_summary", {}),
        working_state_snapshot=input_data.get("working_state_snapshot", {}),
        episode_history_summary=input_data.get("episode_history_summary", []),
    )


__all__ = ["PROMPT_VERSION", "render_reflection_prompt"]
