@echo off
set PYTHONIOENCODING=utf-8
title Build Self-Whisper Installer

set ISCC="%LocalAppData%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo Installing Inno Setup 6 (winget)...
    winget install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements --location "%LocalAppData%\Inno Setup 6"
    set ISCC="%LocalAppData%\Inno Setup 6\ISCC.exe"
)
if not exist %ISCC% (
    echo [ERROR] Inno Setup compiler (ISCC.exe) not found.
    echo Install it from https://jrsoftware.org/isinfo.php then re-run this script.
    pause
    exit /b 1
)

if not exist "dist\Self-Whisper\Self-Whisper.exe" (
    echo Building the app first...
    call build_exe.bat
    if errorlevel 1 exit /b 1
) else (
    echo Found dist\Self-Whisper - reusing it. Delete dist\ to force a rebuild.
)

echo.
echo Compiling installer...
%ISCC% installer.iss
if errorlevel 1 (
    echo [ERROR] Installer build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Installer OK: installer-out\Self-Whisper-Setup-2.0.0.exe
echo Users pick the install folder in the wizard. No admin needed.
echo ============================================================
pause
