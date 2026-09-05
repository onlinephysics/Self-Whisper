@echo off
set PYTHONIOENCODING=utf-8
title Self-Whisper Speech to Text (Gemini Live)

rem Windowless launch: logs and dictation history live in Settings -> Logs.
rem (Use run_debug.bat if you need the old console window for troubleshooting.)

where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" /min pythonw main.py
    exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
    start "" /min python main.py
    exit /b 0
)

echo [ERROR] Python is not found in PATH!
echo Please install Python from python.org and add it to PATH.
pause
exit /b 1
