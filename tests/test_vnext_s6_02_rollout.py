from __future__ import annotations

from dataclasses import dataclass

from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionService,
)
from memoryhub.application.rollout_service import RolloutController, RolloutGateError
from memoryhub.application.shadow_read_service import RolloutReadService, ShadowReadService
from memoryhub.config import VNextConfig
from memoryhub.storage.database import Database


def _reflection_service() -> ReflectionService:
    return ReflectionService(model=DeterministicReflectionModel())


@dataclass
class _Request:
    request_id: str = "request-1"
    tenant_id: str = "tenant-a"
    user_id: str = "user-a"


def test_shadow_and_dual_read_return_legacy_only_and_redact_report() -> None:
    request = _Request()
    for mode in ("shadow", "dual-read"):
        controller = RolloutController(VNextConfig(mode=mode))
        service = RolloutReadService(
            controller=controller,
            shadow_read=ShadowReadService(reflection_service=_reflection_service()),
        )
        result = service.read(
            request,
            legacy_reader=lambda _: {
                "results": [{"memory_id": "legacy", "tenant_id": "tenant-a"}]
            },
            vnext_reader=lambda _: {
                "results": [{"memory_id": "vnext", "tenant_id": "tenant-a"}]
            },
        )
        assert result.response["results"][0]["memory_id"] == "legacy"
        assert result.report is not None and result.report.redacted is True
        assert "private" not in str(result.report)


def test_canary_assignment_is_stable_and_vnext_is_selected_at_100_percent() -> None:
    controller = RolloutController(VNextConfig(mode="canary", canary_percent=100))
    request = _Request()
    assert controller.choose_vnext(request) is True
    assert controller.choose_vnext(_Request(request_id="different")) is True


def test_rollout_rejects_nonzero_zero_tolerance_metrics() -> None:
    controller = RolloutController(VNextConfig(observation_window_requests=1))
    controller.observe(5, request_count=1, cross_tenant_count=1)
    try:
        controller.advance(5)
    except RolloutGateError as exc:
        assert "zero-tolerance" in str(exc)
    else:
        raise AssertionError("unsafe rollout unexpectedly advanced")


def test_rollout_enforces_order_and_rollback_does_not_touch_authority() -> None:
    controller = RolloutController(VNextConfig(observation_window_requests=1))
    controller.observe(5, request_count=1)
    controller.advance(5)
    audit = controller.rollback(reason="read-path safety rehearsal")
    assert audit.action == "ROLLBACK"
    assert controller.current_mode == "legacy"
    assert controller.snapshot()["authority_mutations"] == 0


def test_rollout_state_observations_and_audits_survive_restart(tmp_path) -> None:
    db_path = tmp_path / "rollout.db"
    db = Database(str(db_path))
    db.init_schema()
    controller = RolloutController(
        VNextConfig(observation_window_requests=1), db=db
    )
    controller.observe(5, request_count=1, window_id="window-5")
    controller.advance(5)
    controller.observe(25, request_count=2, window_id="window-25")
    controller.advance(25)
    db.close()

    restarted_db = Database(str(db_path))
    restarted_db.init_schema()
    restarted = RolloutController(VNextConfig(), db=restarted_db)
    assert restarted.current_level == 25
    assert restarted.current_mode == "canary"
    assert restarted.observations[-1].request_count == 2
    assert [audit.next_level for audit in restarted.audits] == [5, 25]
    restarted_db.close()
