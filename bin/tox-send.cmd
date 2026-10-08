@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tox-send.ps1" %*
