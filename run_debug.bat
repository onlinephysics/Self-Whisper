@echo off
set PYTHONIOENCODING=utf-8
title Self-Whisper Speech to Text (DEBUG console)
echo ============================================================
echo Self-Whisper DEBUG mode - console stays open for troubleshooting.
echo All output is also available in Settings -^> Logs.
echo ============================================================
where uv >nul 2>&1
if not errorlevel 1 (
    uv run --no-sync python -m self_whisper
) else (
    rem No uv: run from source layout with system Python (console stays open here).
    set PYTHONPATH=src
    python -m self_whisper
)
if errorlevel 1 (
    echo.
    echo Self-Whisper exited with an error.
    pause
)
