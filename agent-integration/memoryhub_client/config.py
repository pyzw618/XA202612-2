"""Configuration shared by CLI, MCP and Plugin command wrappers."""

from __future__ import annotations

import getpass
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def current_user_id() -> str:
    """Return the interactive OS account used to own MemoryHub data.

    Install helpers can run below sudo, so prefer SUDO_USER over root.  The
    environment-first order also keeps this deterministic in KARE containers.
    """

    sudo_user = os.getenv("SUDO_USER", "").strip()
    env_user = (os.getenv("USER", "") or os.getenv("LOGNAME", "")).strip()
    if env_user == "root" and sudo_user and sudo_user != "root":
        return sudo_user
    for candidate in (
        env_user,
        os.getenv("USERNAME", "").strip(),
    ):
        if candidate:
            return candidate
    try:
        candidate = getpass.getuser().strip()
    except (OSError, KeyError):
        candidate = ""
    return candidate or "default"


def _bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def find_project_root(start: str | Path | None = None) -> Path:
    current = Path(start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".memoryhub").is_dir():
            return candidate
    return current


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class ClientConfig:
    api_url: str = "http://127.0.0.1:8099"
    user_id: str = field(default_factory=current_user_id)
    tenant_id: str = "default"
    project: str = ""
    scene: str = "code"
    task_type: str = "coding_task"
    timeout: float = 30.0
    top_k: int = 5
    min_confidence: float = 0.0
    auto_record: bool = True
    mode: str = "plugin"

    @classmethod
    def load(
        cls,
        *,
        api_url: str | None = None,
        user_id: str | None = None,
        project: str | None = None,
        scene: str | None = None,
        task_type: str | None = None,
        timeout: float | None = None,
        cwd: str | Path | None = None,
    ) -> "ClientConfig":
        project_root = find_project_root(cwd)
        project_file = project_root / ".memoryhub" / "config.json"
        if os.name == "nt" and not os.environ.get("XDG_CONFIG_HOME"):
            config_home = Path(os.environ.get("APPDATA", Path.home() / ".config"))
        else:
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        global_file = config_home / "memoryhub" / "config.json"
        values: dict[str, object] = {}
        values.update(_read_json(global_file))
        values.update(_read_json(project_file))
        env_map = {
            "api_url": os.getenv("MEMORYHUB_API_URL"),
            "user_id": os.getenv("MEMORYHUB_USER_ID"),
            "tenant_id": os.getenv("MEMORYHUB_TENANT_ID"),
            "project": os.getenv("MEMORYHUB_PROJECT"),
            "scene": os.getenv("MEMORYHUB_SCENE"),
            "task_type": os.getenv("MEMORYHUB_TASK_TYPE"),
            "timeout": os.getenv("MEMORYHUB_API_TIMEOUT"),
            "top_k": os.getenv("MEMORYHUB_TOP_K"),
            "min_confidence": os.getenv("MEMORYHUB_MIN_CONFIDENCE"),
            "auto_record": os.getenv("MEMORYHUB_AUTO_RECORD"),
            "mode": os.getenv("MEMORYHUB_MODE"),
        }
        values.update({key: value for key, value in env_map.items() if value not in (None, "")})
        overrides = {
            "api_url": api_url,
            "user_id": user_id,
            "project": project,
            "scene": scene,
            "task_type": task_type,
            "timeout": timeout,
        }
        values.update({key: value for key, value in overrides.items() if value not in (None, "")})
        return cls(
            api_url=str(values.get("api_url") or cls.api_url).rstrip("/"),
            user_id=str(values.get("user_id") or current_user_id()),
            tenant_id=str(values.get("tenant_id") or cls.tenant_id),
            project=str(values.get("project") or project_root),
            scene=str(values.get("scene") or cls.scene),
            task_type=str(values.get("task_type") or cls.task_type),
            timeout=float(values.get("timeout") or cls.timeout),
            top_k=max(1, int(values.get("top_k") or cls.top_k)),
            min_confidence=float(values.get("min_confidence") or cls.min_confidence),
            auto_record=_bool(values.get("auto_record"), cls.auto_record),
            mode=str(values.get("mode") or cls.mode),
        )
