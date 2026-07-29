"""
证据链存储

以 JSONL 格式存储证据链，支持追加写入和按 ID 查询。
"""

from memoryhub.adapter.schemas import Evidence


class EvidenceStore:
    """
    证据链存储器（JSONL 文件）

    使用方式:
        store = EvidenceStore("data/evidence")
        store.save("mem_001", evidence)
        evidences = store.load("mem_001")
    """

    def __init__(self, base_path: str = "data/evidence"):
        """
        参数:
            base_path: 证据文件存储目录
        """
        self.base_path = base_path

    def save(self, memory_id: str, evidence: Evidence) -> None:
        """
        追加保存一条证据

        数据流: 记忆写入 → 绑定证据 → save → JSONL 追加

        参数:
            memory_id: 关联的记忆 ID
            evidence: 证据对象
        """
        raise NotImplementedError

    def batch_save(self, memory_id: str, evidences: list[Evidence]) -> None:
        """批量保存证据"""
        raise NotImplementedError

    def load(self, memory_id: str) -> list[Evidence]:
        """
        加载某条记忆的所有证据

        参数:
            memory_id: 记忆 ID

        返回:
            Evidence 列表
        """
        raise NotImplementedError

    def delete(self, memory_id: str) -> bool:
        """
        删除某条记忆的所有证据

        数据流: 记忆遗忘 → delete → 删除 JSONL 文件

        返回:
            是否成功
        """
        raise NotImplementedError

    def list_all(self) -> list[str]:
        """列出所有有证据的记忆 ID"""
        raise NotImplementedError
