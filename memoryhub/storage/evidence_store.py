"""
证据链存储

以 JSONL 格式存储证据链，支持追加写入和按 ID 查询。
"""

import json
import os
from pathlib import Path

from memoryhub.adapter.schemas import Evidence


class EvidenceStore:
    """
    证据链存储器（JSONL 文件）

    每个 memory_id 对应一个 .jsonl 文件，一行一条 Evidence。

    使用方式:
        store = EvidenceStore("data/evidence")
        store.save("mem_001", evidence)
        evidences = store.load("mem_001")
    """

    def __init__(self, base_path: str = "data/evidence"):
        self.base_path = Path(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    # ---- 写入 ----

    def save(self, memory_id: str, evidence: Evidence) -> None:
        """
        追加保存一条证据。

        参数:
            memory_id: 关联的记忆 ID
            evidence: Evidence 对象
        """
        filepath = self._path(memory_id)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(evidence.model_dump_json() + "\n")

    def batch_save(self, memory_id: str, evidences: list[Evidence]) -> None:
        """
        批量保存证据（一次打开文件，减少 IO）。

        参数:
            memory_id: 关联的记忆 ID
            evidences: Evidence 列表
        """
        filepath = self._path(memory_id)
        with open(filepath, "a", encoding="utf-8") as f:
            for ev in evidences:
                f.write(ev.model_dump_json() + "\n")

    # ---- 读取 ----

    def load(self, memory_id: str) -> list[Evidence]:
        """
        加载某条记忆的所有证据。

        参数:
            memory_id: 记忆 ID

        返回:
            Evidence 列表（按文件顺序，即写入时间升序）
        """
        filepath = self._path(memory_id)
        if not filepath.exists():
            return []

        evidences = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        evidences.append(Evidence.model_validate_json(line))
                    except Exception:
                        # 跳过损坏的行
                        continue
        return evidences

    # ---- 删除 ----

    def delete(self, memory_id: str) -> bool:
        """
        删除某条记忆的所有证据（物理删除文件）。

        返回:
            True 表示已删除，False 表示文件不存在。
        """
        filepath = self._path(memory_id)
        if filepath.exists():
            os.remove(filepath)
            return True
        return False

    # ---- 查询 ----

    def list_all(self) -> list[str]:
        """
        列出所有有证据的记忆 ID。

        遍历证据目录下所有 .jsonl 文件，提取文件名（即 memory_id）。
        """
        ids = []
        for f in self.base_path.glob("*.jsonl"):
            ids.append(f.stem)  # stem = 去掉 .jsonl 的文件名
        return sorted(ids)

    # ---- 内部 ----

    def _path(self, memory_id: str) -> Path:
        # 基本防护：防止路径穿越
        safe_id = memory_id.replace("/", "_").replace("\\", "_")
        return self.base_path / f"{safe_id}.jsonl"
