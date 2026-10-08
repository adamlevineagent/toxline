@echo off
rem Starts Toxline and opens the viewer. The only thing you need to double-click:
rem the first run also checks Python and downloads the Tox library. Safe to run again.
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PORT=8765"
if defined TOXLINE_PORT set "PORT=%TOXLINE_PORT%"
set "URL=http://127.0.0.1:%PORT%/"
curl -s -o nul %URL%api/state && goto open

echo.
echo  Starting Toxline
echo  ----------------
where python >nul 2>nul || goto nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || goto oldpython
if not exist "tox\bin\toxcore.dll" (
  echo First run: downloading the Tox library...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tox\get-toxcore.ps1" || goto failed
)
powershell.exe -NoProfile -Command "if (-not ([IO.Directory]::GetFiles('\\.\pipe\') -match 'codex-browser-use-')) { exit 1 }" || echo Note: Codex Desktop isn't open. Open it: that's where your agents' threads live.
if not exist state mkdir state
echo Starting the service (log: state\toxline.log)...
start "Toxline service" /min cmd /c "python -X utf8 toxlined.py --ingress desktop --port %PORT% >> state\toxline.log 2>&1"
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

:open
echo Toxline is running: %URL%  (it joins the Tox network within about 30 seconds)
if not defined TOXLINE_NO_OPEN (start "" msedge --app=%URL% 2>nul || start "" %URL%)
exit /b 0

:nopython
echo Python isn't installed (or isn't on PATH). Install Python 3.11+ from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, then run this again.
pause
exit /b 1
:oldpython
echo Toxline needs Python 3.11 or newer: https://www.python.org/downloads/
pause
exit /b 1
:failed
echo Couldn't download the Tox library (see above). Check your internet connection and run this again.
pause
exit /b 1
