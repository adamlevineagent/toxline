@echo off
rem Keeps Toxline running in the background and starts it when you sign in (the installer does this
rem too). Run Remove-Autostart.cmd to undo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
