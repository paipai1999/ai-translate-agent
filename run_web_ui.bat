@echo off
title AI Movie Recap - Web UI Dashboard
echo ====================================================
echo Starting AI Movie Recap Dashboard (Web UI)
echo ====================================================
echo.
echo [*] Opening Web Browser at http://127.0.0.1:5000 ...
start http://127.0.0.1:5000
echo [*] Starting Uvicorn Web Server on Port 5000...
.venv\Scripts\python.exe -m uvicorn web_ui:app --host 127.0.0.1 --port 5000
pause
