"""
偏好更新与持久化/中长期版本管理器

包含冲突检测 (ConflictDetector)、冲突解决策略 (ConflictResolver) 及版本管理链。
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    ConflictDecision,
    ConflictRecord,
    MemoryDecision,
    MemoryStatus,
    PreferenceMemory,
)
from memoryhub.core.memory.evidence import EvidenceMerger
from memoryhub.core.preference.confidence import ConfidenceCalculator

logger = logging.getLogger(__name__)


def _normalize_target(target: str) -> str:
    """Normalize a target string for fuzzy comparison."""
    return re.sub(r"[_\-]+", "", target.strip().lower())


def _fuzzy_target_match(left_target: str, right_target: str) -> bool:
    """Check whether two target strings plausibly refer to the same domain.

    Rules (in order):
    1. Exact match after normalisation
    2. One is a prefix of the other (e.g. "food" / "food_flavor")
    3. Longest common root >= 60% of the shorter token
    4. Token overlap: if the shorter target's tokens all appear in the longer one
    """
    ln = _normalize_target(left_target)
    rn = _normalize_target(right_target)
    if ln == rn:
        return True
    if ln.startswith(rn) or rn.startswith(ln):
        return True
    shorter, longer = (ln, rn) if len(ln) <= len(rn) else (rn, ln)
    min_len = len(shorter)
    if min_len == 0:
        return False
    common = 0
    for a, b in zip(shorter, longer):
        if a == b:
            common += 1
        else:
            break
    if common / min_len >= 0.6:
        return True
    left_tokens = set(re.split(r"[_\- ]+", left_target.lower()))
    right_tokens = set(re.split(r"[_\- ]+", right_target.lower()))
    left_tokens.discard("")
    right_tokens.discard("")
    if left_tokens and right_tokens:
        shorter_tokens = left_tokens if len(left_tokens) <= len(right_tokens) else right_tokens
        longer_tokens = right_tokens if len(left_tokens) <= len(right_tokens) else left_tokens
        if shorter_tokens.issubset(longer_tokens):
            return True
    return False


class ConflictDetector:
    """冲突检测器"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def check_preference(
        self, old_pref: PreferenceMemory, new_pref: PreferenceMemory
    ) -> bool:
        """
        判断两条偏好是否构成冲突：
        1. scope 重叠
        2. preference_type 相同
        3. 内容语义矛盾
        """
        scope_overlap = (
            old_pref.is_global
            or new_pref.is_global
            or (
                (
                    old_pref.scope.scene in ["*", new_pref.scope.scene]
                    or new_pref.scope.scene in ["*", old_pref.scope.scene]
                )
                and (
                    old_pref.scope.task_type in ["*", new_pref.scope.task_type]
                    or new_pref.scope.task_type in ["*", old_pref.scope.task_type]
                )
            )
        )
        if not scope_overlap:
            return False

        if old_pref.preference_type != new_pref.preference_type:
            return False

        return self._is_semantic_conflict(old_pref, new_pref)

    def _is_semantic_conflict(
        self, old_pref: PreferenceMemory, new_pref: PreferenceMemory
    ) -> bool:
        """检测语义冲突"""
        old_target = old_pref.payload.get("target", "")
        new_target = new_pref.payload.get("target", "")
        if old_target == new_target:
            if old_pref.payload.get("value") != new_pref.payload.get("value"):
                return True
        elif old_target and new_target:
            from memoryhub.core.preference.updater import _fuzzy_target_match

            if not _fuzzy_target_match(old_target, new_pref.payload.get("target", "")):
                if not self._llm_targets_same_domain(old_pref, new_pref):
                    return False

        if self.llm_client:
            prompt = (
                "Compare these two user preferences and return true if they logically "
                "contradict each other:\n"
                f"Preference A: {old_pref.text}\n"
                f"Preference B: {new_pref.text}\n"
                f'Respond with JSON: {{"conflict": true/false}}'
            )
            try:
                res = self.llm_client.generate(
                    prompt, system_prompt="You are a semantic evaluator."
                )
                content = res.content if hasattr(res, "content") else str(res)
                return json.loads(content).get("conflict", False)
            except Exception:
                pass

        negation_words = {"不要", "禁止", "不", "no", "never", "avoid"}
        has_neg_a = any(w in old_pref.text for w in negation_words)
        has_neg_b = any(w in new_pref.text for w in negation_words)
        return has_neg_a != has_neg_b

    def _llm_targets_same_domain(
        self, old_pref: PreferenceMemory, new_pref: PreferenceMemory
    ) -> bool:
        """Ask LLM whether two target labels belong to the same domain."""
        if not self.llm_client:
            return False
        old_target = old_pref.payload.get("target", "")
        new_target = new_pref.payload.get("target", "")
        prompt = (
            "Do these two target labels refer to the same or overlapping domain?\n"
            f"Target A: {old_target}\n"
            f"Target B: {new_target}\n"
            f'Context A: {old_pref.text}\n'
            f'Context B: {new_pref.text}\n'
            f'Respond with JSON: {{"same_domain": true/false}}'
        )
        try:
            res = self.llm_client.generate(
                prompt, system_prompt="You are a domain classification assistant."
            )
            content = res.content if hasattr(res, "content") else str(res)
            result = json.loads(content).get("same_domain", False)
            logger.debug(
                "LLM target domain check: %s vs %s -> %s", old_target, new_target, result
            )
            return result
        except Exception:
            logger.debug("LLM target domain check failed, falling back to false")
            return False


