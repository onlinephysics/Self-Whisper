# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for Self-Whisper (windowless single-folder build)."""

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# PortAudio DLLs live in the "_sounddevice_data" helper package (sounddevice
# itself is a single module, so collecting by that name is skipped).
sounddevice_datas = collect_data_files("_sounddevice_data")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=sounddevice_datas,
    hiddenimports=[
        "keyring.backends.Windows",
        "keyring.backends.fail",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Self-Whisper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowless: logs live in Settings -> Logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Self-Whisper",
)
