@echo off
REM Memory Engine — Windows Quick Setup
REM Run this from the repo root: setup.bat

echo [*] Memory Engine — Windows Setup
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [-] Python not found. Install from https://python.org
    pause
    exit /b 1
)

REM Install dependencies
echo [*] Installing dependencies...
pip install -r requirements.txt
echo.

REM Run cross-platform setup
echo [*] Running setup...
python setup.py
echo.

echo [+] Done! Start the viewer with:
echo     python memory_engine\viewer.py
echo.
echo [i] Dashboard: http://localhost:37888
pause
