@echo off
set PYTHONIOENCODING=utf-8
title Self-Whisper Speech to Text (Gemini Live)

rem Windowless launch: logs and dictation history live in Settings -> Logs.
rem (Use run_debug.bat if you need the old console window for troubleshooting.)
rem Uses the locked project environment directly via pythonw, so NO console
rem window appears. (Never route this through "uv run": uv is a console
rem program and would leave a blank black window open for the app lifetime.)

if exist ".venv\Scripts\pythonw.exe" (
    start "" /min ".venv\Scripts\pythonw.exe" -m self_whisper
    exit /b 0
)

where uv >nul 2>&1
if not errorlevel 1 (
    echo First run: creating the locked environment...
    uv sync --locked
    if exist ".venv\Scripts\pythonw.exe" (
        start "" /min ".venv\Scripts\pythonw.exe" -m self_whisper
        exit /b 0
    )
)

where pythonw >nul 2>&1
if not errorlevel 1 (
    echo [WARN] Locked environment not found; running with system Python.
    set PYTHONPATH=src
    start "" /min pythonw -m self_whisper
    exit /b 0
)

echo [ERROR] Could not launch Self-Whisper.
echo Install Python from python.org, then run: pip install uv ^&^& uv sync
pause
exit /b 1
