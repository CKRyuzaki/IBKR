@echo off
rem Daily market-data snapshot (read-only): IBKR futures + equities -> CSV archive -> Postgres, plus public rates.
rem Needs IB Gateway logged in on the PAPER account. Scheduled by Windows Task Scheduler (see README).
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\daily.log
.venv\Scripts\python.exe -m ibkr_desk.marketdata.jobs >> logs\daily.log 2>&1
echo exit=%errorlevel% >> logs\daily.log
exit /b %errorlevel%
