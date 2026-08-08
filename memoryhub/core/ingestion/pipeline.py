"""End-to-end raw Agent event ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoryhub.adapter.schemas import MemoryEvent, SafetyAction
from memoryhub.config import AppConfig
from memoryhub.core.ingestion.cleaner import DataCleaner
from memoryhub.core.ingestion.normalizer import DataNormalizer
from memoryhub.core.safety import SensitiveDetector


@dataclass(frozen=True)
class IngestionResult:
    """Safe projection of a completed ingestion run."""

    event: MemoryEvent | None
    safety_action: SafetyAction
    safety_findings: tuple[dict[str, Any], ...]

    def model_dump(self) -> dict[str, Any]:
        return {
            "pipeline": {
                "safety_action": self.safety_action.value,
                "finding_count": len(self.safety_findings),
                "findings": list(self.safety_findings),
            },
            "event": (
                self.event.model_dump(mode="json") if self.event is not None else None
            ),
        }


class IngestionPipeline:
    """Clean, normalize, score, and safely sanitize one raw Agent event."""

    def __init__(
        self,
        *,
        cleaner: DataCleaner | None = None,
        normalizer: DataNormalizer | None = None,
        detector: SensitiveDetector | None = None,
        config: AppConfig | None = None,
    ):
        self.cleaner = cleaner or DataCleaner()
        self.normalizer = normalizer or DataNormalizer()
        runtime_config = config or AppConfig()
        self.detector = detector or SensitiveDetector.from_config(runtime_config.safety)

    def process(self, raw_data: dict[str, Any]) -> IngestionResult:
        cleaned = self.cleaner.clean(raw_data)
        normalized = self.normalizer.normalize(cleaned)
        safety_result = self.detector.process(normalized)

        event = None
        if (
            safety_result.sanitized_event is not None
            and safety_result.decision.action
            in {
                SafetyAction.ALLOW,
                SafetyAction.MASK,
            }
        ):
            event = MemoryEvent.model_validate(
                safety_result.sanitized_event.model_dump(mode="python")
            )

        findings = tuple(
            {
                "rule_name": finding.rule_name,
                "level": finding.level.value,
                "field_path": finding.field_path,
                "action": finding.suggested_action.value,
            }
            for finding in safety_result.report.findings
        )
        return IngestionResult(
            event=event,
            safety_action=safety_result.decision.action,
            safety_findings=findings,
        )
