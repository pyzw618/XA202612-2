"""
memoryhub.core.fact — 三元组事实记忆与冲突检测模块

推荐采用两阶段调用:
  1. propose(): 纯提取与事实准入，不访问数据库
  2. commit(): 主 Agent 明确确认后归一化、检测冲突并写入

ingest() 保留为自动 propose + commit 的兼容接口。

用法:
    from memoryhub.core.fact import FactMemoryPipeline

    pipeline = FactMemoryPipeline(api_key="sk-xxx", db_path="facts.db")
    proposals = pipeline.propose(
        "项目A的负责人是张三。",
        project_id="project_a",
    )
"""

from .models import (
    Entity, PredicateDef, RawTriple, Fact, FactCandidate, FactProposal,
    FactAdmissionDecision, ConflictResult, EntityType, MemoryScope, Resolution,
)
from .admission import FactAdmissionPolicy
from .store import FactStore
from .extractor import TripleExtractor
from .normalizer import EntityNormalizer, PredicateNormalizer
from .conflict import ConflictDetector
from .pipeline import FactMemoryPipeline
from .event_adapter import FactIngestionAdapter
from .index_service import FactIndexService

__all__ = [
    "Entity", "PredicateDef", "RawTriple", "Fact", "FactCandidate", "FactProposal",
    "FactAdmissionDecision", "ConflictResult",
    "EntityType", "MemoryScope", "Resolution",
    "FactAdmissionPolicy",
    "FactStore",
    "TripleExtractor",
    "EntityNormalizer", "PredicateNormalizer",
    "ConflictDetector",
    "FactMemoryPipeline",
    "FactIngestionAdapter",
    "FactIndexService",
]
