@echo off
setlocal
cd /d "%~dp0"
if exist "pyproject.toml" (
    uv run skillforge-vm gui %*
) else (
    skillforge-vm gui %*
)
if errorlevel 1 pause
