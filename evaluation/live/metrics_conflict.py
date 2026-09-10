"""冲突处理正确率（真机事件链路）。

**为什么不能走显式写入接口**

``POST /api/memory/memories/preference`` 直接经 ``MemoryWriteService`` 落库，
**不触发** ``PreferenceUpdater``，因此永远不会产生 ConflictRecord（已实测：连写
两条同 target、不同 value 的偏好，两条都 active 且冲突表为空）。冲突只在事件
抽取链路上产生，所以必须用 ``/api/agent/step`` 连续写两次。

**驱动的前提（服务端曾有两个阻塞缺陷）**

同一用户连续写第二次事件时，服务端曾抛 ``IntegrityError`` 并整条丢弃该事件
（表现为 ``written_event_ids`` 为空、``processing`` 为 null，抽取完全不执行）：

1. ``working_states.working_state_id`` —— 由 tenant/user/task 拼接后硬截断到
   64 字符，长 user_id 会把 task_id 整段截掉，两个任务撞同一主键；
2. ``task_episodes.episode_id`` —— 只由 task_id 派生，**全局主键却不含用户**，
   任何两个用户任务重名即碰撞。

两者都已修复（见 ``canonical_write._scoped_row_id``）。在这之前冲突指标根本
无法测量——而冲突评测按定义就要写第二次，正好命中。

**"驱动失败"不是"决策错误"**

若旧/新偏好任一没写成功，或期望有冲突记录却没有，记为 ``drive_failure`` 并单独
统计。把驱动失败算作决策错误会把实现缺陷伪装成算法准确率。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from evaluation.live.client import LiveClient, LiveClientError
from evaluation.live.metrics_preference import build_step_body, case_user
from evaluation.live.seeding import EvalUser
from evaluation.live.stats import latency_summary, mean


@dataclass
class ConflictOutcome:
    case_id: str
    block: str
    expected_decision: str
    observed_decision: str = ""
    correct: bool = False
    drive_failure: bool = False
    old_written: bool = False
    new_written: bool = False
    active_count: int = 0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "block": self.block,
            "expected_decision": self.expected_decision,
            "observed_decision": self.observed_decision,
            "correct": self.correct,
            "drive_failure": self.drive_failure,
            "old_written": self.old_written,
            "new_written": self.new_written,
            "active_count": self.active_count,
            "reason": self.reason,
        }


#: 事件提交偶发返回空 ``processing``（事件落库但不触发抽取）。实测首次写入
#: 成功率 10/10，但连续写入时不稳定，故重试；重试仍失败才计 drive_failure。
WRITE_ATTEMPTS = 4
#: 服务在事件洪峰下会短暂返回空 processing（疑似单 worker embedding 管线积压），
#: 退避时间取长一些并逐次加倍，避免把饱和当成永久失败。
WRITE_RETRY_BACKOFF_S = 3.0


def _write_preference(
    client: LiveClient, user: EvalUser, text: str, tag: str, scene: str
) -> bool:
    """写入一条偏好，返回是否真正提交（``processing`` 非空）。"""
    for attempt in range(WRITE_ATTEMPTS):
        # 每次都换 tag：event_id 由 tag 派生，重试沿用同一 event_id 会被幂等表
        # 判定为重复而直接跳过，重试就永远不可能成功。
        body = build_step_body(f"{tag}_a{attempt}", text, user, scene=scene)
        try:
            response = client.agent_step(body)
        except LiveClientError:
            response = {}
        if response.get("processing"):
            return True
        if attempt + 1 < WRITE_ATTEMPTS:
            time.sleep(WRITE_RETRY_BACKOFF_S * (attempt + 1))
    return False


def _find_conflict(client: LiveClient, user_id: str) -> dict[str, Any] | None:
    """返回该用户的冲突记录。

    每条样本用独立身份（``case_user``），因此一个用户最多对应一条冲突，无需
    再按 memory_id 过滤。**曾经按 memory_id 匹配但传了空串**，导致永远匹配
    失败、把"冲突已正确创建"误报成"驱动失败"——那种失败模式会静默吞掉真结果。
    """
    conflicts = client.list_conflicts(user_id=user_id)
    return conflicts[0] if conflicts else None


def run_case(
    client: LiveClient,
    case: dict[str, Any],
    user: EvalUser,
    *,
    settle_s: float = 1.0,
) -> ConflictOutcome:
    case_id = str(case.get("case_id", ""))
    outcome = ConflictOutcome(
        case_id=case_id,
        block=str(case.get("block", "")),
        expected_decision=str(case.get("expected_decision", "")),
    )
    # 每条样本独立身份：否则第二条偏好会命中冲突机制改写成 update，无法观察。
    case_owner = case_user(user, case_id)

    outcome.old_written = _write_preference(
        client, case_owner, str(case.get("old_text", "")), f"{case_id}_old",
        str(case.get("old_scene") or "office"),
    )
    if not outcome.old_written:
        outcome.drive_failure = True
        outcome.reason = "old_preference_not_written"
        return outcome

    outcome.new_written = _write_preference(
        client, case_owner, str(case.get("new_text", "")), f"{case_id}_new",
        str(case.get("new_scene") or "office"),
    )
    if not outcome.new_written:
        outcome.drive_failure = True
        outcome.reason = "new_preference_not_written"
        return outcome

    time.sleep(settle_s)
    try:
        active = client.list_preferences(user_id=case_owner.user_id, status="active")
    except LiveClientError:
        active = []
    outcome.active_count = len(active)

    expects_record = bool(case.get("expects_conflict_record", True))
    conflict = _find_conflict(client, case_owner.user_id)
    observed = str((conflict or {}).get("decision", ""))

    if expects_record:
        if conflict is None:
            # 期望有记录却没有 —— 先按"驱动失败"计，避免把实现缺陷算成决策错误。
            outcome.drive_failure = True
            outcome.reason = "expected_conflict_record_missing"
            return outcome
        outcome.observed_decision = observed
        outcome.correct = observed == outcome.expected_decision
        outcome.reason = "matched" if outcome.correct else "decision_mismatch"
        return outcome

    # coexist：可接受的行为是"两条偏好并存且没有冲突记录"。
    outcome.observed_decision = observed or "coexist"
    outcome.correct = conflict is None and outcome.active_count >= 2
    outcome.reason = "coexist_confirmed" if outcome.correct else "unexpected_conflict_record"
    return outcome


def evaluate_conflict(
    client: LiveClient,
    dataset: dict[str, Any],
    user: EvalUser,
    *,
    limit_per_block: int | None = None,
    blocks: list[str] | None = None,
) -> dict[str, Any]:
    wanted = set(blocks) if blocks else None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in dataset.get("samples", []):
        block = str(case.get("block", "unknown"))
        if wanted and block not in wanted:
            continue
        grouped.setdefault(block, []).append(case)

    outcomes: list[ConflictOutcome] = []
    latencies: list[float] = []
    for block in sorted(grouped):
        cases = grouped[block]
        selected = cases[:limit_per_block] if limit_per_block else cases
        for case in selected:
            started = time.perf_counter()
            outcomes.append(run_case(client, case, user))
            latencies.append((time.perf_counter() - started) * 1000)

    scored = [o for o in outcomes if not o.drive_failure]
    # 两个口径都要给，且**以端到端为 headline**。
    #
    # 只报"已驱动样本上的正确率"会高估能力：系统没能把两条偏好关联起来时，
    # 用户看到的就是"处理失败"。条件正确率用于定位"关联上之后的决策是否对"，
    # 二者回答不同问题，不能拿条件值当结论。
    end_to_end = (
        sum(1 for o in outcomes if o.correct) / len(outcomes) if outcomes else None
    )
    by_block: dict[str, dict[str, Any]] = {}
    for block in sorted({o.block for o in outcomes}):
        group = [o for o in outcomes if o.block == block]
        graded = [o for o in group if not o.drive_failure]
        by_block[block] = {
            "count": len(group),
            "scored": len(graded),
            "drive_failures": len(group) - len(graded),
            "accuracy": round(mean([1.0 if o.correct else 0.0 for o in graded]), 4) if graded else None,
            # 端到端口径：把未关联（驱动失败）算作未正确处理
            "accuracy_end_to_end": (
                round(sum(1 for o in group if o.correct) / len(group), 4) if group else None
            ),
        }

    return {
        "total_cases": len(outcomes),
        "scored_cases": len(scored),
        "drive_failure_count": len(outcomes) - len(scored),
        "drive_failure_rate": round((len(outcomes) - len(scored)) / len(outcomes), 4) if outcomes else 0.0,
        "accuracy": round(end_to_end, 4) if end_to_end is not None else None,
        "accuracy_conditional": (
            round(mean([1.0 if o.correct else 0.0 for o in scored]), 4) if scored else None
        ),
        "by_block": by_block,
        "latency": latency_summary(latencies),
        "sample_results": [o.as_dict() for o in outcomes[:240]],
        "notes": (
            "accuracy 为端到端口径（未关联即计为未正确处理），"
            "accuracy_conditional 仅在成功关联的样本上计算，二者必须区分解读。"
            "drive_failure 表示第二对偏好未被关联，其常见成因是 _find_existing 的"
            "目标匹配未命中（同义改写）。coexist 块断言'两条偏好并存且无冲突记录'。"
        ),
    }
