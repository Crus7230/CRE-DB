@echo off
setlocal
for %%I in ("%~dp0..\..") do set "CRE_WORKSPACE_ROOT=%%~fI"
set "CRE_REFRESH_PYTHON=%CRE_WORKSPACE_ROOT%\.codex_tmp\cre-dashboard-venv\Scripts\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "%CRE_REFRESH_PYTHON%" (
  echo Stable CRE refresh Python is missing. 1>&2
  exit /b 2
)
"%CRE_REFRESH_PYTHON%" "%~dp0run_source_aware_refresh.py" --due --apply --allow-live-db --publish-if-enabled --config "%~dp0..\config\source-aware-refresh.json"
exit /b %ERRORLEVEL%
