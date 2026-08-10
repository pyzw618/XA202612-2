"""Start a local MemoryHub REST service for the Claude Code integration.

Local/development mode (default):
    python scripts/start_memoryhub_server.py [--host 127.0.0.1] [--port 8010]

  - Embedding provider = mock, vector engine = faiss, user rules disabled
  - Safety keys auto-generated (see memoryhub_compat.ensure_safety_keys)
  - Applies the two runtime compat patches (see memoryhub_compat)
  - Data directory: default ``claudecode-integration/.memoryhub-data``
    (override with --data-dir)

Config-file mode (closer to a real deployment):
    python scripts/start_memoryhub_server.py --config /path/to/config.yaml

  Builds the app from your ``config.yaml`` (like ``uvicorn memoryhub.app:app``)
  while still applying the runtime compat patches so event writes persist.
  Point the plugin's ``MEMORYHUB_API_URL`` at this instance.

Both the Claude Code plugin and the MemoryHub MCP server talk to this service
over HTTP; it is the single shared backend for every integration.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the MemoryHub REST service for Claude Code")
    parser.add_argument("--host", default="127.0.0.1", help="listen host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8010, help="listen port (default 8010)")
    parser.add_argument("--config", default="", help="path to a real config.yaml (production/Kylin)")
    parser.add_argument("--data-dir", default="", help="data directory for the dev-mode database/indexes")
    parser.add_argument("--reset-dev-data", action="store_true", help="delete the dev data dir before starting")
    return parser.parse_args()


def _load_or_create_dev_keys(data_dir: Path) -> None:
    """Persist dev-mode safety keys so the audit chain stays valid across restarts.

    Dev mode auto-generates random keys per boot; without persistence the next
    boot's new key invalidates the on-disk audit head (``audit.head_invalid``),
    which makes the safety gate unavailable and event writes return 503.
    """
    names = ("MEMORYHUB_AUDIT_HMAC_KEY", "MEMORYHUB_QUARANTINE_KEY", "MEMORYHUB_USER_RULE_KEY")
    if all(os.environ.get(name, "").strip() for name in names):
        return
    keys_path = data_dir / "dev-safety-keys.json"
    keys: dict[str, str] = {}
    if keys_path.exists():
        try:
            keys = json.loads(keys_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            keys = {}
    changed = False
    for name in names:
        if os.environ.get(name, "").strip():
            continue
        value = keys.get(name, "")
        if not value:
            value = base64.b64encode(secrets.token_bytes(32)).decode()
            keys[name] = value
            changed = True
        os.environ[name] = value
    if changed:
        data_dir.mkdir(parents=True, exist_ok=True)
        keys_path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
        print(f"[memoryhub] dev safety keys persisted to {keys_path}", flush=True)


def main() -> None:
    args = _parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(HERE))

    from memoryhub_compat import apply_re_parser_shim, ensure_safety_keys, patch_event_repository

    apply_re_parser_shim()

    data_dir = Path(args.data_dir or Path(__file__).resolve().parents[1] / ".memoryhub-data")
    if args.reset_dev_data and not args.config:
        import shutil

        shutil.rmtree(data_dir, ignore_errors=True)
        print(f"[memoryhub] reset dev data directory: {data_dir}", flush=True)

    if args.config:
        ensure_safety_keys()
    else:
        _load_or_create_dev_keys(data_dir)
        ensure_safety_keys()

    patch_event_repository()

    import uvicorn

    if args.config:
        from memoryhub.app import create_app
        from memoryhub.config import load_config

        print(f"[memoryhub] loading config from {args.config}", flush=True)
        app = create_app(load_config(args.config))
    else:
        from memoryhub.config import AppConfig, EmbeddingConfig, SafetyConfig, StorageConfig

        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"[memoryhub] dev-mode data directory: {data_dir}", flush=True)

        config = AppConfig(
            storage=StorageConfig(
                db_path=str(data_dir / "memoryhub.db"),
                vector_index_path=str(data_dir / "vector_index"),
                evidence_path=str(data_dir / "evidence"),
            ),
            embedding=EmbeddingConfig(provider="mock", dimension=64),
            safety=SafetyConfig(
                user_rules={"enabled": False},
                # 审计链与隔离区默认落在仓库 data/ 下（与 db 无关，且随机密钥
                # 每 boot 变化会让旧 head 失效）；dev 模式把它们也收进 data_dir，
                # 使 --reset-dev-data 能整体清理、密钥持久化后跨重启稳定。
                audit={"directory": str(data_dir / "safety-audit")},
                quarantine={"directory": str(data_dir / "review-quarantine")},
            ),
        )
        from memoryhub.app import create_app

        app = create_app(config)

    print(f"[memoryhub] serving on http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
