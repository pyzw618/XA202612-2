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
3. ``ensure_safety_keys`` — backwards-compatible wrapper around MemoryHub's
   persistent core key store.
"""

from __future__ import annotations

import base64
import os


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


def ensure_safety_keys(config=None):
    if config is None:
        from memoryhub.config import AppConfig

        config = AppConfig()
    from memoryhub.core.safety.key_store import provision_safety_keys

    resolution = provision_safety_keys(config)
    env_names = {
        "audit_hmac": config.safety.audit.hmac_key_env,
        "quarantine": config.safety.quarantine.encryption_key_env,
        "user_rule": config.safety.user_rules.encryption_key_env,
    }
    for name, env_name in env_names.items():
        if not os.environ.get(env_name, "").strip():
            os.environ[env_name] = base64.b64encode(resolution.key(name)).decode("ascii")
    return resolution