class ConflictResolver:
    """冲突解决策略执行器"""

    def auto_resolve(
        self,
        old_pref: PreferenceMemory,
        new_pref: PreferenceMemory,
        detector: ConflictDetector,
    ) -> tuple[ConflictDecision, str]:
        """
        执行决策矩阵：
        1. scope 不同 -> COEXIST
        2. 内容相同（支持性证据）-> MERGE
        3. 新记忆来源 = explicit_feedback 且内容冲突 -> OVERRIDE
        4. 新旧内容互补/不冲突 -> MERGE
        5. 隐式推理冲突且置信度较低 -> PENDING
        """
        same_scope = (
            old_pref.scope.scene == new_pref.scope.scene
            and old_pref.scope.task_type == new_pref.scope.task_type
        )
        if not same_scope and not old_pref.is_global and not new_pref.is_global:
            return (
                ConflictDecision.COEXIST,
                "Scopes differ; both preferences can coexist.",
            )

        if self._is_same_content(old_pref, new_pref):
            return (
                ConflictDecision.MERGE,
                "Identical preference reinforced by new evidence.",
            )

        if not detector.check_preference(old_pref, new_pref):
            return (
                ConflictDecision.MERGE,
                "Preferences are compatible; reinforce evidence before changing content.",
            )

        if new_pref.extract_source == "explicit_feedback":
            return (
                ConflictDecision.OVERRIDE,
                "Explicit feedback conflicts with the same preference target.",
            )

        if (
            new_pref.extract_source == "implicit_inference"
            and new_pref.confidence < 0.8
        ):
            return (
                ConflictDecision.PENDING,
                "Implicit preference contradiction requires user confirmation.",
            )

        return (
            ConflictDecision.OVERRIDE,
            "Newer implicit preference overrides older record.",
        )

    @staticmethod
    def _is_same_content(left: PreferenceMemory, right: PreferenceMemory) -> bool:
        """判断两条偏好是否表达相同内容（用于识别支持性证据而非冲突）。"""
        left_target = left.payload.get("target")
        right_target = right.payload.get("target")
        if left_target and right_target:
            if left_target == right_target:
                return left.payload.get("value") == right.payload.get("value")
            if _fuzzy_target_match(left_target, right_target):
                return left.payload.get("value") == right.payload.get("value")
        return left.text.strip().lower() == right.text.strip().lower()


