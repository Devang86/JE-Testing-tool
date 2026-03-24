@echo off
title KKC JE Testing Tool
color 0A

echo.
echo  =========================================================
echo   KKC ^& Associates LLP
echo   Journal Entry Testing Tool  v1.0.0
echo  =========================================================
echo.
echo   SA 240 compliant ^| Fully offline ^| Audit-grade
echo.
echo  ---------------------------------------------------------
echo   Starting the application...
echo   This window must stay open while you use the tool.
echo   To stop the tool, close this window or press Ctrl+C.
echo  ---------------------------------------------------------
echo.

REM Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not found in PATH.
    echo.
    echo  Please install Python 3.11 or later from:
    echo  https://www.python.org/downloads/
    echo.
    echo  Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM Check Streamlit is installed
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo  Streamlit not found. Installing required packages...
    echo  ^(This only happens once on first run^)
    echo.
    pip install -r requirements.txt
    echo.
)

REM Launch the app
streamlit run app.py

echo.
echo  The tool has stopped.
pause
