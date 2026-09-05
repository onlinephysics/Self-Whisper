@echo off
set PYTHONIOENCODING=utf-8
title Build Self-Whisper EXE

echo Installing builder (PyInstaller)...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Could not install PyInstaller.
    pause
    exit /b 1
)

echo.
echo Building windowless EXE (this takes a few minutes)...
pyinstaller --noconfirm SelfWhisper.spec
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
