from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    """The V2 outer case schema. Benchmark-specific fields live in input/gold."""

    case_id: str
    benchmark: str
    ability: str
    difficulty: str
    input: dict[str, Any]
    gold: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = "2.0"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BenchmarkCase":
        required = {"case_id", "benchmark", "ability", "difficulty", "input", "gold"}
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"benchmark case missing required fields: {', '.join(missing)}")
        return cls(
            **{name: value[name] for name in required},
            metadata=dict(value.get("metadata") or {}),
            version=str(value.get("version", "2.0")),
        )
