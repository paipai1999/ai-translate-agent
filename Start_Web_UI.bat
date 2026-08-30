@echo off
chcp 65001 >nul
title AI Movie Recap Generator - Web UI Launcher
color 0A
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
cls
echo ===============================================================================
echo            🌐 STARTING AI MOVIE RECAP WEB UI DASHBOARD... 🌐
echo ===============================================================================
echo.
echo Launching your local web server...
echo Your browser should open automatically at: http://localhost:5000
echo.
echo Press Ctrl+C in this command window anytime to shut down the server.
echo.
start http://localhost:5000
"%PYTHON_EXE%" web_ui.py
pause
