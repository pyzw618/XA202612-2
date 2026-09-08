@echo off
call "D:\software\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
set PATH=D:\project\XA202612-2\.venv\Scripts;%PATH%
cmake -S "%~dp0." -B "%~dp0build-regression" -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=D:/conda/Library || exit /b 1
cmake --build "%~dp0build-regression" --target memoryhub-client-frontend-tests || exit /b 1
