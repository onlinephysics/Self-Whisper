@echo off
set PYTHONIOENCODING=utf-8
title Build Self-Whisper EXE

where uv >nul 2>&1
if errorlevel 1 (
    echo Installing uv (project manager)...
    pip install uv
    if errorlevel 1 (
        echo [ERROR] Could not install uv.
        pause
        exit /b 1
    )
)

echo Syncing locked dependencies...
uv sync --locked --group dev
if errorlevel 1 (
    echo [ERROR] Dependency sync failed.
    pause
    exit /b 1
)

echo.
echo Building windowless EXE (this takes a few minutes)...
uv run pyinstaller --noconfirm SelfWhisper.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Build OK: dist\Self-Whisper-*\Self-Whisper-*.exe (versioned folder)
echo Copy that folder anywhere and run it - no Python needed.
echo (Your API key stays in Windows Credential Manager.)
echo ============================================================
pause
