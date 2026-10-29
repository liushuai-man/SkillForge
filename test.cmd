@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
uv run --no-sync python scripts/test.py %*
exit /b %errorlevel%
