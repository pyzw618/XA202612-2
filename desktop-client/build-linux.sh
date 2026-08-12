#!/usr/bin/env bash
# Kylin-MemoryHub 桌面客户端 - 麒麟 Linux 构建脚本
# 用法: bash build-linux.sh [release|debug]
set -e
cd "$(dirname "$0")"

MODE="${1:-release}"
BUILD_DIR="build"
if [ "$MODE" = "debug" ]; then
    BUILD_DIR="build-debug"
    CMAKE_TYPE="Debug"
else
    CMAKE_TYPE="Release"
fi

# 麒麟源 Qt 5.15：widgets/network/charts
cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE="$CMAKE_TYPE"
cmake --build "$BUILD_DIR" -j"$(nproc)"

echo
echo "[OK] 构建完成: $BUILD_DIR/memoryhub-client"
echo "[运行] ./$BUILD_DIR/memoryhub-client"
