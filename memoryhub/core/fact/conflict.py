"""
冲突检测模块

两阶段：
1. check() — 代码快速查找冲突（不调 LLM）
   无已有 → NEW
   有已有+同object_id → DUPLICATE
   有已有+不同object_id → CONFLICT（触发阶段 2）
2. resolve() — LLM 裁决冲突（replace / keep_old / merge / coexist / escalate）
"""

import json
import logging

from memoryhub.core.memory.llm import StructuredLLMAdapter

from .llm import build_chat_client
from .models import ConflictResult, Fact, Resolution
from .prompts import CONFLICT_RESOLVE_SYSTEM, CONFLICT_RESOLVE_USER
from .store import FactStore

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = ""
DEFAULT_MODEL = ""


class ConflictDetector:
    """写时冲突检测 + LLM 裁决"""

    def __init__(self, store: FactStore, api_key: str = "", llm_client=None):
        self.store = store
        self._llm = build_chat_client(
            api_key=api_key, llm_client=llm_client, base_url=DEFAULT_BASE_URL
        )
        self._adapter = (
            StructuredLLMAdapter(llm_client)
            if callable(getattr(llm_client, "generate", None))
            else None
        )

    # ─── 阶段 1: 代码检测（不调 LLM）─────────────────────────────────

    def check(self, fact: Fact) -> ConflictResult:
        """
        代码快速查找冲突。只返回 NEW / DUPLICATE / CONFLICT。

        CONFLICT 的 relation 表示"客体不同，需要 LLM 裁决"。
        """
        predicate = self.store.get_predicate(fact.predicate_id)
        if predicate is None:
            return ConflictResult(
                relation="NEW",
                new_fact=fact,
                reason=f"未知谓词 '{fact.predicate_id}'，按新事实处理",
            )

        existing = self.store.find_facts_by_sp(
            fact.subject_id,
            fact.predicate_id,
            scope=fact.scope,
            project_id=fact.project_id,
            user_id=fact.user_id,
        )

        if not existing:
            return ConflictResult("NEW", fact, reason="新事实，无已有记录")

        # 多值谓词：检查完全重复，否则共存
        if not predicate.single_value:
            for old in existing:
                if (
                    old.object_id == fact.object_id
                    and old.object_value == fact.object_value
                ):
                    return ConflictResult(
                        "DUPLICATE",
                        fact,
                        old,
                        reason=f"与已有事实完全相同（谓词 '{predicate.canonical_name}' 允许多值）",
                    )
            return ConflictResult(
                "COEXIST",
                fact,
                existing[0],
                reason=f"谓词 '{predicate.canonical_name}' 允许多值，新值可共存",
            )

        # 单值谓词
        for old in existing:
            if old.object_id == fact.object_id:
                return ConflictResult(
                    "DUPLICATE",
                    fact,
                    old,
                    reason=f"相同主体、谓词、客体（已有: {old.object_value}）",
                )

        old_strs = [f"{o.object_value} (id={o.object_id})" for o in existing]
        return ConflictResult(
            "CONFLICT",
            fact,
            existing[0],
            reason=(
                f"单值谓词 '{predicate.canonical_name}' 冲突: "
                f"已有={', '.join(old_strs)}, 新={fact.object_value}"
            ),
        )

    # ─── 阶段 2: LLM 裁决（仅 CONFLICT 时调用）────────────────────────

    def resolve(self, result: ConflictResult) -> ConflictResult:
        """
        LLM 裁决冲突。
        根据新旧事实的来源、时间、置信度，决定: replace / keep_old / merge / coexist / escalate
        """
        if result.relation != "CONFLICT":
            return result

        new = result.new_fact
        old = result.existing_fact
        if old is None:
            result.resolution = Resolution.REPLACE.value
            return result

        # 获取可读名称
        subj_ent = self.store.get_entity(new.subject_id)
        pred_def = self.store.get_predicate(new.predicate_id)

        subject_name = subj_ent.canonical_name if subj_ent else new.subject_id
        subject_type = subj_ent.entity_type if subj_ent else "Unknown"
        predicate_name = pred_def.canonical_name if pred_def else new.predicate_id

        user_msg = CONFLICT_RESOLVE_USER.format(
            subject_name=subject_name,
            subject_type=subject_type,
            predicate_name=predicate_name,
            old_object_value=old.object_value,
            old_source_text=old.source_text,
            old_observed_at=old.observed_at,
            old_confidence=old.confidence,
            new_object_value=new.object_value,
            new_source_text=new.source_text,
            new_observed_at=new.observed_at,
            new_confidence=new.confidence,
        )

        try:
            if self._adapter is not None:
                data = self._adapter.generate_json(
                    task_name="fact_conflict_resolution",
                    system_prompt=CONFLICT_RESOLVE_SYSTEM,
                    prompt=user_msg,
                    parser=lambda value: (
                        value
                        if isinstance(value, dict)
                        else (_ for _ in ()).throw(
                            ValueError("LLM JSON response must be an object")
                        )
                    ),
                )
            else:
                response = self._llm.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[
                        {"role": "system", "content": CONFLICT_RESOLVE_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                    max_tokens=256,
                )
                raw = response.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.strip("`").removeprefix("json").strip()
                data = json.loads(raw)

            action = str(data.get("action", Resolution.ESCALATE.value)).strip()
            reason = str(data.get("reason", "")).strip()
            allowed_actions = {item.value for item in Resolution}
            if action not in allowed_actions:
                action = Resolution.ESCALATE.value
                reason = f"invalid_llm_action; {reason}".strip()
            result.resolution = action
            result.reason = f"[LLM裁决] {reason}"
            logger.info(f"冲突裁决: {action} — {reason}")

        except Exception as e:
            logger.warning(f"LLM 冲突裁决失败: {e}，默认 escalate")
            result.resolution = Resolution.ESCALATE.value
            result.reason = f"[裁决失败，升级人工] {result.reason}"

        return result
