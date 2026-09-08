"""Fact semantics layered on the project's Knowledge/Authority storage.

The package deliberately contains only semantic identifiers and rules.  It does
not introduce a second fact table or a second write path.
"""

from .models import Entity, EntityType, PredicateDef, FactDecisionRequired
from .normalizer import EntityNormalizer, PredicateNormalizer
from .conflict import FactConflictDetector, ConflictDetector
from .semantic import FactSemanticService, FactSemanticResult

__all__ = [
    "Entity", "EntityType", "PredicateDef", "FactDecisionRequired",
    "EntityNormalizer", "PredicateNormalizer", "FactConflictDetector", "ConflictDetector",
    "FactSemanticService", "FactSemanticResult",
]
