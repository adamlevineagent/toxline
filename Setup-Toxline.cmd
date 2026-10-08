@echo off
rem One-time setup: checks Python, downloads the prebuilt Tox library, and tests it.
rem Safe to run again. Afterwards, double-click Start-Toxline.cmd.
setlocal
cd /d "%~dp0"
echo.
echo  Toxline setup
echo  -------------
where python >nul 2>nul || goto nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || goto oldpython
for /f "delims=" %%v in ('python -c "import sys; print(sys.version.split()[0])"') do echo Python %%v: OK
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tox\get-toxcore.ps1" || goto failed
echo Testing Tox on this machine (two local nodes talk to each other, about 15 seconds)...
python -X utf8 tox\selftest.py --no-internet > "%TEMP%\toxline-selftest.txt" 2>&1 || goto selftest
echo Tox self-test: PASS
powershell.exe -NoProfile -Command "if (-not ([IO.Directory]::GetFiles('\\.\pipe\') -match 'codex-browser-use-')) { exit 1 }" && (echo Codex Desktop: running) || (echo Codex Desktop: not open. Open it before Start-Toxline.cmd.)
echo.
echo  Setup done. Next: double-click Start-Toxline.cmd
echo.
pause
exit /b 0

:nopython
echo Python isn't installed (or isn't on PATH). Install Python 3.11+ from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" in the installer, then run this again.
pause
exit /b 1
:oldpython
echo Toxline needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ and run this again.
pause
exit /b 1
:selftest
echo The Tox self-test failed. Details: %TEMP%\toxline-selftest.txt
echo If it mentions vcruntime140.dll, install the Microsoft Visual C++ Redistributable (x64):
echo https://aka.ms/vs/17/release/vc_redist.x64.exe
pause
exit /b 1
:failed
echo Setup failed (see the message above).
pause
exit /b 1
