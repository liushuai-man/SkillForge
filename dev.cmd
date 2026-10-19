@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
uv run python scripts/dev.py %*
if errorlevel 1 (
    pause
    exit /b 1
)
