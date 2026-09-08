@echo off
rem 前端编译/回归测试构建脚本（本机实际工具链路径）
rem C:\mhub-src 为指向 desktop-client 的 ASCII junction（规避中文路径）
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
cmake -S C:/mhub-src -B C:/mhub-build -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:/Qt/5.15.2/msvc2019_64 || exit /b 1
cmake --build C:/mhub-build --target memoryhub-client memoryhub-client-frontend-tests memoryhub-client-api-tests || exit /b 1
