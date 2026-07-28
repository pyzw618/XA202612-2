"""
偏好抽取模块

从 MemoryEvent 中提取用户偏好，支持规则抽取和 LLM 辅助抽取，并结合 ConflictDecision 补全 Evidence 链。
"""

import json
import re
from datetime import datetime, timezone
from memoryhub.adapter.schemas import (
    Evidence,
    MemoryEvent,
    MemoryLevel,
    PreferenceMemory,
    PreferenceType,
    SceneScope,
    SourceType,
)


class PreferenceExtractor:
    """偏好抽取器"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """从单条事件中抽取候选偏好"""
        # 1. 规则抽取（硬约束及高显式指令拦截）
        candidates = self._rule_extract(event)
        if not candidates and event.quality.score >= 0.6:
            # 2. LLM 辅助抽取隐式偏好
            candidates = self._llm_extract(event)

        # 3. 补全证据链与通用属性
        for pref in candidates:
            if not pref.evidences:
                pref.evidences.append(self._build_evidence(event))
            if not pref.tags:
                pref.tags = self._extract_tags_from_text(pref.text)

        return candidates

def _rule_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """规则模板抽取（显式偏好 / 硬约束）"""
        if event.source_type not in [SourceType.USER_BEHAVIOR, SourceType.MANUAL_CONFIG]:
            return []

        text = event.text or str(event.payload.get("value", ""))
        if not text:
            return []

        candidates = []

        # 规则 A：输出格式偏好（增强：中英文修饰词 + 全局判定）
        pattern_format = (
            r"(以后|默认|每次|常规|随时|始终|一律|总是|长期|全局|所有场景|任何场景|任何地方|在任何地方|跨场景"
            r"|always|default|from now on|globally|everywhere|all scenarios|all contexts)"
            r".*(用|using|use)\s*(markdown|html|json|xml|csv)"
        )
        match = re.search(pattern_format, text, re.IGNORECASE)
        if match:
            prefix = match.group(1)
            target_format = match.group(3).upper()

            # 扩展后的全局判断
            global_keywords = [
                "全局", "所有场景", "任何场景", "任何地方", "在任何地方", "跨场景", "始终", "一律", "总是",
                "globally", "everywhere", "always", "all scenarios", "all contexts"
            ]
            is_global_pref = (
                any(kw in prefix.lower() for kw in global_keywords)
                or event.scene == "*"
            )

            pref = PreferenceMemory(
                user_id=event.user_id,
                preference_type=PreferenceType.FORMAT_PREF,
                text=f"偏好使用 {target_format} 格式进行数据输出。",
                payload={"action": "set_format", "target": "output_format", "value": target_format.lower()},
                scope=SceneScope(
                    scene="*" if is_global_pref else event.scene,
                    task_type="*" if is_global_pref else event.task_type,
                ),
                is_global=is_global_pref,
                confidence=0.95,
                quality_score=event.quality.score,
                extract_source="explicit_feedback",
                level=MemoryLevel.LONG,
                tags=[target_format.lower(), "format", "output"],
            )
            candidates.append(pref)

        # 规则 B：硬性隐私/安全约束（中英文全量拓展，使用 lower() 避免大小写漏匹配）
        privacy_keywords = [
            # 中文
            "不要记住", "别记录", "不要保存", "别存", "禁止记录", "禁止保存", "不准保存", "勿记", "擦除",
            "隐私", "安全", "保密", "机密", "敏感", "合规",
            "密码", "密钥", "token", "凭证", "身份证", "手机号", "信用卡", "银行卡", "地址", "轨迹", "位置",
            # 英文
            "don't remember", "do not record", "don't save", "never store", "privacy", "sensitive",
            "password", "secret", "api_key", "credential", "location", "token"
        ]
        if any(kw in text.lower() for kw in privacy_keywords):
            pref = PreferenceMemory(
                user_id=event.user_id,
                preference_type=PreferenceType.SAFETY_PREF,
                text="硬约束：任何时候都禁止在持久存储中保留敏感会话凭证及位置轨迹数据。",
                payload={"action": "restrict_storage", "target": "sensitive_data", "value": "forbidden"},
                scope=SceneScope(scene="*", task_type="*"),
                is_global=True,
                confidence=1.0,
                quality_score=event.quality.score,
                extract_source="explicit_feedback",
                level=MemoryLevel.LONG,
                tags=["privacy", "safety", "restriction"],
            )
            candidates.append(pref)

        return candidates

def _llm_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """LLM 辅助抽取（隐式偏好）：三代 GVR 循环"""
        if not self.llm_client:
            return []

        blacklist = {"date", "time", "timestamp", "location", "departure_date", "pickup_time"}
        clean_payload = {k: v for k, v in event.payload.items() if k not in blacklist}

        system_prompt = (
            "You are a Preference Abstraction Engine for an AI Agent.\n"
            "Identify user's high-level latent preference from behavioral context.\n"
            "Rules:\n"
            "1. Do NOT repeat raw parameters or mention temporary details.\n"
            "2. Output strictly JSON with keys: 'implicit_pref', 'preference_type', 'action_payload', 'tags', and optional 'is_global' (boolean, true if user explicitly asks for global/all-scenario applicability).\n"
        )

        allowed_types = "|".join([e.value for e in PreferenceType])
        user_prompt = f"""