class PreferenceUpdater:
    """偏好更新与持久化/中长期版本管理器"""

    def __init__(
        self,
        llm_client=None,
        db_client=None,
        pref_repo=None,
        conflict_repo=None,
        write_service=None,
        confidence_calculator=None,
    ):
        self.detector = ConflictDetector(llm_client=llm_client)
        self.resolver = ConflictResolver()
        self.db_client = db_client
        self.pref_repo = pref_repo
        self.conflict_repo = conflict_repo
        self.write_service = write_service
        self.confidence_calculator = confidence_calculator or ConfidenceCalculator()
        self._mock_db: dict[str, PreferenceMemory] = {}

    def add(
        self, preference: PreferenceMemory, *, skip_write_gate: bool = False
    ) -> str:
        """新增或更新偏好"""
        # 查找当前活跃的候选旧偏好
        existing_pref = self._find_existing(preference)

        if not existing_pref:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self.confidence_calculator.calculate(preference)
            self._save(preference, action=MemoryDecision.NEW, skip_write_gate=skip_write_gate)
            return preference.memory_id

        # 触发冲突检测与解决
        decision, reason = self.resolver.auto_resolve(
            existing_pref, preference, self.detector
        )

        for e in preference.evidences:
            if e.decision is None:
                e.decision = decision

        # 确定性 conflict_id：同一冲突对再次被检测到时更新既有记录，
        # 而不是插入重复行（与 KnowledgeUpdater._record_ambiguous_conflict 对齐）。
        conflict_digest = hashlib.sha256(
            f"{preference.user_id}|{existing_pref.memory_id}|{preference.memory_id}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        conflict_rec = ConflictRecord(
            conflict_id=f"conf_pref_{conflict_digest}",
            user_id=preference.user_id,
            old_memory_id=existing_pref.memory_id,
            new_memory_id=preference.memory_id,
            memory_type="preference",
            old_content=existing_pref.text,
            new_content=preference.text,
            decision=decision,
            reason=reason,
        )

        if decision == ConflictDecision.OVERRIDE:
            return self.update(
                existing_pref.memory_id,
                preference,
                conflict_rec,
                skip_write_gate=skip_write_gate,
            )

        elif decision == ConflictDecision.MERGE:
            if ConflictResolver._is_same_content(existing_pref, preference):
                self._reinforce(existing_pref, preference)
                self._save(
                    existing_pref,
                    action=MemoryDecision.REINFORCE,
                    skip_write_gate=skip_write_gate,
                )
                self._record_conflict(conflict_rec, existing_pref.memory_id)
                return existing_pref.memory_id
            merged = self.merge(existing_pref, preference)
            self._save(
                existing_pref,
                new_status=MemoryStatus.ARCHIVED,
                action=MemoryDecision.REVISE,
                skip_write_gate=skip_write_gate,
            )
            self._save(
                merged,
                action=MemoryDecision.REVISE,
                skip_write_gate=skip_write_gate,
            )
            self._record_conflict(conflict_rec, merged.memory_id)
            return merged.memory_id

        elif decision == ConflictDecision.COEXIST:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self.confidence_calculator.calculate(preference)
            self._save(
                preference,
                action=MemoryDecision.COEXIST,
                skip_write_gate=skip_write_gate,
            )
            self._record_conflict(conflict_rec, preference.memory_id)
            return preference.memory_id

        else:
            # PENDING: 保存待确认
            preference.status = MemoryStatus.PENDING
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self.confidence_calculator.calculate(preference)
            self._save(
                preference,
                action=MemoryDecision.REVIEW,
                skip_write_gate=skip_write_gate,
            )
            self._record_conflict(conflict_rec, preference.memory_id)
            return preference.memory_id

    def _reinforce(
        self, existing: PreferenceMemory, incoming: PreferenceMemory
    ) -> None:
        """Keep an unchanged preference active and attach independent evidence."""
        existing.evidences = self._merge_evidences(
            existing.evidences, incoming.evidences
        )
        existing.quality_score = max(existing.quality_score, incoming.quality_score)
        existing.updated_at = datetime.now(timezone.utc)
        self.confidence_calculator.calculate(existing)

    def update(
        self, memory_id: str, new_pref: PreferenceMemory, conflict_rec=None,
        *, skip_write_gate: bool = False,
    ) -> str:
        """更新已有偏好"""
        old_pref = self._get(memory_id)
        if old_pref is None:
            # 找不到旧偏好，作为新记录保存
            new_pref.status = MemoryStatus.ACTIVE
            new_pref.created_at = datetime.now(timezone.utc)
            new_pref.updated_at = datetime.now(timezone.utc)
            self._save(new_pref, action=MemoryDecision.NEW, skip_write_gate=skip_write_gate)
            return new_pref.memory_id

        # 旧偏好归档，新偏好设为活跃
        old_pref.status = MemoryStatus.ARCHIVED
        old_pref.updated_at = datetime.now(timezone.utc)
        self._save(old_pref, action=MemoryDecision.SUPERSEDE, skip_write_gate=skip_write_gate)
        new_pref.status = MemoryStatus.ACTIVE
        new_pref.parent_id = old_pref.memory_id
        new_pref.root_id = old_pref.root_id or old_pref.memory_id
        new_pref.version = old_pref.version + 1
        new_pref.updated_at = datetime.now(timezone.utc)
        # 继承旧证据链并保留新证据，交由置信度计算器基于完整证据链重算
        new_pref.evidences = self._merge_evidences(
            old_pref.evidences, new_pref.evidences
        )
        self.confidence_calculator.calculate(new_pref)
        self._save(new_pref, action=MemoryDecision.SUPERSEDE, skip_write_gate=skip_write_gate)
        if conflict_rec is not None:
            self._record_conflict(conflict_rec, new_pref.memory_id)

        return new_pref.memory_id

    def merge(
        self, pref_a: PreferenceMemory, pref_b: PreferenceMemory
    ) -> PreferenceMemory:
        """Create a new active version without mutating the archived parent."""
        merged = pref_b.model_copy(deep=True)
        merged.parent_id = pref_a.memory_id
        merged.root_id = pref_a.root_id or pref_a.memory_id
        merged.version = pref_a.version + 1
        merged.status = MemoryStatus.ACTIVE
        merged.evidences = self._merge_evidences(pref_a.evidences, pref_b.evidences)
        merged.created_at = datetime.now(timezone.utc)
        merged.updated_at = datetime.now(timezone.utc)
        self.confidence_calculator.calculate(merged)
        return merged

    @staticmethod
    def _merge_evidences(left: list, right: list) -> list:
        """Compatibility wrapper around the shared deterministic evidence merger."""
        return EvidenceMerger().normalize_and_merge([*left, *right])

    def archive(self, memory_id: str):
        """归档偏好"""
        pref = self._get(memory_id)
        if pref is not None:
            pref.status = MemoryStatus.ARCHIVED
            pref.updated_at = datetime.now(timezone.utc)
            self._save(pref, action=MemoryDecision.SUPERSEDE)

    def get_version_chain(self, memory_id: str) -> list[PreferenceMemory]:
        """获取版本链"""
        if self.pref_repo is not None:
            return self.pref_repo.get_version_chain(memory_id)
        current = self._mock_db.get(memory_id)
        chain: list[PreferenceMemory] = []
        visited: set[str] = set()
        while current is not None and current.memory_id not in visited:
            chain.append(current)
            visited.add(current.memory_id)
            current = (
                self._mock_db.get(current.parent_id) if current.parent_id else None
            )
        chain.reverse()
        return chain

    def _find_existing(self, preference: PreferenceMemory):
        """Find only a comparable active preference; never use type/scope alone."""
        if self.pref_repo is not None:
            candidates = self.pref_repo.get_active(preference.user_id)
        else:
            candidates = [
                pref
                for pref in self._mock_db.values()
                if pref.user_id == preference.user_id
                and pref.status == MemoryStatus.ACTIVE
            ]
        for pref in candidates:
            if pref.preference_type != preference.preference_type:
                continue
            if not self._scope_overlaps(pref, preference):
                continue
            if self._same_preference_target(pref, preference):
                logger.info(
                    "find_existing: fuzzy match %s[%s] <-> %s[%s]",
                    pref.memory_id,
                    pref.payload.get("target"),
                    preference.memory_id,
                    preference.payload.get("target"),
                )
                return pref
            if self._llm_targets_same_domain(pref, preference):
                logger.info(
                    "find_existing: LLM domain match %s[%s] <-> %s[%s]",
                    pref.memory_id,
                    pref.payload.get("target"),
                    preference.memory_id,
                    preference.payload.get("target"),
                )
                return pref
        logger.info(
            "find_existing: no match for %s[%s] among %d candidates",
            preference.memory_id,
            preference.payload.get("target"),
            len(candidates),
        )
        return None

    def _llm_targets_same_domain(
        self, left: PreferenceMemory, right: PreferenceMemory
    ) -> bool:
        """Use LLM to check whether two preferences target the same domain."""
        if not self.detector.llm_client:
            return False
        return self.detector._llm_targets_same_domain(left, right)

    @staticmethod
    def _scope_overlaps(left: PreferenceMemory, right: PreferenceMemory) -> bool:
        return (
            left.is_global
            or right.is_global
            or (
                (
                    left.scope.scene in ("*", right.scope.scene)
                    or right.scope.scene in ("*", left.scope.scene)
                )
                and (
                    left.scope.task_type in ("*", right.scope.task_type)
                    or right.scope.task_type in ("*", left.scope.task_type)
                )
            )
        )

    @staticmethod
    def _same_preference_target(
        left: PreferenceMemory, right: PreferenceMemory
    ) -> bool:
        left_target = str(left.payload.get("target", "")).strip()
        right_target = str(right.payload.get("target", "")).strip()
        if left_target or right_target:
            if left_target == right_target:
                return True
            if left_target and right_target:
                return _fuzzy_target_match(left_target, right_target)
        return left.text.strip().casefold() == right.text.strip().casefold()

    def _get(self, memory_id: str):
        """获取偏好"""
        if self.pref_repo is not None:
            return self.pref_repo.get_by_id(memory_id)
        return self._mock_db.get(memory_id)

    def _record_conflict(self, conflict: ConflictRecord, result_id: str) -> None:
        conflict.result_memory_id = result_id
        if conflict.decision != ConflictDecision.PENDING:
            conflict.resolved_at = datetime.now(timezone.utc)
        if self.conflict_repo is not None:
            self.conflict_repo.save(conflict)

    def _save(
        self,
        preference: PreferenceMemory,
        new_status=None,
        *,
        action: MemoryDecision | str | None = None,
        skip_write_gate: bool = False,
    ):
        """Persist and synchronize one preference version with its domain action."""
        if new_status is not None:
            preference.status = new_status
        if self.write_service is not None:
            self.write_service.upsert_memory(
                preference, action=action, skip_write_gate=skip_write_gate
            )
        elif self.pref_repo is not None:
            self.pref_repo.save(preference)
        else:
            self._mock_db[preference.memory_id] = preference
