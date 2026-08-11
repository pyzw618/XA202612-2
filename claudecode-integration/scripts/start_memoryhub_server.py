"""Start a local MemoryHub REST service for the Claude Code integration.

Local/development mode (default):
    python scripts/start_memoryhub_server.py [--host 127.0.0.1] [--port 8010]

  - Embedding provider = mock, vector engine = faiss, user rules disabled
  - Safety keys generated once by MemoryHub's core persistent key store
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
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the MemoryHub REST service for Claude Code")
    parser.add_argument("--host", default="127.0.0.1", help="listen host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8010, help="listen port (default 8010)")
    parser.add_argument(
        "--config",
        default="",
        help="path to a real config.yaml (production/Kylin)",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="data directory for the dev-mode database/indexes",
    )
    parser.add_argument(
        "--reset-dev-data",
        action="store_true",
        help="delete the dev data dir before starting",
    )
    return parser.parse_args()


def _import_legacy_dev_keys(data_dir: Path) -> None:
    """Import the former dev key JSON into the new core store on next startup."""
    new_path = data_dir / "security" / "safety-keys.json"
    legacy_path = data_dir / "dev-safety-keys.json"
    if not legacy_path.is_file() or legacy_path.is_symlink():
        return
    try:
        if os.name != "nt":
            legacy_path.chmod(0o600)
    except OSError:
        raise RuntimeError("key_store.legacy_dev_file_invalid") from None
    if new_path.exists():
        return
    names = (
        "MEMORYHUB_AUDIT_HMAC_KEY",
        "MEMORYHUB_QUARANTINE_KEY",
        "MEMORYHUB_USER_RULE_KEY",
    )
    try:
        raw = legacy_path.read_bytes()
        if len(raw) > 8 * 1024:
            raise ValueError
        keys = json.loads(raw.decode("utf-8"))
        if not isinstance(keys, dict) or not set(keys).issubset(names):
            raise ValueError
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("key_store.legacy_dev_file_invalid") from None
    decoded: list[bytes] = []
    for name in names:
        if os.environ.get(name, "").strip():
            continue
        value = keys.get(name)
        if not isinstance(value, str):
            raise RuntimeError("key_store.legacy_dev_file_invalid")
        try:
            material = base64.b64decode(value.encode("ascii"), validate=True)
        except (UnicodeError, ValueError):
            raise RuntimeError("key_store.legacy_dev_file_invalid") from None
        if len(material) != 32:
            raise RuntimeError("key_store.legacy_dev_file_invalid")
        decoded.append(material)
        os.environ[name] = value
    if len(set(decoded)) != len(decoded):
        raise RuntimeError("key_store.legacy_dev_key_reuse")


def _build_dev_config(data_dir: str | Path):
    from memoryhub.config import AppConfig, EmbeddingConfig, SafetyConfig, StorageConfig

    resolved = Path(data_dir).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        storage=StorageConfig(
            db_path=str(resolved / "memoryhub.db"),
            vector_index_path=str(resolved / "vector_index"),
            evidence_path=str(resolved / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="mock", dimension=64),
        safety=SafetyConfig(
            key_store={"path": str(resolved / "security" / "safety-keys.json")},
            user_rules={"enabled": False},
            audit={"directory": str(resolved / "safety-audit")},
            quarantine={"directory": str(resolved / "review-quarantine")},
        ),
    )


def main() -> None:
    args = _parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(HERE))

    from memoryhub_compat import apply_re_parser_shim, patch_event_repository

    apply_re_parser_shim()

    data_dir = Path(
        args.data_dir or Path(__file__).resolve().parents[1] / ".memoryhub-data"
    ).expanduser().resolve()
    if args.reset_dev_data and not args.config:
        import shutil

        shutil.rmtree(data_dir, ignore_errors=True)
        print(f"[memoryhub] reset dev data directory: {data_dir}", flush=True)

    if not args.config:
        _import_legacy_dev_keys(data_dir)

    patch_event_repository()

    import uvicorn

    if args.config:
        from memoryhub.app import create_app
        from memoryhub.config import load_config

        print(f"[memoryhub] loading config from {args.config}", flush=True)
        app = create_app(load_config(args.config))
    else:
        print(f"[memoryhub] dev-mode data directory: {data_dir}", flush=True)
        config = _build_dev_config(data_dir)
        from memoryhub.app import create_app

        app = create_app(config)

    print(f"[memoryhub] serving on http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
