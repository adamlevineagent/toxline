@echo off
rem Starts the Toxline service (real Tox + Codex agent threads) and opens the viewer.
rem Safe to double-click again: if it's already running, it just opens the viewer.
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
curl -s -o nul http://127.0.0.1:8765/api/state && goto open
start "Toxline service" /min python -X utf8 toxlined.py --ingress desktop --port 8765
for /l %%i in (1,1,30) do (
  timeout /t 1 /nobreak >nul
  curl -s -o nul http://127.0.0.1:8765/api/state && goto open
)
echo Toxline didn't start. Look at the "Toxline service" window for the error.
pause
exit /b 1
:open
start "" msedge --app=http://127.0.0.1:8765/ 2>nul || start "" http://127.0.0.1:8765/
