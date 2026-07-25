"""
偏好置信度计算模块

根据证据数量、来源类型、时间衰减以及成事效果计算置信度。
"""

import math
from datetime import datetime, timezone
from memoryhub.adapter.schemas import PreferenceMemory, MemoryEvent, SourceType, Evidence


class ConfidenceCalculator:
    """偏好置信度计算器"""

    SOURCE_WEIGHTS = {
        "explicit_feedback": 1.0,
        "manual_config": 0.95,
        "repeated_behavior": 0.8,
        "tool_result": 0.6,
        "single_behavior": 0.4,
    }

    def calculate(self, preference: PreferenceMemory) -> float:
        """计算综合置信度"""
        if not preference.evidences:
            return 0.0

        timestamps = [e.timestamp for e in preference.evidences]
        sources = [e.source_type for e in preference.evidences]

        f_count = self._factor_evidence_count(len(preference.evidences))
        f_source = self._factor_source_type(sources)
        f_time = self._factor_time_decay(timestamps)
        f_consistency = self._factor_consistency(preference)

        raw_score = f_source * f_time * f_consistency * (1.0 + 0.15 * f_count)

        neg_penalty = 0.0
        for e in preference.evidences:
            if e.content and "OVERRIDE" in e.content:
                neg_penalty += 0.25 * e.weight
            elif e.content and "COMPROMISE" in e.content:
                neg_penalty += 0.10 * e.weight

        final_confidence = (1.0 / (1.0 + math.exp(-3.0 * (raw_score - 0.5)))) - neg_penalty
        preference.confidence = max(0.0, min(1.0, final_confidence))
        
        return preference.confidence

    def _factor_evidence_count(self, evidence_count: int) -> float:
        if evidence_count <= 0:
            return 0.0
        return math.log(1 + evidence_count)

    def _factor_source_type(self, sources: list[SourceType]) -> float:
        max_weight = 0.4
        for s in sources:
            if s == SourceType.USER_BEHAVIOR:
                weight = self.SOURCE_WEIGHTS["explicit_feedback"]
            elif s == SourceType.MANUAL_CONFIG:
                weight = self.SOURCE_WEIGHTS["manual_config"]
            elif s == SourceType.TOOL_RESULT:
                weight = self.SOURCE_WEIGHTS["tool_result"]
            else:
                weight = self.SOURCE_WEIGHTS["single_behavior"]
            
            if weight > max_weight:
                max_weight = weight
        return max_weight

    def _factor_time_decay(self, timestamps: list[datetime]) -> float:
        if not timestamps:
            return 1.0
        
        now = datetime.now(timezone.utc)
        half_life_days = 14.0
        total_decay = 0.0
        
        for t in timestamps:
            t_utc = t.replace(tzinfo=timezone.utc) if not t.tzinfo else t
            diff_days = (now - t_utc).total_seconds() / 86400.0
            decay = math.exp(-max(0.0, diff_days) / half_life_days)
            total_decay += decay
            
        return total_decay / len(timestamps)

    def _factor_consistency(self, preference: PreferenceMemory) -> float:
        success_count = 0
        total_count = len(preference.evidences)
        
        for e in preference.evidences:
            if "SUCCESS" in e.content and "OVERRIDE" not in e.content:
                success_count += 1
                
        if total_count == 0:
            return 1.0
            
        consistency_ratio = success_count / total_count
        return 1.2 if consistency_ratio >= 0.8 else (0.5 + 0.5 * consistency_ratio)

    def update_confidence(self, preference: PreferenceMemory, new_event: MemoryEvent) -> float:
        """增量更新置信度"""
        epsilon_t = 0.0
        status = new_event.payload.get("status", "")
        user_action = new_event.payload.get("user_action", "")

        if status in ["USER_REJECT", "API_FAIL"]:
            epsilon_t += 0.3
        if user_action == "OVERRIDE":
            epsilon_t += 0.8

        evidence_content = f"[{new_event.event_type.upper()}] Status:{status} Action:{user_action}"
        if epsilon_t > 0.5:
            evidence_content += " | OVERRIDE_ERROR"

        if new_event.occurred_at:
            try:
                dt = datetime.strptime(new_event.occurred_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        new_evidence = Evidence(
            event_id=event_id if (event_id := getattr(new_event, "event_id", "")) else "",
            content=evidence_content,
            source_type=new_event.source_type,
            timestamp=dt,
            weight=max(0.1, 1.0 - epsilon_t)
        )
        preference.evidences.append(new_evidence)
        
        return self.calculate(preference)