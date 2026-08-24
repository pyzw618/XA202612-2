"""Pure episode lifecycle, replay, and resume-token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from memoryhub.domain.contracts import EpisodeStatus


class EpisodeLifecycleError(ValueError):
    """An episode status transition or resume operation is invalid."""


class EpisodeResumeConflict(RuntimeError):
    """A resume token or snapshot version is stale."""


_ALLOWED_CLOSE = {
    EpisodeStatus.ACTIVE.value: {EpisodeStatus.COMPLETED.value, EpisodeStatus.FAILED.value},
    EpisodeStatus.SUSPENDED.value: {
        EpisodeStatus.COMPLETED.value,
        EpisodeStatus.FAILED.value,
    },
}


def new_resume_token() -> str:
    return secrets.token_urlsafe(32)


def hash_resume_token(token: str) -> str:
    if not token:
        raise ValueError("resume token must not be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resume_token_matches(token: str, token_hash: str | None) -> bool:
    return bool(token_hash) and hmac.compare_digest(hash_resume_token(token), token_hash)


def allowed_close_status(current: str, target: str) -> bool:
    return target in _ALLOWED_CLOSE.get(current, set())


def replay_episode(
    snapshot: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Replay only events newer than the snapshot's sequence.

    Event payloads may contain a structured ``state`` object, or the small
    phase/status fields used by the append service. Unknown payload keys are
    retained under ``event_payloads`` for diagnostics rather than discarded.
    """

    result = deepcopy(dict(snapshot))
    result.setdefault("event_payloads", [])
    last_seq = int(result.get("last_event_seq", 0))
    for event in sorted(events, key=lambda item: int(item.get("seq_no", 0))):
        seq_no = int(event.get("seq_no", 0))
        if seq_no <= last_seq:
            continue
        payload = dict(event.get("payload") or {})
        state = payload.get("state")
        if isinstance(state, Mapping):
            result.update(deepcopy(dict(state)))
        for key in ("current_phase", "goal", "pending_steps", "completed_steps", "constraints"):
            if key in payload:
                result[key] = deepcopy(payload[key])
        if "phase" in payload:
            result["current_phase"] = payload["phase"]
        if "status" in payload and payload["status"] in {item.value for item in EpisodeStatus}:
            result["status"] = payload["status"]
        result["event_payloads"].append(
            {"seq_no": seq_no, "event_type": event.get("event_type", "")}
        )
        last_seq = seq_no
    result["last_event_seq"] = last_seq
    return result


def stale_resource_ids(
    expected: Mapping[str, str], current: Mapping[str, str]
) -> list[str]:
    """Return resources missing or changed since the episode snapshot."""

    return sorted(
        resource_id
        for resource_id, version in expected.items()
        if current.get(resource_id) != version
    )


def is_terminal_boundary(checkpoint_type: str) -> bool:
    """Return whether a checkpoint closes the episode."""

    return checkpoint_type in {"COMPLETE", "FAILED"}


__all__ = [
    "EpisodeLifecycleError",
    "EpisodeResumeConflict",
    "allowed_close_status",
    "hash_resume_token",
    "is_terminal_boundary",
    "new_resume_token",
    "replay_episode",
    "resume_token_matches",
    "stale_resource_ids",
]
