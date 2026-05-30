@echo off
:: Options Signals — Windows launcher
:: Double-click this file, or create a Desktop shortcut to it.
:: To run the terminal dashboard instead: launch.bat terminal

setlocal
cd /d "%~dp0"

:: Activate virtualenv if present
if exist "..\venv\Scripts\activate.bat" call "..\venv\Scripts\activate.bat"
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

if "%1"=="terminal" (
    python terminal_app.py %*
) else (
    echo Starting Options Signals at http://localhost:8501 ...
    streamlit run app.py --server.port 8501 --server.headless false
)
