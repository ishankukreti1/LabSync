@echo off
setlocal
echo ========================================
echo          LabSync Build ^& Run
echo ========================================
echo.

REM Initialize MSVC x64 build environment if cl is not in PATH
where cl >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [Initializing MSVC x64 build environment...]
    call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
)

if not exist "build" (
    mkdir build
)

echo [Configuring CMake...]
cmake -B build -DCMAKE_BUILD_TYPE=Release -DMYSQLCPPCONN_ROOT="C:/Program Files/MySQL/MySQL Connector C++ 26.7" -G "NMake Makefiles"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] CMake configuration failed.
    pause
    exit /b %ERRORLEVEL%
)

echo [Building LabSync.exe...]
cmake --build build
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b %ERRORLEVEL%
)

REM Start MySQL through Windows Services; do not modify server configuration automatically.

echo.
echo ========================================
echo         Launching LabSync Terminal
echo ========================================
echo.
.\build\LabSync.exe
