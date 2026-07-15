"""
偏好更新与版本管理模块

处理偏好新增、更新、合并，维护版本链。
"""

from memoryhub.adapter.schemas import PreferenceMemory, ConflictRecord


class PreferenceUpdater:
    """偏好更新器"""

    def add(self, preference: PreferenceMemory) -> str:
        """
        新增偏好记忆

        数据流:
            候选偏好 → add → 检查是否与已有偏好冲突
              → 无冲突: 写入存储，返回 memory_id
              → 有冲突: 交由 ConflictDetector 处理

        参数:
            preference: 待新增的偏好

        返回:
            memory_id
        """
        raise NotImplementedError

    def update(self, old_id: str, new_preference: PreferenceMemory) -> str:
        """
        更新已有偏好（生成新版本）

        数据流:
            旧偏好 ID + 新偏好内容 → update
              → 创建新版本，version + 1
              → 设置 parent_id 指向旧版本
              → 旧版本状态设为 archived

        参数:
            old_id: 旧偏好 ID
            new_preference: 新偏好内容

        返回:
            新版本的 memory_id
        """
        raise NotImplementedError

    def merge(self, pref_a: PreferenceMemory, pref_b: PreferenceMemory) -> PreferenceMemory:
        """
        合并两条偏好

        数据流:
            偏好 A + 偏好 B → merge → 合并后的偏好

        参数:
            pref_a, pref_b: 待合并的偏好

        返回:
            合并后的 PreferenceMemory

        合并策略:
            - 内容互补时拼接
            - 取较高置信度
            - 合并证据链
        """
        raise NotImplementedError

    def get_version_chain(self, memory_id: str) -> list[PreferenceMemory]:
        """
        获取偏好版本链

        返回:
            从最早版本到最新版本的有序列表
        """
        raise NotImplementedError

    def archive(self, memory_id: str) -> bool:
        """归档某条偏好（标记为 archived）"""
        raise NotImplementedError
