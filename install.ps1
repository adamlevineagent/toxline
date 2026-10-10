# Toxline installer. One line in PowerShell does everything:
#
#   irm https://raw.githubusercontent.com/adamlevineagent/toxline/main/install.ps1 | iex
#
# It puts Toxline in %LOCALAPPDATA%\Toxline (or uses the folder this script is in), installs Python
# if you don't have it (asks first), downloads the Tox library, keeps Toxline running in the
# background (restarted if it stops, started when you sign in), adds Start menu and desktop
# shortcuts, offers the Claude Code skill, and opens Toxline. Safe to run again: it updates the code
# and keeps your settings, contacts and Tox ID.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$port = if ($env:TOXLINE_PORT) { $env:TOXLINE_PORT } else { '8765' }
$api = "http://127.0.0.1:$port/api/state"

function Say($msg) { Write-Host "  $msg" }
function Ask($q) {
  if ($env:TOXLINE_YES -eq '1') { return $true }
  $a = Read-Host "  $q [Y/n]"
  return ($a -eq '' -or $a -match '^[yY]')
}

Write-Host ""
Write-Host "  Toxline setup" -ForegroundColor Green
Write-Host "  -------------"

# 1. Where Toxline lives --------------------------------------------------------------------------
$here = if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'toxlined.py'))) { $PSScriptRoot } else { $null }
if ($here) {
  $app = $here
  Say "Using this folder: $app"
} else {
  $app = Join-Path $env:LOCALAPPDATA 'Toxline'
  Say "Downloading Toxline into $app ..."
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("toxline-" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory $tmp | Out-Null
  try {
    Invoke-WebRequest 'https://github.com/adamlevineagent/toxline/archive/refs/heads/main.zip' -OutFile "$tmp\t.zip" -UseBasicParsing
    Expand-Archive "$tmp\t.zip" $tmp
    New-Item -ItemType Directory -Force $app | Out-Null
    # Code is replaced; state\ (settings, contacts, your Tox ID) and tox\bin are kept.
    Copy-Item "$tmp\toxline-main\*" $app -Recurse -Force
  } finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
Get-ChildItem $app -Recurse -File | Unblock-File -ErrorAction SilentlyContinue   # downloaded scripts run without nags
New-Item -ItemType Directory -Force (Join-Path $app 'state') | Out-Null

# 2. Python ----------------------------------------------------------------------------------------
function Find-Python {
  $cands = @()
  foreach ($c in @('py', 'python')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $cands += , @($cmd.Source) }
  }
  $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object { , @($_.FullName) }
  foreach ($c in $cands) {
    $exe = $c[0]
    $args_ = if ($exe -like '*\py.exe') { @('-3', '-c') } else { @('-c') }
    try {
      $out = & $exe @args_ "import sys; print(sys.executable if sys.version_info >= (3, 11) else '')" 2>$null
      if ($out -and (Test-Path $out.Trim())) { return $out.Trim() }
    } catch {}
  }
  return $null
}
$py = Find-Python
if (-not $py) {
  Say "Toxline needs Python 3.11 or newer, and it isn't installed."
  if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask "Install Python now (free, from python.org via winget)?")) {
    Say "Installing Python (a minute or two) ..."
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $py = Find-Python
  }
  if (-not $py) {
    Say "Please install Python 3.11+ from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
    return
  }
}
Set-Content (Join-Path $app 'state\python.txt') $py -Encoding ASCII
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
Say "Python: $py"

# 3. Tox library ---------------------------------------------------------------------------------
& (Join-Path $app 'tox\get-toxcore.ps1') | ForEach-Object { Say $_ }

# 4. Keep it running ------------------------------------------------------------------------------
$sup = Join-Path $app 'toxline_supervisor.py'
$wsh = New-Object -ComObject WScript.Shell
function Shortcut($path, $target, $arguments, $desc, $style = 1) {
  $s = $wsh.CreateShortcut($path)
  $s.TargetPath = $target; $s.Arguments = $arguments; $s.WorkingDirectory = $app
  $s.Description = $desc; $s.WindowStyle = $style
  $s.Save()
}
$links = $env:TOXLINE_SHORTCUTS   # testing only: put shortcuts here instead of the real folders
$startup = if ($links) { $links } else { [Environment]::GetFolderPath('Startup') }
Shortcut (Join-Path $startup 'Toxline.lnk') $pyw "-X utf8 `"$sup`"" 'Keeps Toxline running' 7
$launcher = Join-Path $app 'Start-Toxline.cmd'
$menu = if ($links) { Join-Path $links 'menu' } else { [Environment]::GetFolderPath('Programs') }
$desk = if ($links) { Join-Path $links 'desktop' } else { [Environment]::GetFolderPath('Desktop') }
New-Item -ItemType Directory -Force $menu, $desk | Out-Null
Shortcut (Join-Path $menu 'Toxline.lnk') $launcher '' 'Open Toxline' 7
Shortcut (Join-Path $desk 'Toxline.lnk') $launcher '' 'Open Toxline' 7
Say "Toxline will keep running in the background and start when you sign in."
Say "Shortcuts: Start menu and desktop -> Toxline."

$up = $false
try { Invoke-RestMethod $api -TimeoutSec 3 | Out-Null; $up = $true } catch {}
$other = $false
if ($up) {
  # Updating a running install: restart it on the new code (its supervisor brings it back). Only if it
  # runs from this folder; a Toxline installed somewhere else is left alone.
  $l = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  $p = if ($l) { Get-CimInstance Win32_Process -Filter "ProcessId=$($l.OwningProcess)" } else { $null }
  if ($p -and $p.CommandLine -like "*$app*" -and -not $here) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $up = $false; Start-Sleep 2
  } elseif ($p -and $p.CommandLine -notlike "*$app*") {
    Say "Another Toxline is already running on this PC on port $port (installed in another folder). Leaving it alone."
    $other = $true
  }
}
if (-not $other) { Start-Process $pyw -ArgumentList '-X', 'utf8', "`"$sup`"" -WorkingDirectory $app -WindowStyle Hidden }

# 5. Claude Code skill (optional) --------------------------------------------------------------------
$claude = Join-Path $env:USERPROFILE '.claude'
if ((Test-Path $claude) -and $env:TOXLINE_SKILL -ne '0' -and (Ask "You use Claude Code: install the Toxline skill so Claude can run Toxline for you?")) {
  $dir = Join-Path $claude 'skills\toxline'
  New-Item -ItemType Directory -Force $dir | Out-Null
  $text = [IO.File]::ReadAllText((Join-Path $app 'skill\toxline\SKILL.md')).Replace('{{TOXLINE_DIR}}', $app)
  [IO.File]::WriteAllText((Join-Path $dir 'SKILL.md'), $text, (New-Object Text.UTF8Encoding $false))
  Say "Claude skill installed. Start a new Claude Code session and ask it about Toxline."
}

# 6. Open it --------------------------------------------------------------------------------------
for ($i = 0; $i -lt 60; $i++) {
  try { Invoke-RestMethod $api -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep 1 }
}
if (-not $up) {
  Say "Toxline didn't start. The end of its log:"
  Get-Content (Join-Path $app 'state\toxline.log') -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Say $_ }
  return
}
if (-not (Get-ChildItem '\\.\pipe\' | Where-Object Name -like 'codex-browser-use-*')) {
  Say "Note: open Codex Desktop too. That's where your agent's threads live."
}
Write-Host ""
Say "Done. Opening Toxline (next time: the Toxline shortcut)."
if ($env:TOXLINE_NO_OPEN -ne '1') { Start-Process "http://127.0.0.1:$port/" }
