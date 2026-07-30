"""
事实记忆管线 — 候选分析与明确提交

  文本 → propose(): 提取 → 事实准入 → 事实候选（完全无数据库副作用）
       → commit(): 明确作用域 → 归一化 → 冲突检测/裁决 → 写入

兼容接口 ingest() 会自动执行 propose + commit。

用法:
    from memoryhub.core.fact import FactMemoryPipeline

    pipeline = FactMemoryPipeline(api_key="sk-xxx", db_path="facts.db")
    proposals = pipeline.propose(
        "项目A的负责人是张三。",
        project_id="project_a",
    )
    results = [pipeline.commit(p) for p in proposals if p.admission.should_remember]
    for r in results:
        print(f"{r.relation} → {r.resolution}: {r.reason}")
"""

import logging
from typing import Optional

# 默认开启日志，方便追踪每一步
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

from .models import (
    Fact, FactCandidate, FactProposal, ConflictResult, MemoryScope, Resolution,
)
from .admission import FactAdmissionPolicy
from .store import FactStore
from .extractor import TripleExtractor
from .normalizer import EntityNormalizer, PredicateNormalizer
from .conflict import ConflictDetector

logger = logging.getLogger(__name__)


class FactMemoryPipeline:
    """
    事实记忆管线。

    推荐入口:
      propose(text, ...) → list[FactCandidate]
      commit(candidate, ...) → ConflictResult

    兼容入口:
      ingest(text, ...) → list[ConflictResult]

    处理阶段:
      1. 提取: DeepSeek 提取 (S, P, O) 三元组
      2. 准入: 只保留适合本模块的客观事实
      3. 提交时归一化: 代码 alias 匹配 + LLM 兜底
      4. 提交时冲突处理: 同作用域代码查找 + 必要时 LLM 裁决
    """

    def __init__(
        self,
        api_key: str = "",
        db_path: str = ":memory:",
        ontology_path: Optional[str] = None,
        admission_policy: Optional[FactAdmissionPolicy] = None,
    ):
        """
        Args:
            api_key: DeepSeek API key
            db_path: SQLite 数据库路径
            ontology_path: 谓词本体 JSON 路径
        """
        self.store = FactStore(db_path)
        self.extractor = TripleExtractor(api_key=api_key)
        self.entity_norm = EntityNormalizer(self.store, api_key=api_key)
        self.pred_norm = PredicateNormalizer(self.store, ontology_path=ontology_path, api_key=api_key)
        self.detector = ConflictDetector(self.store, api_key=api_key)
        self.admission = admission_policy or FactAdmissionPolicy()

    def propose(
        self,
        text: str,
        source_id: str = "",
        project_id: Optional[str] = None,
        scope_hint: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> list[FactProposal]:
        """
        纯分析候选事实，不访问实体、谓词、事实表或向量索引。
        """
        logger.info(f"[propose] source={source_id}, text_len={len(text)}")
        raw_triples = self.extractor.extract(text, source_id)
        proposals: list[FactProposal] = []

        for rt in raw_triples:
            admission = self.admission.evaluate(
                rt, project_id=project_id, scope_hint=scope_hint,
            )
            proposals.append(FactCandidate(
                candidate_id=FactCandidate.make_id(),
                raw_triple=rt,
                admission=admission,
                source_id=source_id,
                project_id_hint=project_id,
                scope_hint=scope_hint,
                metadata=dict(metadata or {}),
            ))

        logger.info(
            f"[propose] 候选={len(proposals)}, "
            f"建议保存={sum(p.admission.should_remember for p in proposals)}"
        )
        return proposals

    def commit(
        self,
        proposal: FactProposal,
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
        resolution: Optional[str] = None,
        auto_resolve: bool = True,
        force: bool = False,
    ) -> ConflictResult:
        """明确提交一个候选事实，并执行同作用域冲突检测与写入。"""
        if not proposal.admission.should_remember and not force:
            raise ValueError(f"候选事实未通过准入判断: {proposal.admission.reason}")

        final_scope = scope or proposal.scope_hint or proposal.admission.suggested_scope
        if final_scope is None:
            raise ValueError("提交事实前必须明确指定 scope")
        final_project_id = project_id or proposal.project_id_hint
        if final_scope == MemoryScope.GLOBAL.value:
            final_project_id = None

        rt = proposal.raw_triple
        subj_id = self.entity_norm.normalize(rt.subject_text, rt.subject_type)
        pred_id = self.pred_norm.normalize(rt.predicate_text)
        obj_id = self.entity_norm.normalize(rt.object_text, rt.object_type)

        fact = Fact(
            fact_id=Fact.make_id(),
            subject_id=subj_id,
            predicate_id=pred_id,
            object_id=obj_id,
            object_value=rt.object_text,
            source_text=rt.evidence,
            source_id=proposal.source_id,
            observed_at=Fact.now_iso(),
            confidence=rt.confidence,
            scope=final_scope,
            project_id=final_project_id,
        )
        result = self.detector.check(fact)

        if result.relation == "CONFLICT":
            if resolution is not None:
                if resolution not in [r.value for r in Resolution]:
                    raise ValueError(f"不支持的冲突裁决: {resolution}")
                result.resolution = resolution
                result.reason = f"[调用方裁决] {result.reason}"
            elif auto_resolve:
                result = self.detector.resolve(result)
            else:
                result.resolution = Resolution.ESCALATE.value
                result.reason = f"[等待主Agent裁决] {result.reason}"

        self._apply(result)
        return result

    def ingest(
        self,
        text: str,
        source_id: str = "",
        project_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> list[ConflictResult]:
        """
        送入一段文本，返回所有三元组的冲突检测结果。

        Args:
            text: 原始文本（工具调用结果 / 用户发言 / 任意来源）
            source_id: 来源标识

        Returns:
            ConflictResult 列表
        """
        commit_scope = scope
        if commit_scope is None and project_id is None:
            commit_scope = MemoryScope.GLOBAL.value

        proposals = self.propose(
            text,
            source_id=source_id,
            project_id=project_id,
            scope_hint=commit_scope,
        )
        results: list[ConflictResult] = []
        for proposal in proposals:
            if not proposal.admission.should_remember:
                logger.info(
                    f"[ingest] 跳过候选 {proposal.proposal_id}: "
                    f"{proposal.admission.reason}"
                )
                continue
            results.append(self.commit(
                proposal,
                scope=commit_scope,
                project_id=project_id,
            ))

        # 统计
        counts = {}
        for r in results:
            key = f"{r.relation}"
            if r.resolution:
                key += f"→{r.resolution}"
            counts[key] = counts.get(key, 0) + 1
        logger.info(f"[ingest] 完成: {counts}, total={len(results)}")

        return results

    def _apply(self, result: ConflictResult):
        """根据检测 + 裁决结果写入 / 更新 store"""
        fact = result.new_fact

        if result.relation == "NEW":
            self.store.insert_fact(fact)

        elif result.relation == "DUPLICATE":
            pass  # 不重复写入

        elif result.relation == "COEXIST":
            self.store.insert_fact(fact)

        elif result.relation == "CONFLICT":
            action = result.resolution or Resolution.ESCALATE.value

            if action == Resolution.REPLACE.value:
                # 新事实取代旧，旧事实标记 superseded
                if result.existing_fact:
                    self.store.update_fact_status(result.existing_fact.fact_id, "superseded")
                self.store.insert_fact(fact)

            elif action == Resolution.KEEP_OLD.value:
                # 丢弃新事实
                pass

            elif action == Resolution.MERGE.value:
                # 合并：旧事实标记 superseded，新事实写入（带合并备注）
                if result.existing_fact:
                    self.store.update_fact_status(result.existing_fact.fact_id, "superseded")
                self.store.insert_fact(fact)

            elif action == Resolution.COEXIST.value:
                # 都保留
                self.store.insert_fact(fact)

            else:  # escalate
                fact.status = "disputed"
                self.store.insert_fact(fact)

    def get_facts(
        self,
        status: str = "active",
        limit: int = 100,
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> list[Fact]:
        return self.store.list_facts(
            status=status, limit=limit, scope=scope, project_id=project_id,
        )

    def get_effective_facts(
        self,
        project_id: Optional[str] = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[Fact]:
        """
        获取当前上下文的有效事实。

        项目单值事实覆盖相同 S+P 的全局事实；多值事实与全局事实合并。
        """
        global_facts = self.store.list_facts(
            status=status, limit=limit, scope=MemoryScope.GLOBAL.value,
        )
        if not project_id:
            return global_facts

        project_facts = self.store.list_facts(
            status=status,
            limit=limit,
            scope=MemoryScope.PROJECT.value,
            project_id=project_id,
        )
        project_keys = set()
        for fact in project_facts:
            predicate = self.store.get_predicate(fact.predicate_id)
            if predicate is None or predicate.single_value:
                project_keys.add((fact.subject_id, fact.predicate_id))

        inherited = [
            fact for fact in global_facts
            if (fact.subject_id, fact.predicate_id) not in project_keys
        ]
        return (project_facts + inherited)[:limit]

    def get_fact_by_id(self, fact_id: str) -> Optional[Fact]:
        return self.store.get_fact(fact_id)

    def close(self):
        self.store.close()
