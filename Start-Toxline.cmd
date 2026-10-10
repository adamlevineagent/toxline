@echo off
rem Opens Toxline. The first time, it sets everything up (Python if needed, the Tox library,
rem background running, shortcuts). Safe to run any time.
setlocal
cd /d "%~dp0"
set "PORT=8765"
if defined TOXLINE_PORT set "PORT=%TOXLINE_PORT%"
set "URL=http://127.0.0.1:%PORT%/"
curl -s -o nul %URL%api/state && goto open

if not exist "state\python.txt" goto setup
if not exist "tox\bin\toxcore.dll" goto setup
set /p PY=<state\python.txt
if not exist "%PY%" goto setup
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"
echo Starting Toxline...
start "" /b "%PYW%" -X utf8 "%~dp0toxline_supervisor.py"
for /l %%i in (1,1,40) do (
  ping -n 2 127.0.0.1 >nul
  curl -s -o nul %URL%api/state && goto open
)
echo.
echo Toxline didn't start. The last lines of state\toxline.log:
echo.
powershell.exe -NoProfile -Command "Get-Content 'state\toxline.log' -Tail 15"
echo.
pause
exit /b 1

:setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 pause
exit /b 0

:open
if not defined TOXLINE_NO_OPEN (start "" msedge --app=%URL% 2>nul || start "" %URL%)
exit /b 0
