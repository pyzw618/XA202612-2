#!/usr/bin/env bash
# Windows 本机构建（MSVC + Qt 5.15），中文路径下的可靠构建方式：
# 读取 vcvars64 导出的环境，使用 NMake 生成器。
# 用法: bash build-windows.sh
set -e
cd "$(dirname "$0")"

MSVC_VERSION="14.41.34120"
SDK_VERSION="10.0.22621.0"
VS_ROOT="C:/Program Files/Microsoft Visual Studio/2022/Community"
MSVC_BIN="$VS_ROOT/VC/Tools/MSVC/$MSVC_VERSION/bin/Hostx64/x64"
NMAKE="$MSVC_BIN/nmake.exe"
CL="$MSVC_BIN/cl.exe"
MSVC_INC="$VS_ROOT/VC/Tools/MSVC/$MSVC_VERSION/include;$VS_ROOT/VC/Tools/MSVC/$MSVC_VERSION/ATLMFC/include;$VS_ROOT/VC/Auxiliary/VS/include"
SDK_INC="C:/Program Files (x86)/Windows Kits/10/Include/$SDK_VERSION/ucrt;C:/Program Files (x86)/Windows Kits/10/Include/$SDK_VERSION/um;C:/Program Files (x86)/Windows Kits/10/Include/$SDK_VERSION/shared;C:/Program Files (x86)/Windows Kits/10/Include/$SDK_VERSION/winrt"
MSVC_LIB="$VS_ROOT/VC/Tools/MSVC/$MSVC_VERSION/ATLMFC/lib/x64;$VS_ROOT/VC/Tools/MSVC/$MSVC_VERSION/lib/x64"
SDK_LIB="C:/Program Files (x86)/Windows Kits/10/Lib/$SDK_VERSION/ucrt/x64;C:/Program Files (x86)/Windows Kits/10/Lib/$SDK_VERSION/um/x64"

SDK_BIN="C:/Program Files (x86)/Windows Kits/10/bin/$SDK_VERSION/x64;C:/Program Files (x86)/Windows Kits/10/bin/x64;C:/Program Files (x86)/Microsoft SDKs/Windows/v10.0A/bin/NETFX 4.7 Tools/x64"
export PATH="$MSVC_BIN:$SDK_BIN:$VS_ROOT/Common7/IDE:$VS_ROOT/Common7/Tools:$VS_ROOT/MSBuild/Current/Bin/amd64:$PATH"
export INCLUDE="$MSVC_INC;$SDK_INC"
export LIB="$MSVC_LIB;$SDK_LIB"
export VCToolsInstallDir="$VS_ROOT/VC/Tools/MSVC/$MSVC_VERSION/"

# 注意：MSYS 会把 / 转成路径，用 cmd 内联避免；这里直接调用 cmake(.exe)
CMAKE="/c/Program Files/cmake-3.30.5-windows-x86_64/bin/cmake.exe"
QT_PREFIX="C:/Qt/5.15.2/msvc2019_64"

"$CMAKE" -S . -B build-release -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$QT_PREFIX" \
    -DCMAKE_MAKE_PROGRAM="$NMAKE" \
    -DCMAKE_C_COMPILER="$CL" -DCMAKE_CXX_COMPILER="$CL"
"$CMAKE" --build build-release --config Release
echo "BUILD_OK"
