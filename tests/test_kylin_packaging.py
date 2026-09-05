from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "packaging" / "linux" / "assets"


def test_graphical_launcher_publishes_generation_only_after_health_check() -> None:
    launcher = (ASSETS / "memoryhub_app_launcher").read_text(encoding="utf-8")
    service = (ASSETS / "memoryhub_service_launcher").read_text(encoding="utf-8")

    assert "while [ \"$attempts\" -lt 40 ] && ! is_healthy" in launcher
    assert "if is_healthy && is_memoryhub_pid \"$service_pid\"; then" in launcher
    assert 'cat "$expected_generation_file" >"$running_generation_file"' in launcher
    assert "memoryhub-service-generation" not in service


def test_graphical_launcher_stops_every_validated_stale_service() -> None:
    launcher = (ASSETS / "memoryhub_app_launcher").read_text(encoding="utf-8")

    scan = launcher.index("for proc in /proc/[0-9]*")
    kill = launcher.index('kill "$pid"', scan)
    wait = launcher.index('while [ "$attempts" -lt 20 ] && is_healthy', kill)
    assert scan < kill < wait
    assert 'if [ "$stopped" = false ]; then\n        for proc' not in launcher


def test_generation_match_requires_a_live_owned_memoryhub_process() -> None:
    launcher = (ASSETS / "memoryhub_app_launcher").read_text(encoding="utf-8")
    start = launcher.index("generation_matches()")
    end = launcher.index("\n}\n", start)
    function = launcher[start:end]

    assert '[ -r "$service_pid_file" ]' in function
    assert 'is_memoryhub_pid "$pid"' in function


def test_opencode_configuration_does_not_revive_legacy_systemd_service() -> None:
    configurator = (ASSETS / "memoryhub-configure-opencode").read_text(encoding="utf-8")

    assert "systemctl --user" not in configurator
    assert "memoryhub.service" not in configurator
