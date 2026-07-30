"""
证据链存储 — JSONL 格式。

每条记忆的产生都绑定原始事件作为"证据"，
支持追溯"这条记忆是从哪条用户反馈/操作行为推导出来的"。

格式（每行一条 JSON）:
  {"evidence_id": "evid_xxx", "memory_id": "pref_xxx",
   "source_event_id": "ev_xxx", "source_type": "user_feedback",
   "description": "用户说：以后周报都用 Markdown",
   "created_at": 1720000000.0}
"""

import json
import os
import uuid
import time
from typing import List, Optional, Dict

# 默认存储目录
_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "evidences")


class EvidenceStore:
    """
    JSONL 证据链存储。

    用法:
        es = EvidenceStore()
        es.append(memory_id="pref_001", source_event_id="ev_abc",
                  source_type="user_feedback", description="用户说：以后用 Markdown")
        chain = es.get_chain("pref_001")  # → list[dict]
    """

    def __init__(self, base_dir: str = ""):
        self.base_dir = base_dir or _DEFAULT_DIR
        os.makedirs(self.base_dir, exist_ok=True)

    # ---- 写入 ----

    def append(
        self,
        memory_id: str,
        source_event_id: str,
        source_type: str,
        description: str,
    ) -> str:
        """
        追加一条证据。
        返回 evidence_id。
        """
        evidence = {
            "evidence_id": _uid(),
            "memory_id": memory_id,
            "source_event_id": source_event_id,
            "source_type": source_type,
            "description": description,
            "created_at": time.time(),
        }
        filepath = self._path(memory_id)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(evidence, ensure_ascii=False) + "\n")
        return evidence["evidence_id"]

    def append_batch(self, items: List[Dict]) -> List[str]:
        """批量追加证据。每项: {memory_id, source_event_id, source_type, description}"""
        ids = []
        # 按 memory_id 分组写入
        grouped: Dict[str, list] = {}
        for item in items:
            mid = item["memory_id"]
            grouped.setdefault(mid, []).append(item)

        for mid, group in grouped.items():
            filepath = self._path(mid)
            with open(filepath, "a", encoding="utf-8") as f:
                for item in group:
                    evidence = {
                        "evidence_id": _uid(),
                        "memory_id": mid,
                        "source_event_id": item["source_event_id"],
                        "source_type": item["source_type"],
                        "description": item["description"],
                        "created_at": time.time(),
                    }
                    f.write(json.dumps(evidence, ensure_ascii=False) + "\n")
                    ids.append(evidence["evidence_id"])
        return ids

    # ---- 读取 ----

    def get_chain(self, memory_id: str) -> List[dict]:
        """
        查询某条记忆的完整证据链。
        按时间升序排列。
        """
        filepath = self._path(memory_id)
        if not os.path.exists(filepath):
            return []

        chain = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chain.append(json.loads(line))
        chain.sort(key=lambda x: x.get("created_at", 0))
        return chain

    def get_source_events(self, memory_id: str) -> List[str]:
        """获取产生这条记忆的原始事件 ID 列表。"""
        chain = self.get_chain(memory_id)
        return [e["source_event_id"] for e in chain]

    # ---- 删除 ----

    def delete_chain(self, memory_id: str) -> bool:
        """删除某条记忆的全部证据（精准遗忘时调用）。"""
        filepath = self._path(memory_id)
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False

    # ---- 内部 ----

    def _path(self, memory_id: str) -> str:
        return os.path.join(self.base_dir, f"{memory_id}.jsonl")


def _uid() -> str:
    return "evid_" + uuid.uuid4().hex[:12]
