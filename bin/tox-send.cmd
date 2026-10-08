@echo off
setlocal DisableDelayedExpansion
rem cmd can expand %%VARS%% before this shim runs, so inline text must be refused.
set "TOXLINE_CMD_SHIM=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tox-send.ps1" %*
exit /b %errorlevel%
