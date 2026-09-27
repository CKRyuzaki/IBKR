@echo off
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\python.exe" -m ibkr_desk.dashboard.app
timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:8500
