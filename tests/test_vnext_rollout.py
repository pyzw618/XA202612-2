from __future__ import annotations

import json

import pytest

from memoryhub.application.rollout_service import RolloutController, RolloutGateError
from memoryhub.config import VNextConfig


def test_rollout_requires_observation_and_zero_tolerance_safety() -> None:
    controller = RolloutController(VNextConfig(observation_window_requests=1))
    with pytest.raises(RolloutGateError, match="no observation"):
        controller.advance(5)

    controller.observe(5, request_count=1, policy_leak_count=1, window_id="w5-bad")
    with pytest.raises(RolloutGateError, match="zero-tolerance"):
        controller.advance(5)


def test_rollout_cuts_each_level_and_records_rollback_window(tmp_path) -> None:
    controller = RolloutController(
        VNextConfig(rollback_window_minutes=60, observation_window_requests=1)
    )
    controller.observe(5, request_count=1, window_id="w5")
    controller.advance(5)
    assert controller.current_mode == "canary"
    assert controller.rollback_window_active() is True
    rollback = controller.rollback(reason="manual rehearsal", target_level=0)
    assert rollback.action == "ROLLBACK"
    assert controller.current_mode == "legacy"

    for level in (5, 25, 50, 100):
        controller.observe(level, request_count=1, window_id=f"w{level}")
        controller.advance(level)
    assert controller.current_level == 100
    assert [
        audit.next_level for audit in controller.audits if audit.action == "CUTOVER"
    ] == [5, 5, 25, 50, 100]
    snapshot = tmp_path / "rollout.json"
    controller.write_snapshot(snapshot)
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert data["redacted"] is True
    assert data["authority_mutations"] == 0
    assert len(data["audits"]) == 6


def test_rollout_rejects_skipping_levels() -> None:
    controller = RolloutController()
    controller.observe(25, request_count=1)
    with pytest.raises(RolloutGateError, match="must advance"):
        controller.advance(25)
