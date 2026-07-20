"""
偏好更新与版本管理模块

处理偏好新增、更新、合并，维护版本链，内嵌时序一致性物理回退防御。
"""

from datetime import datetime, timezone
from memoryhub.adapter.schemas import PreferenceMemory, MemoryStatus, Evidence


class PreferenceUpdater:
    """偏好更新器"""

    # 内存模拟持久化存储层（全系统单例数据缓存）
    _mock_db: dict[str, PreferenceMemory] = {}

    def add(self, preference: PreferenceMemory) -> str:
        """
        新增偏好记忆
        """
        # 1. 查找是否存在同类型、同场景作用域的活跃偏好
        existing_id = None
        for mid, pref in self._mock_db.items():
            if (
                pref.status == MemoryStatus.ACTIVE
                and pref.user_id == preference.user_id
                and pref.preference_type == preference.preference_type
                and pref.scope.scene == preference.scope.scene
                and pref.scope.task_type == preference.scope.task_type
            ):
                existing_id = mid
                break

        # 2. 如果无冲突：直接新增
        if not existing_id:
            preference.status = MemoryStatus.ACTIVE
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self._mock_db[preference.memory_id] = preference
            return preference.memory_id
        
        # 3. 若检测到冲突：执行版本演化和回退核验
        return self.update(existing_id, preference)

    def update(self, old_id: str, new_preference: PreferenceMemory) -> str:
        """
        更新已有偏好（生成新版本，内置物理回滚机制）
        """
        old_pref = self._mock_db.get(old_id)
        if not old_pref:
            # 基础降级：不存在则直接新增
            new_preference.status = MemoryStatus.ACTIVE
            self._mock_db[new_preference.memory_id] = new_preference
            return new_preference.memory_id

        # 1. 时序一致性崩溃分析（统计最近 7 天的覆写反馈证据比例）
        now = datetime.now(timezone.utc)
        recent_evidences = []
        for e in old_pref.evidences:
            e_ts = e.timestamp.replace(tzinfo=timezone.utc) if not e.timestamp.tzinfo else e.timestamp
            if (now - e_ts).days <= 7:
                recent_evidences.append(e)
        
        overrides_count = sum(
            1 for e in recent_evidences 
            if "OVERRIDE" in e.content
        )

        # 2. **崩溃回滚触发条件**：一周内交互数据 $\ge 3$ 条且纠错覆写率 $\ge 70\%$
        if len(recent_evidences) >= 3 and (overrides_count / len(recent_evidences)) >= 0.7:
            if old_pref.parent_id and old_pref.parent_id in self._mock_db:
                # 物理 Revert：重新激活上一个干净安全的父 Commit 节点
                self._mock_db[old_pref.parent_id].status = MemoryStatus.ACTIVE
                self._mock_db[old_pref.parent_id].updated_at = datetime.now(timezone.utc)
                # 裁剪垃圾节点
                old_pref.status = MemoryStatus.ARCHIVED
                return old_pref.parent_id
            else:
                # 若无历史版本，说明偏好初始提炼阶段即发生错乱，直接擦除该节点，阻断级联放大
                old_pref.status = MemoryStatus.DELETED
                return ""

        # 3. 正常升级版本链
        new_preference.version = old_pref.version + 1
        new_preference.parent_id = old_id
        new_preference.status = MemoryStatus.ACTIVE
        new_preference.created_at = old_pref.created_at
        new_preference.updated_at = datetime.now(timezone.utc)

        # 融合继承证据链，限制最多保留最近 15 条
        merged_evidences = old_pref.evidences + new_preference.evidences
        new_preference.evidences = merged_evidences[-15:]

        # 旧版本归档
        old_pref.status = MemoryStatus.ARCHIVED

        self._mock_db[new_preference.memory_id] = new_preference
        return new_preference.memory_id

    def merge(self, pref_a: PreferenceMemory, pref_b: PreferenceMemory) -> PreferenceMemory:
        """
        合并两条偏好
        """
        # 整合拼接内容
        merged_content = f"{pref_a.content} 且 {pref_b.content}"
        
        # 融合证据链
        merged_evidences = pref_a.evidences + pref_b.evidences

        merged_pref = PreferenceMemory(
            user_id=pref_a.user_id,
            preference_type=pref_a.preference_type,
            content=merged_content,
            scope=pref_a.scope,
            confidence=max(pref_a.confidence, pref_b.confidence),
            status=MemoryStatus.ACTIVE,
            version=max(pref_a.version, pref_b.version),
            parent_id=pref_a.parent_id,
            evidences=merged_evidences[-15:],
            created_at=min(pref_a.created_at, pref_b.created_at),
            updated_at=datetime.now(timezone.utc)
        )
        return merged_pref

    def get_version_chain(self, memory_id: str) -> list[PreferenceMemory]:
        """
        获取偏好版本链
        """
        chain = []
        curr_id = memory_id
        visited = set()  # 防止版本圈回环异常

        while curr_id and curr_id not in visited:
            pref = self._mock_db.get(curr_id)
            if not pref:
                break
            chain.insert(0, pref)  # 头插，按时间升序排序
            visited.add(curr_id)
            curr_id = pref.parent_id

        return chain

    def archive(self, memory_id: str) -> bool:
        """
        归档某条偏好
        """
        pref = self._mock_db.get(memory_id)
        if pref:
            pref.status = MemoryStatus.ARCHIVED
            pref.updated_at = datetime.now(timezone.utc)
            return True
        return False