Execution Context:
Event Source Type: {event.source_type}
Event Type: {event.event_type}
Event Text Summary: {event.text}
Cleaned content payload: {json.dumps(clean_payload)}
Outcome status: {event.payload.get("status", "SUCCESS")}

Output JSON format:
{{
  "implicit_pref": "Single sentence high-level preference description",
  "preference_type": "{allowed_types}",
  "action_payload": {{"action": "string", "target": "string", "value": "any"}},
  "tags": ["tag1", "tag2"],
  "is_global": false
}}
"""
        draft_content = ""
        verifier_feedback = ""
        loop_count = 0

        while loop_count < 3:
            loop_count += 1
            prompt_payload = user_prompt
            if draft_content and verifier_feedback:
                prompt_payload += f"\nPrevious Draft: {draft_content}\nVerifier Rejection: {verifier_feedback}\nRefine draft."

            try:
                response_text = self.llm_client.generate(system_prompt, prompt_payload)
                
                # 增强：防止 LLM 输出 Markdown json 块导致解析失败
                if "```" in response_text:
                    match = re.search(r"```(?:json)?\s*(.*?)\s*```", response_text, re.DOTALL)
                    if match:
                        response_text = match.group(1)

                parsed = json.loads(response_text)
                h_pref = parsed.get("implicit_pref", "")
                pref_type_str = parsed.get("preference_type", "output_style")
                action_payload = parsed.get("action_payload", {})
                extracted_tags = parsed.get("tags", [])
                
                # 增强：从 LLM 输出与原始文本/文本摘要中双重判断 is_global
                llm_is_global = bool(parsed.get("is_global", False))
                global_keywords = [
                    # 中文
                    "全局", "所有场景", "任何场景", "任何地方", "在任何地方", "跨场景", "始终", "一律", "总是",
                    # 英文
                    "globally", "everywhere", "always", "all scenarios", "all contexts"
                ]

                text_has_global_kw = any(
                    kw in (event.text or "").lower()
                    for kw in global_keywords
                )

                is_global_pref = llm_is_global or text_has_global_kw or event.scene == "*"

                # GVR 质量校验：避免过度具体化或提及临时槽位
                if len(h_pref) >= 8 and not any(slot in h_pref.lower() for slot in ["price_range", "flight_class", "="]):
                    return [
                        PreferenceMemory(
                            user_id=event.user_id,
                            preference_type=self._classify_type(pref_type_str),
                            text=h_pref,
                            payload=action_payload,
                            scope=SceneScope(
                                scene="*" if is_global_pref else event.scene,
                                task_type="*" if is_global_pref else event.task_type,
                            ),
                            is_global=is_global_pref,
                            confidence=0.75,
                            quality_score=event.quality.score,
                            extract_source="implicit_inference",
                            level=MemoryLevel.MID,
                            tags=extracted_tags if extracted_tags else self._extract_tags_from_text(h_pref),
                        )
                    ]
                else:
                    draft_content = h_pref
                    verifier_feedback = "over-specificity or lack of abstraction"
            except Exception:
                break

        return []

def _classify_type(self, text: str) -> PreferenceType:
        try:
            return PreferenceType(text)
        except ValueError:
            return PreferenceType.OUTPUT_STYLE

def _extract_tags_from_text(self, text: str) -> list[str]:
        words = re.findall(r"\b\w{3,}\b", text.lower())
        stopwords = {"using", "with", "from", "that", "this", "have", "preference", "default", "should"}
        return list(set([w for w in words if w not in stopwords]))[:5]

def _build_evidence(self, event: MemoryEvent) -> Evidence:
        if event.occurred_at:
            try:
                dt = datetime.strptime(event.occurred_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        return Evidence(
            event_id=getattr(event, "event_id", "") or "",
            content=f"[{event.event_type.upper()}] Source:{event.source_type.value} Quality:{event.quality.score:.2f}",
            source_type=event.source_type,
            timestamp=dt,
            weight=event.quality.score,
            decision=None,  # 初始提取的单条事件默认为 None，后续在 ConflictResolver 中标记冲突决策
        )