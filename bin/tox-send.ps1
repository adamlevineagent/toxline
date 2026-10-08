# tox-send: the agent's way to put words in its Tox guest's chat.
# Pure PowerShell so it runs inside Codex's sandbox (no Python, no escalation).
# Talks to the toxline service over localhost; if the sandbox blocks that, it drops the
# request in toxline's outbox folder and waits for the service's answer file.
#
#   tox-send "message"            send to this thread's guest (found via CODEX_THREAD_ID)
#   tox-send --file reply.md      send a file's contents
#   tox-send --who                who this thread talks to + recent chat
#   tox-send --to W "message"     on a thread shared by several guests: who gets it (name, or all)
param()
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$port = if ($env:TOXLINE_PORT) { $env:TOXLINE_PORT } else { '8765' }
$base = "http://127.0.0.1:$port"
$home_ = if ($env:TOXLINE_HOME) { $env:TOXLINE_HOME } else { Join-Path $root 'state' }
$outbox = Join-Path $home_ 'outbox'

$argv = @($args)
$thread = $env:CODEX_THREAD_ID
$who = $false; $file = $null; $to = $null; $text = @()
for ($i = 0; $i -lt $argv.Count; $i++) {
  switch ($argv[$i]) {
    '--who'    { $who = $true }
    '--file'   { $i++; $file = $argv[$i] }
    '--to'     { $i++; $to = $argv[$i] }
    '--thread' { $i++; $thread = $argv[$i] }
    '--port'   { $i++; $port = $argv[$i]; $base = "http://127.0.0.1:$port" }
    '--home'   { $i++; $home_ = $argv[$i]; $outbox = Join-Path $home_ 'outbox' }
    '-h'       { Get-Content $PSCommandPath | Select-Object -Skip 1 -First 7 | ForEach-Object { $_.TrimStart('# ') }; exit 0 }
    '--help'   { Get-Content $PSCommandPath | Select-Object -Skip 1 -First 7 | ForEach-Object { $_.TrimStart('# ') }; exit 0 }
    default    { $text += $argv[$i] }
  }
}
if ($env:TOXLINE_CMD_SHIM -eq '1' -and ($text.Count -gt 0 -or (-not $file -and -not $who))) {
  # cmd has already expanded %VARS% and may have removed quotes. Even plain-looking
  # text cannot be trusted here; only file contents bypass that argument parsing.
  [Console]::Error.WriteLine('tox-send: inline messages are unsafe through tox-send.cmd. Use --file <path>, or call tox-send.ps1 directly from PowerShell.')
  exit 2
}
if (-not $thread) { [Console]::Error.WriteLine('tox-send: no CODEX_THREAD_ID here; pass --thread <id>'); exit 2 }

