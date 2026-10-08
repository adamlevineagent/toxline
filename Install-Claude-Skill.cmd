@echo off
rem Installs the "toxline" skill for Claude Code, pointed at this Toxline folder.
rem Run it again after moving the Toxline folder.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$src = Join-Path (Get-Location) 'skill\toxline\SKILL.md';" ^
  "$dir = Join-Path $env:USERPROFILE '.claude\skills\toxline';" ^
  "New-Item -ItemType Directory -Force $dir | Out-Null;" ^
  "$text = [IO.File]::ReadAllText($src).Replace('{{TOXLINE_DIR}}', (Get-Location).Path);" ^
  "[IO.File]::WriteAllText((Join-Path $dir 'SKILL.md'), $text, (New-Object Text.UTF8Encoding $false));" ^
  "Write-Host ('Installed the toxline skill in ' + $dir)" || goto failed
echo Restart Claude Code (or start a new session), then ask it things like "what's happening in Toxline?"
pause
exit /b 0
:failed
echo Couldn't install the skill (see above).
pause
exit /b 1
