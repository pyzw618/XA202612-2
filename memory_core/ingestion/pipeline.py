from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


SOURCE_ALIASES = {
    "tool": "tool_result",
    "tool_call": "tool_result",
    "tool_call_result": "tool_result",
    "tool_execution": "tool_result",
    "agent_tool": "tool_result",
    "behavior": "user_behavior",
    "user_action": "user_behavior",
    "user_behavior": "user_behavior",
    "config": "manual_config",
    "manual": "manual_config",
    "manual_config": "manual_config",
}

EVENT_ALIASES = {
    "tool": "tool_result",
    "tool_call": "tool_result",
    "tool_call_result": "tool_result",
    "tool_execution": "tool_result",
    "action": "user_action",
    "behavior": "user_action",
    "user_action": "user_action",
    "config": "manual_config",
    "manual": "manual_config",
    "manual_config": "manual_config",
}

SENSITIVE_PATTERNS = (
    ("api_key", re.compile(r"(?i)(api[_-]?key|access[_-]?key)\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{6,})")),
    ("token", re.compile(r"(?i)(token|secret|password)\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{6,})")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
)

REQUIRED_FIELDS = ("event_id", "source_type", "event_type", "user_id", "occurred_at", "payload")
VALID_SOURCE_TYPES = frozenset({"tool_result", "user_behavior", "manual_config"})


@dataclass(frozen=True)
class QualityReport:
    """Quality dimensions used by downstream admission policy."""

    score: float
    status: str
    completeness: float
    validity: float
    consistency: float
    freshness: float
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IngestionRecord:
    """Canonical event emitted after cleaning and normalization."""

    event_id: str
    source_type: str
    event_type: str
    user_id: str
    session_id: str
    scene: str
    task_type: str
    occurred_at: str
    text: str
    payload: dict[str, Any]
    schema_version: str
    source_hash: str
    redactions: list[str]
    quality: QualityReport

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["quality"] = self.quality.to_dict()
        return result


class IngestionPipeline:
    """Normalize raw events from tools, user behavior, and manual config.

    The implementation deliberately uses deterministic standard-library rules
    so that it can run in a constrained edge environment and be audited.
    """

    def __init__(self, reference_time: datetime | str | None = None) -> None:
        self.reference_time = _parse_datetime(reference_time) if reference_time is not None else datetime.now(timezone.utc)

    def process(self, raw: Mapping[str, Any]) -> IngestionRecord:
        if not isinstance(raw, Mapping):
            raise TypeError("raw event must be a mapping")

        cleaned = _clean_value(dict(raw))
        if not isinstance(cleaned, dict):
            raise TypeError("raw event must normalize to a mapping")
        source_hash = hashlib.sha256(_stable_json(cleaned).encode("utf-8")).hexdigest()
        redactions: set[str] = set()
        cleaned = _redact_value(cleaned, redactions)

        source_type = _canonical_source(_pick(cleaned, "source_type", "source", "channel"))
        event_type = _canonical_event(_pick(cleaned, "event_type", "type"), source_type)
        user_id = _as_text(_pick(cleaned, "user_id", "user", "uid"))
        session_id = _as_text(_pick(cleaned, "session_id", "session", "conversation_id"))
        scene = _as_text(_pick(cleaned, "scene", "context_scene"))
        task_type = _as_text(_pick(cleaned, "task_type", "task", "intent"))
        occurred_at, timestamp_ok = _normalize_timestamp(
            _pick(cleaned, "occurred_at", "timestamp", "time", "created_at")
        )

        payload_value = _pick(cleaned, "payload", "content", "data", "result")
        payload = dict(payload_value) if isinstance(payload_value, Mapping) else {"value": payload_value} if payload_value is not None else {}
        payload = _clean_value(payload)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        payload = _redact_value(payload, redactions)
        if source_type == "tool_result" and "tool_name" not in payload:
            tool_name = _pick(cleaned, "tool_name", "tool")
            if tool_name is not None:
                payload["tool_name"] = _as_text(tool_name)

        text_value = _pick(cleaned, "text", "message", "description")
        if text_value is None and isinstance(cleaned.get("content"), str):
            text_value = cleaned["content"]
        text = _as_text(text_value)
        if not text and isinstance(payload.get("output"), str):
            text = _as_text(payload["output"])

        event_id = _as_text(_pick(cleaned, "event_id", "id"))
        if not event_id:
            event_id = "evt_" + source_hash[:16]

        quality = _score_quality(
            event_id=event_id,
            source_type=source_type,
            event_type=event_type,
            user_id=user_id,
            occurred_at=occurred_at,
            timestamp_ok=timestamp_ok,
            payload=payload,
            redactions=redactions,
            reference_time=self.reference_time,
        )
        return IngestionRecord(
            event_id=event_id,
            source_type=source_type,
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            scene=scene,
            task_type=task_type,
            occurred_at=occurred_at,
            text=text,
            payload=payload,
            schema_version="1.0",
            source_hash=source_hash,
            redactions=sorted(redactions),
            quality=quality,
        )


def _pick(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        value = unicodedata.normalize("NFKC", value)
        value = "".join(char for char in value if not unicodedata.category(char).startswith("C") or char in "\t\n\r")
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, Mapping):
        return {str(key): _clean_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_value(item) for item in value]
    return value


def _redact_text(value: str, labels: set[str]) -> str:
    result = value
    for label, pattern in SENSITIVE_PATTERNS:
        if pattern.search(result):
            labels.add(label)
            if label in {"api_key", "token"} and pattern.groups >= 2:
                result = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", result)
            else:
                result = pattern.sub(f"[REDACTED_{label.upper()}]", result)
    return result


def _redact_value(value: Any, labels: set[str]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, labels)
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            label = _sensitive_key_label(key_text)
            if label and item not in (None, ""):
                labels.add(label)
                result[key_text] = f"[REDACTED_{label.upper()}]"
            else:
                result[key_text] = _redact_value(item, labels)
        return result
    if isinstance(value, list):
        return [_redact_value(item, labels) for item in value]
    return value


def _sensitive_key_label(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized in {"apikey", "accesskey"}:
        return "api_key"
    if normalized in {"token", "secret", "password"}:
        return "token"
    return ""


def _canonical_source(value: Any) -> str:
    raw = _as_text(value).lower().replace("-", "_").replace(" ", "_")
    return SOURCE_ALIASES.get(raw, raw)


def _canonical_event(value: Any, source_type: str) -> str:
    raw = _as_text(value).lower().replace("-", "_").replace(" ", "_")
    if raw:
        return EVENT_ALIASES.get(raw, raw)
    return {"tool_result": "tool_result", "user_behavior": "user_action", "manual_config": "manual_config"}.get(source_type, "unknown")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = _as_text(value)
    if not text:
        return None
    longmemeval_match = re.fullmatch(
        r"(\d{4}/\d{2}/\d{2})\s+\([A-Za-z]{3}\)\s+(\d{2}:\d{2})",
        text,
    )
    if longmemeval_match:
        parsed = datetime.strptime(
            f"{longmemeval_match.group(1)} {longmemeval_match.group(2)}",
            "%Y/%m/%d %H:%M",
        )
        return parsed.replace(tzinfo=timezone.utc)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T00:00:00+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    else:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_timestamp(value: Any) -> tuple[str, bool]:
    parsed = _parse_datetime(value)
    if parsed is None:
        return "", False
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z"), True


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _score_quality(
    *,
    event_id: str,
    source_type: str,
    event_type: str,
    user_id: str,
    occurred_at: str,
    timestamp_ok: bool,
    payload: Mapping[str, Any],
    redactions: Iterable[str],
    reference_time: datetime,
) -> QualityReport:
    issues: list[str] = []
    values = {
        "event_id": event_id,
        "source_type": source_type,
        "event_type": event_type,
        "user_id": user_id,
        "occurred_at": occurred_at,
        "payload": payload,
    }
    missing = [key for key in REQUIRED_FIELDS if values[key] in ("", None, {})]
    completeness = 1.0 - len(missing) / len(REQUIRED_FIELDS)
    if missing:
        issues.extend(f"missing:{key}" for key in missing)

    validity = 1.0
    if source_type not in VALID_SOURCE_TYPES:
        validity -= 0.4
        issues.append("invalid:source_type")
    if not event_type or event_type == "unknown":
        validity -= 0.2
        issues.append("invalid:event_type")
    if not timestamp_ok:
        validity -= 0.3
        issues.append("invalid:occurred_at")
    validity = max(0.0, validity)

    consistency = 1.0
    if source_type == "tool_result" and not payload.get("tool_name"):
        consistency -= 0.4
        issues.append("inconsistent:tool_name")
    if source_type == "user_behavior" and not any(key in payload for key in ("action", "target", "value")):
        consistency -= 0.3
        issues.append("inconsistent:behavior_payload")
    if source_type == "manual_config" and not any(key in payload for key in ("key", "name", "setting", "value")):
        consistency -= 0.3
        issues.append("inconsistent:config_payload")
    consistency = max(0.0, consistency)

    freshness = 0.0
    parsed = _parse_datetime(occurred_at)
    if parsed is not None:
        age_days = (reference_time - parsed).total_seconds() / 86400.0
        if age_days < -1:
            freshness = 0.5
            issues.append("freshness:future_event")
        elif age_days <= 30:
            freshness = 1.0
        elif age_days <= 180:
            freshness = 0.8
        elif age_days <= 365:
            freshness = 0.6
        else:
            freshness = 0.4
            issues.append("freshness:stale_event")
    else:
        issues.append("freshness:unknown")

    score = round(0.4 * completeness + 0.3 * validity + 0.2 * consistency + 0.1 * freshness, 4)
    status = "accepted" if score >= 0.8 else "review" if score >= 0.6 else "rejected"
    # Missing identity plus an invalid timestamp cannot be safely replayed.
    if "user_id" in missing and not timestamp_ok:
        status = "rejected"
    elif source_type not in VALID_SOURCE_TYPES or missing or not timestamp_ok:
        status = "review"
    if redactions:
        issues.append("security:redacted_sensitive_value")
    return QualityReport(
        score=score,
        status=status,
        completeness=round(completeness, 4),
        validity=round(validity, 4),
        consistency=round(consistency, 4),
        freshness=round(freshness, 4),
        issues=issues,
    )
