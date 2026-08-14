"""Backward-compatible evidence normalization, deterministic de-duplication and summaries."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


class EvidenceMerger:
    def __init__(self, max_evidences: int = 20) -> None:
        self.max_evidences = max(1, max_evidences)

    def normalize(self, evidence: Any) -> Any:
        if isinstance(evidence, dict):
            result = dict(evidence)
            result.setdefault("event_id", "")
            result.setdefault("evidence_id", "")
            result.setdefault("content", result.get("excerpt", ""))
            result.setdefault("source_type", "unknown")
            result.setdefault("timestamp", "")
            result.setdefault("quality", result.get("quality_score", 1.0))
            return result
        # Existing Pydantic Evidence objects retain their public type and fields.
        for name, default in (("event_id", ""), ("evidence_id", ""), ("content", "")):
            if not hasattr(evidence, name):
                try:
                    setattr(evidence, name, default)
                except Exception:
                    pass
        return evidence

    def key(self, evidence: Any) -> str:
        event_id = str(self._value(evidence, "event_id") or "")
        evidence_id = str(self._value(evidence, "evidence_id") or "")
        if event_id and evidence_id:
            return f"id:{event_id}:{evidence_id}"
        source_id = str(self._value(evidence, "source_id") or event_id)
        content = str(
            self._value(evidence, "content") or self._value(evidence, "excerpt") or ""
        )
        digest = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
        return f"content:{source_id}:{digest}"

    def normalize_and_merge(self, evidences: list[Any]) -> list[Any]:
        merged: dict[str, Any] = {}
        for evidence in evidences or []:
            normalized = self.normalize(evidence)
            key = self.key(normalized)
            if key not in merged:
                merged[key] = normalized
        ordered = sorted(merged.values(), key=self._sort_key)
        return ordered[-self.max_evidences :]

    def summary(self, evidences: list[Any]) -> dict[str, Any]:
        normalized = self.normalize_and_merge(evidences)
        sources = sorted(
            {str(self._value(item, "source_type") or "unknown") for item in normalized}
        )
        return {
            "count": len(normalized),
            "source_types": sources,
            "latest_at": self._timestamp_text(normalized[-1]) if normalized else "",
        }

    @staticmethod
    def _value(evidence: Any, name: str) -> Any:
        return (
            evidence.get(name, "")
            if isinstance(evidence, dict)
            else getattr(evidence, name, "")
        )

    def _sort_key(self, evidence: Any) -> tuple[float, str]:
        text = self._timestamp_text(evidence)
        if not text:
            return (0.0, self.key(evidence))
        try:
            value = text.replace("Z", "+00:00")
            return (
                datetime.fromisoformat(value)
                .replace(tzinfo=timezone.utc if "+" not in value[-6:] else None)
                .timestamp(),
                self.key(evidence),
            )
        except ValueError:
            return (0.0, self.key(evidence))

    def _timestamp_text(self, evidence: Any) -> str:
        value = self._value(evidence, "timestamp")
        return value.isoformat() if isinstance(value, datetime) else str(value or "")
