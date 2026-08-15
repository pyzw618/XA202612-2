"""Start a local MemoryHub REST service for opencode integration.

Config-file mode (recommended for Kylin deployment):
    python scripts/start_memoryhub_server.py --config /path/to/config.yaml

  Builds the app from your ``config.yaml`` (like ``uvicorn memoryhub.app:app``)
  while still applying the runtime compat patches so event writes persist.
  If the config enables ``safety.user_rules`` you must also wire an identity
  resolver, otherwise event ingestion stays disabled — identical to the stock
  server. Point the MCP server's ``MEMORYHUB_API_URL`` at this instance.

Local mode without --config (Kylin OS only):
  - Embedding provider = kylin (real SDK), vector engine = milvus
  - Safety keys auto-generated (see memoryhub_compat.ensure_safety_keys)
  - Applies the two runtime compat patches (see memoryhub_compat)
  - Data directory: default ``opencode-integration/.memoryhub-data``
    (override with --data-dir)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the MemoryHub REST service for opencode")
    parser.add_argument("--host", default="127.0.0.1", help="listen host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="listen port (default 8000)")
    parser.add_argument("--config", default="", help="path to a real config.yaml (production/Kylin)")
    parser.add_argument("--data-dir", default="", help="data directory for the dev-mode database/indexes")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(HERE))

    from memoryhub_compat import apply_re_parser_shim, ensure_safety_keys, patch_event_repository

    apply_re_parser_shim()
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

        data_dir = Path(args.data_dir or Path(__file__).resolve().parents[1] / ".memoryhub-data")
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"[memoryhub] dev-mode data directory: {data_dir}", flush=True)

        config = AppConfig(
            storage=StorageConfig(
                db_path=str(data_dir / "memoryhub.db"),
                vector_index_path=str(data_dir / "vector_index"),
                evidence_path=str(data_dir / "evidence"),
            ),
            embedding=EmbeddingConfig(provider="kylin", dimension=768),
            safety=SafetyConfig(user_rules={"enabled": False}),
        )
        from memoryhub.app import create_app

        app = create_app(config)

    print(f"[memoryhub] serving on http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
