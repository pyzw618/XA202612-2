#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${MEMORYHUB_PYTHON:-${PROJECT_ROOT}/.venv/bin/python}"
BIND_HOST="${MEMORYHUB_HOST:-127.0.0.1}"
PORT="${MEMORYHUB_PORT:-8099}"

cd "${PROJECT_ROOT}"
exec "${PYTHON_BIN}" -m uvicorn memoryhub.app:app --host "${BIND_HOST}" --port "${PORT}"
