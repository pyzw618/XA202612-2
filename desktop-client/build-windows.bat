@echo off
REM ============================================================
REM Kylin-MemoryHub 桌面客户端 - Windows 构建脚本（MSVC + Qt 5.15）
REM 用法: build-windows.bat [release|debug]
REM 前置: Qt 5.15 msvc2019_64 已安装到 C:\Qt\5.15.2\msvc2019_64
REM       或修改 QT_ROOT 指向你的 Qt 安装目录
REM ============================================================
setlocal enabledelayedexpansion

set "QT_ROOT=C:\Qt\5.15.2\msvc2019_64"
set "BUILD_MODE=%~1"
if "%BUILD_MODE%"=="" set "BUILD_MODE=release"

REM 定位 VS2022 vcvars
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
) else if exist "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
) else (
    echo [ERROR] vcvars64.bat not found. Please set VS path manually.
    exit /b 1
)

if "%BUILD_MODE%"=="debug" (
    set "CMAKE_BUILD_TYPE=Debug"
    set "BUILD_DIR=build-debug"
) else (
    set "CMAKE_BUILD_TYPE=Release"
    set "BUILD_DIR=build-release"
)

cmake -S . -B %BUILD_DIR% -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=%CMAKE_BUILD_TYPE% -DCMAKE_PREFIX_PATH=%QT_ROOT%
if errorlevel 1 exit /b 1

cmake --build %BUILD_DIR% --config %CMAKE_BUILD_TYPE% -j8
if errorlevel 1 exit /b 1

echo.
echo [OK] Build finished: %BUILD_DIR%\memoryhub-client.exe
endlocal
