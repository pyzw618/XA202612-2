# Windows 本机构建（MSVC + Qt 5.15）
# 通过 ASCII junction（C:\mhub-src -> desktop-client）规避中文路径在
# moc/链接器/PDB 中的破坏问题。
$ErrorActionPreference = "Stop"

$vcvars = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
$srcDir = "C:/mhub-src"
$buildDir = "C:/mhub-build"

$cmds = "call `"$vcvars`" && cmake -S $srcDir -B $buildDir -G `"NMake Makefiles`" -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:/Qt/5.15.2/msvc2019_64 && cmake --build $buildDir --config Release"

cmd /c $cmds
if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD_FAILED" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "BUILD_OK" -ForegroundColor Green
