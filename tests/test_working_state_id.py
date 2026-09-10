"""working_state_id 派生规则回归测试。

背景缺陷：``_working_state_id`` 原本是 tenant/user/task 拼接后硬截断到 64 字符。
当 ``user_id`` 较长时 ``task_id`` 会被整段截掉，**同一用户的两个不同任务会得到
同一个主键**，第二次写入直接抛
``IntegrityError: UNIQUE constraint failed: working_states.working_state_id``。

影响面：所有"同一用户连续执行多个任务"的流程，其中就包括冲突处理——它按定义
就要对同一用户写第二次。因此这个缺陷会让冲突处理完全无法工作。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoryhub.application.canonical_write import CanonicalWriteService


@dataclass
class _Event:
    tenant_id: str
    user_id: str
    task_id: str


def _derive(tenant: str, user: str, task: str) -> str:
    return CanonicalWriteService._working_state_id(_Event(tenant, user, task))


def test_short_ids_are_unchanged() -> None:
    """短 id 必须与旧实现逐字节一致，否则既有行会对不上主键。"""
    assert _derive("default", "lcz", "task-A") == "working-default-lcz-task-A"


def test_long_user_ids_do_not_collapse_different_tasks() -> None:
    """长 user_id 下，不同 task 必须得到不同 id —— 这正是原缺陷所在。"""
    user = "evalrun_20260910T104614Z_2fc5::conf2_nat_0001"
    old = _derive("default", user, "task_old")
    new = _derive("default", user, "task_new")
    assert old != new


def test_ids_never_exceed_column_width() -> None:
    user = "x" * 200
    for task in ("t1", "t2", "x" * 200):
        assert len(_derive("default", user, task)) <= 64


def test_derivation_is_deterministic() -> None:
    user = "evalrun_20260910T104614Z_2fc5::conf2_nat_0001"
    assert _derive("default", user, "task_old") == _derive("default", user, "task_old")


def test_same_task_still_shares_one_state_row() -> None:
    """同一 (tenant,user,task) 必须稳定映射到同一 id，否则无法复用工作状态。"""
    user = "evalrun_20260910T104614Z_2fc5::conf2_nat_0001"
    assert _derive("default", user, "task_a") == _derive("default", user, "task_a")


def test_tenant_is_part_of_identity() -> None:
    assert _derive("tenant-a", "user", "task") != _derive("tenant-b", "user", "task")


# ------------------------------------------------- episode_id 同类缺陷


def _episode(tenant: str, user: str, task: str) -> str:
    return CanonicalWriteService._scoped_row_id("episode", _Event(tenant, user, task))


def test_episode_id_includes_user_scope() -> None:
    """episode_id 曾是 `episode-{task_id}`，全局主键却不含用户。

    两个用户只要任务名相同（"周报"、"task-1" 这类极常见）就会主键碰撞，
    第二个用户的写入整条失败、完全不触发抽取。
    """
    a = _episode("default", "userA", "task_old")
    b = _episode("default", "userB", "task_old")
    assert a != b


def test_episode_id_stays_within_column_width() -> None:
    long_user = "evalrun_20260910T104614Z_2fc5::conf2_nat_0001"
    for task in ("task_old", "task_new", "x" * 80):
        assert len(_episode("default", long_user, task)) <= 64


def test_episode_id_is_deterministic() -> None:
    assert _episode("default", "userA", "t") == _episode("default", "userA", "t")
