@echo off
REM Revenue Recovery Desk - one-click launcher (Windows)
REM Double-click this file to start the app, or run it from a terminal.

REM Move to this script's folder so it works from anywhere.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv
    echo Create it first:  python -m venv .venv  ^&^&  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting Revenue Recovery Desk...
echo The app will open in your browser at http://localhost:8501
echo Press Ctrl+C in this window to stop the app.
echo.

".venv\Scripts\python.exe" -m streamlit run app.py

REM Keep the window open if Streamlit exits with an error.
if errorlevel 1 pause
