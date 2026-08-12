"""Runtime compatibility helpers for running MemoryHub on local/dev machines.

These patch *runtime* behaviour only; no ``memoryhub`` source file is touched.

NOTE (2026-08-08): the two underlying bugs are now **fixed in memoryhub** — see
``docs/DATA_FLOW_UPDATE.md``. This module is kept purely as a fallback for
checkouts that predate the fix; it is safe (and a no-op in effect) to keep
applying it, and equally safe to drop.

1. ``re._parser`` / ``re._constants`` shim — some Python builds (e.g. this
   repo's conda envs) do not expose ``re._parser``, which
   ``memoryhub.safety_rules.regex_safety`` requires. ``regex_safety`` now falls
   back to ``sre_parse``/``sre_constants`` natively, so this shim is only
   needed for unfixed versions. On Kylin's standard CPython this is a no-op.
2. ``EventRepository.save/batch_save`` patch — the safety gate hands approved
   events whose ``payload`` is an immutable mapping wrapper that SQLAlchemy's
   JSON column cannot serialize, so a clean ALLOW/MASK event fails to persist
   with ``TypeError: Object of type _ImmutableMapping is not JSON serializable``.
   ``EventRepository._to_row`` now projects via ``model_dump(mode="json")``, so
   this patch is only needed for unfixed versions.
3. ``ensure_safety_keys`` — auto-generates the 32-byte Base64 keys the safety
   gate requires, so the service boots without manual key setup. In dev mode
   the generated keys are persisted to a file and reused across restarts,
   otherwise the HMAC audit chain breaks on the next boot (``audit.head_invalid``).
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path


def apply_re_parser_shim() -> None:
    """Expose ``re._parser`` / ``re._constants`` when the Python build lacks them."""
    import re

    if hasattr(re, "_parser") and hasattr(re, "_constants"):
        return
    import sre_constants
    import sre_parse

    if not hasattr(re, "_parser"):
        re._parser = sre_parse
    if not hasattr(re, "_constants"):
        re._constants = sre_constants


def patch_event_repository() -> None:
    """Normalise safe-event payloads so EventRepository can persist them."""
    from memoryhub.adapter.schemas import MemoryEvent
    from memoryhub.storage.database import EventRepository

    def _plain(event: MemoryEvent) -> MemoryEvent:
        if isinstance(event.payload, dict):
            return event
        return MemoryEvent.model_validate(event.model_dump(mode="python"))

    original_save = EventRepository.save
    original_batch = EventRepository.batch_save

    def patched_save(self, event):
        return original_save(self, _plain(event))

    def patched_batch(self, events):
        return original_batch(self, [_plain(e) for e in events])

    EventRepository.save = patched_save
    EventRepository.batch_save = patched_batch


_KEY_NAMES = ("MEMORYHUB_AUDIT_HMAC_KEY", "MEMORYHUB_QUARANTINE_KEY", "MEMORYHUB_USER_RULE_KEY")


def load_or_create_keys(key_file: str | Path) -> dict[str, str]:
    """Return {env_name: base64key}, loading from ``key_file`` or generating once.

    Dev mode: keys must stay stable across restarts so the on-disk audit chain
    (HMAC-signed head/records) keeps verifying. Never reuse across environments.
    """
    path = Path(key_file)
    keys: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name in _KEY_NAMES and value:
                keys[name] = value
    missing = [name for name in _KEY_NAMES if name not in keys]
    if missing:
        for name in missing:
            keys[name] = base64.b64encode(secrets.token_bytes(32)).decode()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        path.write_text(
            "".join(f"{name}={keys[name]}\n" for name in _KEY_NAMES),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"[memoryhub] 已生成并持久化安全密钥: {path}", flush=True)
    else:
        print(f"[memoryhub] 复用已持久化安全密钥: {path}", flush=True)
    return keys


def ensure_safety_keys(key_file: str | Path | None = None) -> dict[str, str]:
    """Auto-generate (once) the safety keys and export them to the environment."""
    keys = load_or_create_keys(key_file) if key_file else {n: os.environ.get(n, "") for n in _KEY_NAMES}
    for name in _KEY_NAMES:
        value = os.environ.get(name, "").strip() or keys.get(name, "")
        if not value:
            value = base64.b64encode(secrets.token_bytes(32)).decode()
            print(
                f"[memoryhub] {name} 未设置，已自动生成临时 32 字节密钥。"
                "生产环境请通过密钥服务注入真实密钥。",
                flush=True,
            )
        os.environ[name] = value
    return {name: os.environ[name] for name in _KEY_NAMES}
