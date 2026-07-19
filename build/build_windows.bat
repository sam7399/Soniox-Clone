@echo off
REM ============================================================
REM  GlobalVoice AI - one-command Windows build
REM  Requires: Python 3.12+ (64-bit) on PATH, internet connection
REM  Run from the project root:  build\build_windows.bat
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/5] Creating virtual environment...
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat

echo [2/5] Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [3/5] Downloading FFmpeg (if missing)...
powershell -ExecutionPolicy Bypass -File build\get_ffmpeg.ps1
if errorlevel 1 goto :fail

echo [4/5] Running tests...
python -m pytest tests -q
if errorlevel 1 (
    echo Tests failed - fix before shipping. & goto :fail
)

echo [5/5] Building executable with PyInstaller...
pyinstaller build\GlobalVoiceAI.spec --noconfirm
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  Build complete:  dist\GlobalVoiceAI\GlobalVoiceAI.exe
echo  To create the installer, open build\installer.iss with
echo  Inno Setup 6 and press Compile (or run iscc build\installer.iss)
echo  Portable version: copy dist\GlobalVoiceAI anywhere and create
echo  an empty file named portable.flag next to the exe.
echo ============================================================
exit /b 0

:fail
echo BUILD FAILED - see messages above.
exit /b 1
