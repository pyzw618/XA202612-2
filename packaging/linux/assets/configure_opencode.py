#!/usr/bin/env python3
"""Safely register MemoryHub in an OpenCode JSON/JSONC configuration."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def _strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas without touching strings."""

    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                index += 1
            if index + 1 >= len(text):
                raise ValueError("unterminated block comment in OpenCode configuration")
            index += 2
            continue
        output.append(char)
        index += 1

    without_comments = "".join(output)
    output = []
    index = 0
    in_string = False
    escaped = False
    while index < len(without_comments):
        char = without_comments[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(without_comments) and without_comments[lookahead].isspace():
                lookahead += 1
            if lookahead < len(without_comments) and without_comments[lookahead] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _config_path(opencode_root: Path) -> Path:
    jsonc_path = opencode_root / "opencode.jsonc"
    json_path = opencode_root / "opencode.json"
    if jsonc_path.exists():
        return jsonc_path
    if json_path.exists():
        return json_path
    return jsonc_path


def register_mcp(opencode_root: Path, launcher: Path, user_id: str) -> Path:
    opencode_root.mkdir(parents=True, exist_ok=True)
    config_path = _config_path(opencode_root)
    config: dict[str, object] = {}
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8")
        try:
            parsed = json.loads(_strip_jsonc(original))
        except (json.JSONDecodeError, ValueError) as error:
            raise SystemExit(
                f"memoryhub: cannot update invalid OpenCode config {config_path}: {error}"
            ) from error
        if not isinstance(parsed, dict):
            raise SystemExit(f"memoryhub: OpenCode config root must be an object: {config_path}")
        config = parsed
        backup_path = config_path.with_name(config_path.name + ".memoryhub-backup")
        if not backup_path.exists():
            shutil.copy2(config_path, backup_path)

    mcp = config.get("mcp")
    if mcp is None:
        mcp = {}
        config["mcp"] = mcp
    if not isinstance(mcp, dict):
        raise SystemExit(f"memoryhub: OpenCode 'mcp' setting must be an object: {config_path}")
    mcp["memoryhub"] = {
        "type": "local",
        "command": ["/bin/sh", str(launcher)],
        "environment": {
            "MEMORYHUB_API_URL": "http://127.0.0.1:8099",
            "MEMORYHUB_USER_ID": user_id,
        },
        "enabled": True,
        "timeout": 15000,
    }

    temporary = config_path.with_name(config_path.name + ".memoryhub-new")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, config_path)
    return config_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opencode-root", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    config_path = register_mcp(args.opencode_root, args.launcher, args.user)
    print(f"MemoryHub MCP registered in {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
