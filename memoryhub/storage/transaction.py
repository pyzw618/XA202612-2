"""
跨存储事务补偿协议。

解决 B20 问题：SQLite、FAISS、Evidence 三个独立存储无法用数据库事务包在一起。
本模块提供补偿式"事务"——记录每一步的回滚操作，失败时按逆序执行补偿。

用法:
    tx = StorageTransaction()
    try:
        pref_repo.insert(row)
        tx.on_failure(lambda: pref_repo.delete_by_id(row.memory_id))

        vector_store.add(mid, vec)
        tx.on_failure(lambda: vector_store.remove(mid))

        evidence_store.save(mid, ev)
        tx.on_failure(lambda: evidence_store.delete(mid))
    except Exception:
        tx.rollback()
        raise   # 上层知道写入失败
"""

import logging
from typing import Callable, List

logger = logging.getLogger(__name__)


class StorageTransaction:
    """
    跨存储补偿式事务。

    不是 ACID 事务——补偿只是"尽力撤销"，不是 100% 保证。
    如果补偿本身也失败了，记录错误日志但不吞掉原始异常。

    用法:
        tx = StorageTransaction()

        # 每一步成功后立即注册回滚
        repo.save(record)
        tx.on_failure(lambda: repo.delete_by_id(record.memory_id))

        vs.add(mid, vec)
        tx.on_failure(lambda: vs.remove(mid))

        # 如果上面任何一步抛异常 → 已注册的回滚按逆序执行
    """

    def __init__(self, name: str = ""):
        """
        Args:
            name: 事务名称，用于错误日志
        """
        self._name = name or "unnamed"
        self._rollbacks: List[Callable[[], None]] = []

    # ---- 注册回滚 ----

    def on_failure(self, undo: Callable[[], None]) -> None:
        """
        注册一个回滚操作。按注册的逆序执行。

        用法:
            tx.on_failure(lambda: vector_store.remove(memory_id))
        """
        self._rollbacks.append(undo)

    # ---- 回滚 ----

    def rollback(self) -> List[str]:
        """
        逆序执行所有已注册的回滚操作。

        Returns:
            每个回滚的描述列表（"[成功]" 或 "[失败] description"），用于日志。
        """
        results = []
        for undo in reversed(self._rollbacks):
            try:
                undo()
                results.append(f"[已回滚] {_describe(undo)}")
            except Exception as e:
                logger.error(
                    "StorageTransaction[%s] 回滚失败: %s → %s",
                    self._name, _describe(undo), e,
                )
                results.append(f"[回滚失败] {_describe(undo)}: {e}")
        self._rollbacks.clear()
        return results

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # 有异常 → 回滚，但不吞异常
            self.rollback()
        return False  # 重新抛出原始异常

    def __repr__(self):
        return f"<StorageTransaction[{self._name}] steps={len(self._rollbacks)}>"


def _describe(fn: Callable) -> str:
    """尽量描述一个 lambda/函数做了什么。"""
    try:
        name = fn.__name__
        if name != "<lambda>":
            return name
        import inspect
        src = inspect.getsource(fn).strip()
        # 取 lambda 之后的部分
        if "lambda:" in src:
            return src.split("lambda:", 1)[1].strip().rstrip(",)")
        return src[:60]
    except Exception:
        return "unknown"