function Invoke-Toxline($op, $payload) {
  # 1) localhost HTTP
  try {
    if ($op -eq 'who') {
      return Invoke-RestMethod -Uri "$base/api/whoami?thread_id=$thread&limit=15" -TimeoutSec 15
    }
    $json = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
    return Invoke-RestMethod -Method Post -Uri "$base/api/send" -Body $json -ContentType 'application/json; charset=utf-8' -TimeoutSec 30
  } catch {
    if ($_.Exception.Response) {
      $msg = $_.ErrorDetails.Message
      try { $msg = ($msg | ConvertFrom-Json).error } catch {}
      if (-not $msg) { $msg = $_.Exception.Message }
      [Console]::Error.WriteLine("tox-send: $msg"); exit 1
    }
  }
  # 2) outbox file drop (works when the sandbox blocks network but can write the toxline folder)
  $id = [guid]::NewGuid().ToString('N')
  $req = @{ id = $id; op = $op; thread_id = $thread; body = $payload.body; to = $payload.to }
  $tmp = Join-Path $outbox "$id.tmp"; $final = Join-Path $outbox "$id.req.json"
  try {
    [IO.File]::WriteAllText($tmp, ($req | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    Move-Item $tmp $final
  } catch {
    [Console]::Error.WriteLine("tox-send: can't reach toxline (no localhost access and can't write $outbox). Is Toxline running?"); exit 1
  }
  $res = Join-Path $outbox "$id.res.json"
  for ($t = 0; $t -lt 150; $t++) {
    if (Test-Path $res) {
      Start-Sleep -Milliseconds 50
      $r = [IO.File]::ReadAllText($res, [Text.Encoding]::UTF8) | ConvertFrom-Json
      Remove-Item $res -ErrorAction SilentlyContinue
      if ($r.error) { [Console]::Error.WriteLine("tox-send: $($r.error)"); exit 1 }
      return $r
    }
    Start-Sleep -Milliseconds 200
  }
  Remove-Item $final -ErrorAction SilentlyContinue   # so a late service start doesn't send it after we said it failed
  [Console]::Error.WriteLine('tox-send: toxline did not answer within 30s, so nothing was sent. Is Toxline running?'); exit 1
}

if ($who) {
  $r = Invoke-Toxline 'who' @{}
  $shared = @($r.contacts).Count -gt 1
  foreach ($c in @($r.contacts)) {
    $hold = if ($c.hold_outgoing -eq 1) { ', OUTGOING ON HOLD' } else { '' }
    $what = if ($c.role -eq 'consult') { ', an AI agent you are questioning' } elseif ($c.role -eq 'agent') { ', an AI agent' } else { '' }
    "This thread talks to $($c.name)$what (guest id $($c.id), Tox $($c.online), status $($c.status)$hold)."
  }
  if ($shared) { 'Shared thread: use --to NAME (or --to all) when sending.' }
  foreach ($m in $r.recent) {
    $from = if ($m.direction -eq 'in') { $m.guest } elseif ($shared) { "you -> $($m.guest)" } else { 'you' }
    $line = $m.body; if ($line.Length -gt 300) { $line = $line.Substring(0, 300) + '...' }
    if ($m.direction -eq 'out') { "  [$from] $line   ($($m.state))" } else { "  [$from] $line" }
  }
  exit 0
}

if ($file) {
  if (-not (Test-Path -LiteralPath $file)) { [Console]::Error.WriteLine("tox-send: no such file: $file"); exit 2 }
  $body = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $file), [Text.Encoding]::UTF8)
}
elseif ($MyInvocation.ExpectingInput) { $body = ($input | Out-String).TrimEnd("`r", "`n") }
elseif (($text.Count -eq 1 -and $text[0] -eq '-') -or ($text.Count -eq 0 -and [Console]::IsInputRedirected)) {
  $in = New-Object IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)
  $body = $in.ReadToEnd()
}
else { $body = ($text -join ' ') }
$body = $body -replace "`r`n", "`n"
if (-not $body.Trim()) { [Console]::Error.WriteLine('tox-send: nothing to send'); exit 2 }

$r = Invoke-Toxline 'send' @{ thread_id = $thread; body = $body; wait = 4; to = $to }
$states = @{
  delivered      = 'DELIVERED - their client confirmed receipt'
  sent           = "SENT - handed to Tox; waiting for their client's receipt"
  offline_queued = 'QUEUED - they are offline; it goes out automatically when they connect'
  held           = 'HELD - outgoing messages are on hold for review; it goes out when released'
  failed         = 'FAILED'
}
$failed = $false
foreach ($res in @($r.results)) {
  $m = $res.message
  $s = if ($states.ContainsKey($m.state)) { $states[$m.state] } else { $m.state.ToUpper() }
  if ($m.state -eq 'held' -and $m.detail -like '*budget*') { $s = 'HELD - the message budget for this agent conversation is used up. Stop here and tell your owner; it goes out only if they release it' }
  "To $($res.to.name): $s (message id $($m.id), $($m.body.Length) chars)"
  if ($m.state -eq 'failed') { $failed = $true }
}
if ($failed) { exit 1 }
