@echo off
set PYTHONIOENCODING=utf-8
title Self-Whisper Speech to Text (Gemini Live)

rem Windowless launch: logs and dictation history live in Settings -> Logs.
rem (Use run_debug.bat if you need the old console window for troubleshooting.)
rem Requires: uv sync --locked (deps come from uv.lock)

where uv >nul 2>&1
if not errorlevel 1 (
    start "" /min uv run --no-sync pythonw -m self_whisper
    exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
    echo [WARN] uv not found; running without locked env.
    start "" /min pythonw -m self_whisper
    exit /b 0
)

echo [ERROR] Neither uv nor Python found in PATH!
echo Install Python from python.org and run: pip install uv ^&^& uv sync
pause
exit /b 1
