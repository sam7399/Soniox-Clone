# PyInstaller spec for GlobalVoice AI (build on Windows).
# Usage:  pyinstaller build/GlobalVoiceAI.spec
import os
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # FFmpeg binaries must be downloaded first: build/get_ffmpeg.ps1
        (str(ROOT / "build" / "ffmpeg"), "ffmpeg"),
    ],
    hiddenimports=[
        "sqlalchemy.dialects.sqlite",
        "sounddevice",
        "pyttsx3.drivers", "pyttsx3.drivers.sapi5",
        "keyring.backends.Windows",
        "docx", "openpyxl", "reportlab",
        "websocket", "keyboard",
    ],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter"],
    hookspath=[],
    runtime_hooks=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GlobalVoiceAI",
    icon=str(ROOT / "assets" / "app.ico")
        if (ROOT / "assets" / "app.ico").exists() else None,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    name="GlobalVoiceAI",
)
