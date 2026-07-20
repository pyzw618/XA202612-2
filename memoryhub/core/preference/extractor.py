"""
偏好抽取模块

从 MemoryEvent 中提取用户偏好，支持规则抽取和 LLM 辅助抽取。
"""

import re
import json
from memoryhub.adapter.schemas import MemoryEvent, PreferenceMemory, PreferenceType, SceneScope, Evidence, EventType


class PreferenceExtractor:
    """
    偏好抽取器
    """

    def __init__(self, llm_client=None):
        """
        参数:
            llm_client: LLM 抽象客户端，用于辅助抽取隐式偏好
        """
        self.llm_client = llm_client

    def extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        从单条事件中抽取候选偏好
        """
        # 1. 规则抽取优先（硬约束及高显式指令拦截）
        candidates = self._rule_extract(event)
        if candidates:
            # 绑定证据并返回
            for pref in candidates:
                if not pref.evidences:
                    pref.evidences.append(self._build_evidence(event))
            return candidates

        # 2. 如果满足高可信标准，使用 LLM 辅助进行 Schema-Agnostic 隐式偏好提取
        if event.quality_score >= 0.6:
            llm_candidates = self._llm_extract(event)
            candidates.extend(llm_candidates)

        # 3. 补全缺失证据链
        for pref in candidates:
            if not pref.evidences:
                pref.evidences.append(self._build_evidence(event))

        return candidates

    def _rule_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        规则模板抽取（显式偏好 / 硬约束）
        """
        # 仅对显式配置及用户主动反馈的数据进行硬规则匹配
        if event.event_type not in [EventType.USER_FEEDBACK, EventType.MANUAL_CONFIG]:
            return []

        text = event.content.get("text", "") or event.content.get("value", "")
        if not isinstance(text, str) or not text:
            return []

        candidates = []

        # 规则 A：样式格式硬约束
        pattern_format = r"(以后|默认|每次).*用\s*(markdown|html|json|xml|csv)"
        match = re.search(pattern_format, text, re.IGNORECASE)
        if match:
            target_format = match.group(2).upper()
            pref = PreferenceMemory(
                user_id=event.user_id,
                preference_type=PreferenceType.FORMAT_PREF,
                content=f"偏好使用 {target_format} 格式进行数据输出。",
                scope=SceneScope(scene=event.scene, task_type=event.task_type),
                confidence=0.95
            )
            candidates.append(pref)

        # 规则 B：硬性隐私/安全过滤门
        if any(kw in text for kw in ["不要记住", "别记录", "隐私", "安全", "禁止"]):
            pref = PreferenceMemory(
                user_id=event.user_id,
                preference_type=PreferenceType.SAFETY_PREF,
                content="硬约束：任何时候都禁止在持久存储中保留敏感会话凭证及位置轨迹数据。",
                scope=SceneScope(scene="*", task_type="*"),
                confidence=1.0
            )
            candidates.append(pref)

        return candidates

    def _llm_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        LLM 辅助抽取(隐式偏好): 3次黄金迭代 GVR 收敛
        """
        if not self.llm_client:
            return []

        # 清除一次性临时时空约束（例如具体时间、地点、乘车日期等）
        blacklist = {"date", "time", "timestamp", "location", "departure_date", "pickup_time"}
        clean_content = {k: v for k, v in event.content.items() if k not in blacklist}

        system_prompt = (
            "You are a Preference Abstraction Engine for an AI Agent.\n"
            "Identify user's high-level latent preference (action constraint) from behavioral context.\n"
            "Rules:\n"
            "1. Do NOT repeat raw parameters/values or mention timestamps/locations.\n"
            "2. Generate abstract, schema-agnostic natural language description.\n"
            "3. Output strictly in JSON format with keys: 'implicit_pref' and 'preference_type'.\n"
        )

        allowed_types = "|".join([e.value for e in PreferenceType])

        user_prompt = f"""
Execution Context:
Event Type: {event.event_type}
Cleaned content payload: {json.dumps(clean_content)}
Outcome status: {event.metadata.get("status", "SUCCESS")}

Output format requirement:
{{
  "implicit_pref": "Single sentence high-level preference description",
  "preference_type": "{allowed_types}"
}}
"""

        draft_content = ""
        verifier_feedback = ""
        loop_count = 0

        # GVR (Generate-Verify-Refine) 3 次黄金循环
        while loop_count < 3:
            loop_count += 1
            prompt_payload = user_prompt
            if draft_content and verifier_feedback:
                prompt_payload += (
                    f"\nPrevious Draft: {draft_content}\n"
                    f"Verifier Rejection Feedback: {verifier_feedback}\n"
                    f"Please adjust the abstraction level and refine the draft."
                )

            try:
                response_text = self.llm_client.generate(system_prompt, prompt_payload)
                parsed = json.loads(response_text)
                h_pref = parsed.get("implicit_pref", "")
                pref_type_str = parsed.get("preference_type", "output_style")

                # Verifier 自校核逻辑
                is_valid = True
                feedback = ""

                # 校验点 1: 是否泄露了特定 slot-value 参数结构
                if any(slot in h_pref.lower() for slot in ["price_range", "car_type", "flight_class", "="]):
                    is_valid = False
                    feedback = "over-specificity: do not expose raw API slots or assign hardcoded parameter values."

                # 校验点 2: 长度及内容空洞化防线
                if len(h_pref) < 8 or "no preference" in h_pref.lower():
                    is_valid = False
                    feedback = "lack_of_abstraction: preference is vague and fails to restrict action choices."

                if is_valid:
                    return [PreferenceMemory(
                        user_id=event.user_id,
                        preference_type=self._classify_type(pref_type_str),
                        content=h_pref,
                        scope=SceneScope(scene=event.scene, task_type=event.task_type),
                        confidence=0.75
                    )]
                else:
                    draft_content = h_pref
                    verifier_feedback = feedback

            except Exception:
                break

        return []

    def _classify_type(self, text: str) -> PreferenceType:
        """对偏好文本进行类型分类"""
        try:
            return PreferenceType(text)
        except ValueError:
            return PreferenceType.OUTPUT_STYLE

    def _build_evidence(self, event: MemoryEvent) -> Evidence:
        """从事件构建证据链"""
        return Evidence(
            event_id=event.event_id,
            content=f"[{event.event_type.upper()}] Source:{event.source} Quality:{event.quality_score:.2f}",
            source_type=event.event_type,
            timestamp=event.timestamp,
            weight=event.quality_score
        )