"""
Memory Store — 数据存储层。

管理记忆条目的增删查，是 BM25 + FAISS 共用的数据源。
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MemoryRecord:
    """单条记忆记录。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str = ""                    # 原始文本
    embedding: Optional[List[float]] = None  # 向量（由 Embedding SDK 生成后回填）
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class MemoryStore:
    """
    内存级记忆存储（后续可替换为 SQLite / 向量数据库）。
    """

    def __init__(self):
        self._records: List[MemoryRecord] = []

    def add(self, content: str, embedding: Optional[List[float]] = None, metadata: Optional[dict] = None) -> MemoryRecord:
        """添加一条记忆。"""
        record = MemoryRecord(
            content=content,
            embedding=embedding,
            metadata=metadata or {},
        )
        self._records.append(record)
        return record

    def add_batch(self, items: List[dict]) -> List[MemoryRecord]:
        """批量添加。每项: {content, embedding?, metadata?}"""
        records = []
        for item in items:
            records.append(self.add(
                content=item["content"],
                embedding=item.get("embedding"),
                metadata=item.get("metadata"),
            ))
        return records

    def get_by_id(self, record_id: str) -> Optional[MemoryRecord]:
        """按 ID 查找。"""
        for r in self._records:
            if r.id == record_id:
                return r
        return None

    def get_all(self) -> List[MemoryRecord]:
        """返回全部记录。"""
        return list(self._records)

    def delete(self, record_id: str) -> bool:
        """按 ID 删除。返回是否删除成功。"""
        for i, r in enumerate(self._records):
            if r.id == record_id:
                self._records.pop(i)
                return True
        return False

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return f"<MemoryStore records={len(self._records)}>"
