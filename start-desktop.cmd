@echo off
setlocal
cd /d "%~dp0"
if not exist "desktop\node_modules\electron\dist\electron.exe" (
    echo 请先执行 uv sync 和 npm --prefix desktop ci
    pause
    exit /b 1
)
"desktop\node_modules\electron\dist\electron.exe" desktop %*
if errorlevel 1 pause
