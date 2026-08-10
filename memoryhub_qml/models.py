from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, Qt, Signal, Slot


class DictListModel(QAbstractListModel):
    """Small deterministic list model used by the QML presentation layer."""

    countChanged = Signal()

    def __init__(self, roles: Iterable[str], parent=None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._roles = tuple(roles)
        self._role_ids = {
            int(Qt.ItemDataRole.UserRole) + offset + 1: role
            for offset, role in enumerate(self._roles)
        }

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802 - Qt virtual method
        return {role_id: name.encode("utf-8") for role_id, name in self._role_ids.items()}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt virtual method
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or index.row() < 0 or index.row() >= len(self._items):
            return None
        name = self._role_ids.get(role)
        return self._items[index.row()].get(name) if name else None

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._items)

    @Slot(int, result="QVariantMap")
    def get(self, index: int) -> dict[str, Any]:
        if 0 <= index < len(self._items):
            return dict(self._items[index])
        return {}

    def set_items(self, items: Iterable[Mapping[str, Any]]) -> None:
        self.beginResetModel()
        self._items = [dict(item) for item in items]
        self.endResetModel()
        self.countChanged.emit()

    def items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._items]


class TurnListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(("turnId", "number", "preview", "state", "selected"), parent)


class MessageListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(("speaker", "body", "turnId", "occurredAt", "pending"), parent)


class ToolCallListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "callId",
                "toolName",
                "status",
                "sequence",
                "latencyMs",
                "argumentsJson",
                "resultJson",
                "error",
            ),
            parent,
        )


class MemoryListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "memoryId",
                "memoryType",
                "knowledgeType",
                "title",
                "summary",
                "relevance",
                "source",
                "level",
                "scope",
                "tagsText",
                "used",
            ),
            parent,
        )


class FactProposalListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "proposalId",
                "subject",
                "predicate",
                "objectValue",
                "evidence",
                "confidence",
                "admissionReason",
                "suggestedScope",
                "status",
            ),
            parent,
        )


class PreferenceListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "memoryId",
                "preferenceType",
                "content",
                "confidence",
                "scopeText",
                "status",
                "level",
                "version",
                "createdAt",
                "updatedAt",
                "evidenceCount",
                "tagsText",
                "evidenceJson",
            ),
            parent,
        )


class KnowledgeListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "memoryId",
                "knowledgeType",
                "name",
                "content",
                "confidence",
                "successRate",
                "status",
                "level",
                "version",
                "createdAt",
                "scopeText",
                "steps",
                "tools",
                "toolsText",
                "evidenceCount",
            ),
            parent,
        )


class FactListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "factId",
                "subject",
                "predicate",
                "objectValue",
                "sourceText",
                "confidence",
                "status",
                "scope",
                "projectId",
                "createdAt",
            ),
            parent,
        )


class RetrievalListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "memoryId",
                "memoryType",
                "content",
                "score",
                "source",
            ),
            parent,
        )


class ConflictListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "conflictId",
                "oldContent",
                "newContent",
                "memoryType",
                "decision",
                "reason",
                "createdAt",
            ),
            parent,
        )


class ForgetListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "recordId",
                "instruction",
                "deletedCount",
                "createdAt",
            ),
            parent,
        )


class SafetyRuleListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "ruleId",
                "label",
                "kind",
                "effect",
                "enabled",
                "revision",
                "createdAt",
            ),
            parent,
        )


class EvalListModel(DictListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            (
                "taskName",
                "totalSamples",
                "accuracy",
                "f1",
                "avgLatencyMs",
            ),
            parent,
        )
