"""
偏好置信度计算模块

根据证据数量、来源类型、用户反馈强度等因素计算偏好置信度。
"""

import math
from datetime import datetime, timezone
from memoryhub.adapter.schemas import PreferenceMemory, MemoryEvent, EventType, Evidence


class ConfidenceCalculator:
    """偏好置信度计算器"""

    # 来源类型权重
    SOURCE_WEIGHTS = {
        "explicit_feedback": 1.0,     # 用户显式反馈
        "manual_config": 0.95,        # 手动配置
        "repeated_behavior": 0.8,     # 重复行为
        "tool_result": 0.6,           # 工具调用结果
        "single_behavior": 0.4,       # 单次行为
    }

    def calculate(self, preference: PreferenceMemory) -> float:
        """
        计算偏好置信度
        """
        if not preference.evidences:
            return 0.0

        # 提取证据时间、来源属性
        timestamps = [e.timestamp for e in preference.evidences]
        sources = [e.source_type for e in preference.evidences]

        # 估算各项因子得分
        f_count = self._factor_evidence_count(len(preference.evidences))
        f_source = self._factor_source_type(sources)
        f_time = self._factor_time_decay(timestamps)
        f_consistency = self._factor_consistency(preference)

        # 结合基础衰减强度
        raw_score = f_source * f_time * f_consistency * (1.0 + 0.15 * f_count)

        # 计算成事偏差消减惩罚（如用户覆写或妥协标记）
        neg_penalty = 0.0
        for e in preference.evidences:
            if e.content and "OVERRIDE" in e.content:
                neg_penalty += 0.25 * e.weight
            elif e.content and "COMPROMISE" in e.content:
                neg_penalty += 0.10 * e.weight

        # 贝叶斯平滑转换，限制边界在 [0.0, 1.0] 之间
        final_confidence = (1.0 / (1.0 + math.exp(-3.0 * (raw_score - 0.5)))) - neg_penalty
        preference.confidence = max(0.0, min(1.0, final_confidence))
        
        return preference.confidence

    def _factor_evidence_count(self, evidence_count: int) -> float:
        """证据数量因子：利用对数公式实现边际收益递减"""
        if evidence_count <= 0:
            return 0.0
        return math.log(1 + evidence_count)

    def _factor_source_type(self, sources: list[str]) -> float:
        """来源类型因子：由置信度最高的来源主导评分基准"""
        max_weight = 0.4
        for s in sources:
            if s == EventType.USER_FEEDBACK:
                weight = self.SOURCE_WEIGHTS["explicit_feedback"]
            elif s == EventType.MANUAL_CONFIG:
                weight = self.SOURCE_WEIGHTS["manual_config"]
            elif s == EventType.TOOL_CALL:
                weight = self.SOURCE_WEIGHTS["tool_result"]
            else:
                weight = self.SOURCE_WEIGHTS["single_behavior"]
            
            if weight > max_weight:
                max_weight = weight
        return max_weight

    def _factor_time_decay(self, timestamps: list) -> float:
        """时间衰减因子:距离现在越久,证据信度呈指数衰减(14天半衰期)"""
        if not timestamps:
            return 1.0
        
        now = datetime.now(timezone.utc)
        half_life_days = 14.0
        total_decay = 0.0
        
        for t in timestamps:
            # 确保进行时区防御擦除或对齐以防报错
            t_naive = t.replace(tzinfo=None) if t.tzinfo else t
            now_naive = now.replace(tzinfo=None)
            diff_days = (now_naive - t_naive).total_seconds() / 86400.0
            decay = math.exp(-diff_days / half_life_days)
            total_decay += decay
            
        return total_decay / len(timestamps)

    def _factor_consistency(self, preference: PreferenceMemory) -> float:
        """一致性因子：若历史成效多为正向(SUCCESS)则提供增益，频繁被纠偏则施加高惩罚"""
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
        """
        增量更新置信度:引入言语成事成效偏差梯度(Speech Act Bias)
        """
        epsilon_t = 0.0
        status = new_event.metadata.get("status", "")
        user_action = new_event.metadata.get("user_action", "")

        # 行事与成事冲突程度度量
        if status in ["USER_REJECT", "API_FAIL"]:
            epsilon_t += 0.3
        if user_action == "OVERRIDE":
            epsilon_t += 0.8  # 用户被迫纠错，偏差极大

        # 组装新证据摘要并挂载
        evidence_content = f"[{new_event.event_type.upper()}] Status:{status} Action:{user_action}"
        if epsilon_t > 0.5:
            evidence_content += " | OVERRIDE_ERROR"
            
        new_evidence = Evidence(
            event_id=new_event.event_id,
            content=evidence_content,
            source_type=new_event.event_type,
            timestamp=new_event.timestamp,
            weight=max(0.1, 1.0 - epsilon_t)
        )
        preference.evidences.append(new_evidence)
        
        return self.calculate(preference)