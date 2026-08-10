#!/usr/bin/env python3
"""Build the Kylin mock C libraries with zig cc.

Usage (from repo root, using the project venv python):
    D:/project/XA202612-2/.venv/Scripts/python.exe third_party/kylin-mock/build_mock.py

Outputs land in third_party/kylin-mock/build/:
    libkylin-coreai-embedding-mock.(dll|so|dylib)
    libkysdk-vector-engine-client-capi-mock.(dll|so|dylib)
"""

import os
import platform
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(HERE, "build")

TARGETS = [
    ("embedding_mock.c", "libkylin-coreai-embedding-mock"),
    ("vector_engine_mock.c", "libkysdk-vector-engine-client-capi-mock"),
]

LIB_SUFFIX = {
    "Windows": ".dll",
    "Darwin": ".dylib",
}.get(platform.system(), ".so")


def build_one(source: str, out_name: str) -> str:
    out_path = os.path.join(BUILD_DIR, out_name + LIB_SUFFIX)
    cmd = [
        sys.executable, "-m", "ziglang", "cc",
        "-shared", "-O2",
        "-o", out_path,
        os.path.join(HERE, source),
    ]
    if platform.system() == "Linux":
        cmd.append("-lm")
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return out_path


def main() -> None:
    os.makedirs(BUILD_DIR, exist_ok=True)
    outputs = [build_one(src, name) for src, name in TARGETS]
    print("Built:")
    for path in outputs:
        print(" ", path)


if __name__ == "__main__":
    main()
