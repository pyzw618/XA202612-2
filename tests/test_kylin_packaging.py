from __future__ import annotations

import importlib.util
import json
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


def _load_configure_opencode_module():
    path = ASSETS / "configure_opencode.py"
    spec = importlib.util.spec_from_file_location("configure_opencode", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_opencode_configuration_registers_memoryhub_mcp_and_preserves_settings(
    tmp_path: Path,
) -> None:
    module = _load_configure_opencode_module()
    opencode_root = tmp_path / "opencode"
    opencode_root.mkdir()
    config_path = opencode_root / "opencode.jsonc"
    config_path.write_text(
        '{\n  // keep the existing provider\n  "provider": {"demo": {}},\n}\n',
        encoding="utf-8",
    )
    launcher = tmp_path / "memoryhub" / "mcp-launcher"

    result = module.register_mcp(opencode_root, launcher, "ethan")
    config = json.loads(result.read_text(encoding="utf-8"))

    assert config["provider"] == {"demo": {}}
    assert config["mcp"]["memoryhub"] == {
        "type": "local",
        "command": ["/bin/sh", str(launcher)],
        "environment": {
            "MEMORYHUB_API_URL": "http://127.0.0.1:8099",
            "MEMORYHUB_USER_ID": "ethan",
        },
        "enabled": True,
        "timeout": 15000,
    }
    assert (opencode_root / "opencode.jsonc.memoryhub-backup").exists()


def test_opencode_configuration_refuses_invalid_json_without_overwriting(tmp_path: Path) -> None:
    module = _load_configure_opencode_module()
    opencode_root = tmp_path / "opencode"
    opencode_root.mkdir()
    config_path = opencode_root / "opencode.jsonc"
    original = '{"provider": '
    config_path.write_text(original, encoding="utf-8")

    try:
        module.register_mcp(opencode_root, tmp_path / "mcp-launcher", "ethan")
    except SystemExit as error:
        assert "cannot update invalid OpenCode config" in str(error)
    else:
        raise AssertionError("invalid OpenCode configuration was accepted")

    assert config_path.read_text(encoding="utf-8") == original
    assert not (opencode_root / "opencode.jsonc.memoryhub-backup").exists()


def test_opencode_configurator_installs_cross_kare_mcp_launcher() -> None:
    configurator = (ASSETS / "memoryhub-configure-opencode").read_text(encoding="utf-8")
    launcher = (ASSETS / "memoryhub-mcp-user-launcher").read_text(encoding="utf-8")

    assert "configure_opencode.py" in configurator
    assert "mcp-user-launcher" in configurator
    assert "/opt/kare-applications/shadow/merge/opt/memoryhub/venv/bin/python" in launcher
    assert "python3 \"$config_helper\"" in configurator


def test_desktop_client_has_no_embedded_terminal() -> None:
    desktop_root = ROOT / "desktop-client"
    main_window = (desktop_root / "src" / "MainWindow.cpp").read_text(encoding="utf-8")
    cmake = (desktop_root / "CMakeLists.txt").read_text(encoding="utf-8")
    resources = (desktop_root / "resources" / "app.qrc").read_text(encoding="utf-8")

    assert "TerminalPage" not in main_window
    assert 'registerPage("terminal"' not in main_window
    assert '"内置终端"' not in main_window
    assert "TerminalPage" not in cmake
    assert "terminal.svg" not in resources
    assert not (desktop_root / "src" / "pages" / "TerminalPage.cpp").exists()
    assert not (desktop_root / "src" / "pages" / "TerminalPage.h").exists()
    assert not (desktop_root / "resources" / "icons" / "terminal.svg").exists()


def test_fact_proposal_uses_current_desktop_user_and_canonical_triple_fields() -> None:
    fact_page = (
        ROOT / "desktop-client" / "src" / "pages" / "FactPage.cpp"
    ).read_text(encoding="utf-8")

    assert 'body["user_id"] = AppContext::instance()->userId();' in fact_page
    assert 'j::str(f, "subject")' in fact_page
    assert 'j::str(f, "predicate")' in fact_page


def test_deb_uses_real_kylin_embedding_and_vector_sdk() -> None:
    config = (ASSETS / "config.yaml").read_text(encoding="utf-8")
    launcher = (ASSETS / "memoryhub_service_launcher").read_text(encoding="utf-8")
    build_script = (
        ROOT / "packaging" / "linux" / "build-deb.sh"
    ).read_text(encoding="utf-8")

    assert "mode: production" in config
    assert "allow_fallback: false" in config
    assert "provider: kylin" in config
    assert "provider: milvus" in config
    assert "local_socket: true" in config
    assert "app_id: \"kylin-memoryhub\"" in config
    assert "libkysdk-coreai-embedding.so.1" in config
    assert "libkysdk-vector-engine-client-capi.so" in config
    assert "MEMORYHUB_EMBEDDING_PROVIDER:=kylin" in launcher
    assert "MEMORYHUB_VECTOR_ENGINE_PROVIDER:=milvus" in launcher
    assert "MEMORYHUB_VECTOR_ENGINE_LOCAL_SOCKET:=true" in launcher
    assert "libkysdk-vector-engine-client-capi.so*" in build_script
    assert "libkylin-coreai-embedding" in build_script
    assert "kylin-ai-vector-engine" in build_script


def test_native_sdk_links_transitive_dependencies_and_is_load_checked() -> None:
    cmake = (
        ROOT / "third_party" / "libkysdk-vector-engine-client-nile-sp2" / "CMakeLists.txt"
    ).read_text(encoding="utf-8")
    build_script = (ROOT / "packaging" / "linux" / "build-deb.sh").read_text(
        encoding="utf-8"
    )

    assert "pkg_check_modules(GRPCPP REQUIRED IMPORTED_TARGET grpc++)" in cmake
    assert "PUBLIC PkgConfig::GRPCPP" in cmake
    assert "PUBLIC protobuf::libprotobuf" in cmake
    assert "-Wl,--no-undefined" in cmake
    load_check = build_script.index("ctypes.CDLL(sys.argv[1])")
    assert build_script.index("--target kysdk-vector-engine-client-capi") < load_check
    assert load_check < build_script.index("[3/6] Building Qt desktop client")
    assert "libgrpc++1.51t64 | libgrpc++1.51" in build_script
    assert "libprotobuf32t64 | libprotobuf32" in build_script
    assert "libsqlcipher1" in build_script


def test_packaged_config_resolves_to_production_kylin_milvus() -> None:
    """真正解析打包配置，而不只是匹配字符串。

    字符串断言无法发现"YAML 文本没问题、解析结果却被环境覆盖"这一类缺陷，
    例如 .env 里的空 ``MEMORYHUB_VECTOR_ENGINE_APP_ID=`` 会把配置文件中的
    有效 app_id 清空，导致生产下 Milvus 直接连不上。
    """
    from memoryhub.config import load_config

    config = load_config(str(ASSETS / "config.yaml"))

    assert config.runtime.mode == "production"
    assert config.runtime.allow_fallback is False
    assert config.embedding.provider == "kylin"
    assert config.embedding.dimension == 768
    assert config.vector_engine.provider == "milvus"
    assert config.vector_engine.app_id == "kylin-memoryhub"
    assert config.vector_engine.local_socket is True
    # 解析结果必须与检索侧契约一致：麒麟 embedding 固定 768 维。
    assert config.vector_engine.dimension == config.embedding.dimension


def test_service_config_is_writable_by_the_desktop_user() -> None:
    """配置必须对服务用户可写，否则桌面端「LLM 服务配置」保存必然失败。

    /etc/memoryhub/config.yaml 以 root:0644 安装，而服务以桌面用户身份运行，
    因此 prepare-user 需要播种一份用户可写副本，launcher 优先使用它。
    """
    prepare = (ASSETS / "prepare-user").read_text(encoding="utf-8")
    launcher = (ASSETS / "memoryhub_service_launcher").read_text(encoding="utf-8")

    assert "$HOME/.config/memoryhub/config.yaml" in prepare
    assert "/etc/memoryhub/config.yaml" in prepare
    # launcher 必须在回退到 /etc 之前先看用户配置
    user_probe = launcher.index('$HOME/.config/memoryhub/config.yaml')
    system_default = launcher.index(': "${MEMORYHUB_CONFIG:=/etc/memoryhub/config.yaml}"')
    assert user_probe < system_default
