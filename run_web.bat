@echo off
setlocal
cd /d "%~dp0"
echo === LabSync Web ===
netstat -ano | findstr /R /C:":3309 .*LISTENING" >nul
if errorlevel 1 (
    echo [ERROR] MySQL is not listening on port 3309.
    echo Start the MySQL80 service from Windows Services first.
    pause
    exit /b 1
)
where py >nul 2>&1
if not errorlevel 1 (
    py app.py
) else (
    python app.py
)
pause
