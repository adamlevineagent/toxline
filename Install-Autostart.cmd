@echo off
rem Makes Toxline start (minimized, without opening the viewer) whenever you sign in to Windows.
rem Run Remove-Autostart.cmd to undo.
setlocal
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Toxline.lnk"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath=(Get-Command pythonw.exe).Source;" ^
  "$s.Arguments='-X utf8 \"%~dp0toxlined.py\" --ingress desktop --port 8765';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.WindowStyle=7; $s.Description='Toxline service'; $s.Save()"
if exist "%LNK%" (echo Toxline will start when you sign in.) else (echo Could not create the startup shortcut.)
pause
