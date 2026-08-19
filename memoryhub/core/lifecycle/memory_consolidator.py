"""MemoryConsolidator：中期（情景）→ 长期（经统一抽取链）合并（REFACTOR_PLAN_V2 §4.4.2）。"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """消费中期情景 → 重放事件到统一抽取链 → 长期记忆；情景标记 consolidated（幂等）。"""

    def __init__(self, *, mid_term_repo, event_repo, extraction_executor,
                 preference_updater=None, tool_miner=None, workflow_miner=None):
        self.mid_term_repo = mid_term_repo
        self.event_repo = event_repo
        self.extraction_executor = extraction_executor
        self.preference_updater = preference_updater
        self.tool_miner = tool_miner
        self.workflow_miner = workflow_miner

    def _episode_events(self, ep: dict) -> list:
        events = []
        for eid in ep.get("event_ids") or []:
            ev = self.event_repo.get_by_id(eid)
            if ev is not None:
                events.append(ev)
        return events

    def _episode_groups(self, user_id: str = "") -> dict[tuple, list[list]]:
        """按 (scene, task_type) 把各情景的事件轨迹分组，供工作流挖掘。"""
        groups: dict[tuple, list[list]] = defaultdict(list)
        for ep in self.mid_term_repo.list_active(user_id=user_id):
            events = self._episode_events(ep)
            if not events:
                continue
            scene = str(getattr(events[0], "scene", "") or "")
            task_type = str(getattr(events[0], "task_type", "") or "")
            groups[(scene, task_type)].append(events)
        return groups

    def consolidate_workflow_preferences(self, user_id: str = "") -> list[str]:
        """跨多次执行挖掘 WORKFLOW_PREF：稳定公共步骤 → 写入长期偏好（REFACTOR_PLAN_V2 §4.2.1）。

        复用 WorkflowMiner（LCS 规则优先），把跨轨迹稳定复现的操作步骤映射为用户
        操作流程偏好候选，与 ToolPreferenceMiner 共同补齐"工具/流程偏好"确定性提取。
        """
        if self.workflow_miner is None or self.preference_updater is None:
            return []
        written: list[str] = []
        for (scene, task_type), trajectories in self._episode_groups(user_id).items():
            if len(trajectories) < 3:
                continue  # 同一任务类最少 3 条轨迹才有"稳定工作流"可言
            mined = self.workflow_miner.mine(trajectories)
            for workflow in mined:
                steps = list(getattr(workflow, "steps", None) or [])
                if len(steps) < 2:
                    continue
                workflow_pref = _WorkflowPrefBuilder.build(
                    user_id=user_id or "default",
                    scene=scene,
                    task_type=task_type,
                    steps=steps,
                    name=str(getattr(workflow, "name", "") or ""),
                )
                try:
                    result_id = self.preference_updater.add(workflow_pref)
                    if result_id:
                        written.append(result_id)
                except Exception:
                    logger.exception(
                        "workflow preference write failed: %s", steps
                    )
        return written

    def consolidate_tool_preferences(self, user_id: str = "") -> list[str]:
        """从中期情景的工具轨迹挖掘工具选择偏好并写入长期偏好（REFACTOR_PLAN_V2 §4.2.1）。"""
        if self.tool_miner is None or self.preference_updater is None:
            return []
        episodes = self.mid_term_repo.list_active(user_id=user_id)
        events: list = []
        for ep in episodes:
            events.extend(self._episode_events(ep))
        written: list[str] = []
        for preference in self.tool_miner.mine(events, user_id=user_id or "default"):
            try:
                result_id = self.preference_updater.add(preference)
                if result_id:
                    written.append(result_id)
            except Exception:
                logger.exception("tool preference write failed: %s", preference.text)
        return written

    def consolidate_episodes(self, user_id: str = "") -> dict:
        stats = {"consolidated": 0, "skipped": 0, "errors": 0}
        episodes = self.mid_term_repo.list_active(user_id=user_id)
        for ep in episodes:
            events = []
            for eid in ep.get("event_ids") or []:
                ev = self.event_repo.get_by_id(eid)
                if ev is not None:
                    events.append(ev)
            if not events:
                self.mid_term_repo.mark_consolidated(ep["episode_id"])
                stats["skipped"] += 1
                continue
            try:
                for event in events:
                    self.extraction_executor.run_preference(event)
                trajectories: dict[tuple, list] = defaultdict(list)
                for event in events:
                    trajectories[
                        (event.user_id, event.session_id, event.task_type)
                    ].append(event)
                for trajectory in trajectories.values():
                    self.extraction_executor.run_knowledge(trajectory)
                self.mid_term_repo.mark_consolidated(ep["episode_id"])
                stats["consolidated"] += 1
                logger.info("episode consolidated -> long-term: %s events=%d", ep["episode_id"], len(events))
            except Exception:
                logger.exception("episode consolidation failed: %s", ep["episode_id"])
                stats["errors"] += 1
        return stats


class _WorkflowPrefBuilder:
    """把跨轨迹挖掘出的稳定工作流步骤映射为 WORKFLOW_PREF 偏好候选（I-9）。"""

    @staticmethod
    def build(*, user_id: str, scene: str, task_type: str, steps: list, name: str = ""):
        from memoryhub.adapter.schemas import PreferenceMemory, SceneScope

        step_text = " → ".join(str(s) for s in steps)
        return PreferenceMemory(
            user_id=user_id,
            preference_type="workflow_preference",
            text=f"在{task_type or '当前'}任务中偏好按稳定流程执行：{step_text}",
            payload={"action": "follow_workflow", "task_type": task_type, "steps": steps},
            scope=SceneScope(scene=scene, task_type=task_type),
            confidence=0.8,
            quality_score=1.0,
            extract_source="workflow_miner",
            tags=["流程", task_type],
        )
