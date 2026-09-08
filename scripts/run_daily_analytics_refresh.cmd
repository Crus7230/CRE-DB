@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "UV=%LOCALAPPDATA%\hermes\bin\uv.exe"
if not exist "%UV%" exit /b 70
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"
for %%A in ("%ROOT%\logs\daily-analytics-task.log") do if %%~zA GTR 10485760 move /Y "%%~fA" "%%~fA.1" >nul 2>&1
cd /d "%ROOT%"
set "PYTHONIOENCODING=utf-8"
"%UV%" run --with "psycopg[binary]" python "%ROOT%\scripts\run_market_refresh_pipeline.py" --db "%ROOT%\data\market.db" --apply --allow-live-db --max-attempts 3 --sync-if-enabled >> "%ROOT%\logs\daily-analytics-task.log" 2>&1
set "RC=%ERRORLEVEL%"
exit /b %RC%
