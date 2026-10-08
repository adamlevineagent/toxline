# Downloads the prebuilt Tox library (toxcore.dll + libsodium.dll + pthreadVC3.dll) from this
# repo's GitHub release into tox\bin, checking every file against a pinned SHA-256.
# To build it yourself instead, see tox\README.md.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$bin = Join-Path $PSScriptRoot 'bin'
$url = 'https://github.com/adamlevineagent/toxline/releases/download/toxcore-v0.2.23/toxcore-win64-v0.2.23.zip'
$zipSha = '27457f3b590cc07ff6dddd7d6ed15c1d8c0363a13bb49d4b34ffb0cc3b7ce305'
$want = @{
  'toxcore.dll'    = 'bd53dc1b01d2c87a2c58395acea8deca3d50f93d8ea2de2639aa37c71a02f872'
  'libsodium.dll'  = '740eb7f05048ce346857c39d7c01b6abd574b44f32191cb44fe293f453aa3d61'
  'pthreadVC3.dll' = '928bc67c95aaffca530070580fd8f3433fa7894b87d7f0872efdb1ed18d0e7fa'
}

function Test-Bin {
  foreach ($k in $want.Keys) {
    $p = Join-Path $bin $k
    if (-not (Test-Path $p)) { return $false }
    if ((Get-FileHash $p -Algorithm SHA256).Hash.ToLower() -ne $want[$k]) { return $false }
  }
  return $true
}

if (Test-Bin) { Write-Host 'Tox library: already in tox\bin (checksums OK).'; exit 0 }

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("toxline-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $tmp | Out-Null
try {
  $zip = Join-Path $tmp 'toxcore.zip'
  Write-Host 'Downloading the Tox library from the Toxline GitHub release...'
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
  if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $zipSha) {
    throw 'the download does not match its expected checksum; nothing was installed'
  }
  Expand-Archive $zip -DestinationPath (Join-Path $tmp 'x')
  New-Item -ItemType Directory -Force $bin | Out-Null
  foreach ($k in $want.Keys) { Copy-Item (Join-Path $tmp "x\$k") (Join-Path $bin $k) -Force }
  Copy-Item (Join-Path $tmp 'x\NOTICE.txt') (Join-Path $bin 'NOTICE.txt') -Force
  Copy-Item (Join-Path $tmp 'x\licenses') (Join-Path $bin 'licenses') -Recurse -Force
  if (-not (Test-Bin)) { throw 'installed files do not match their expected checksums' }
  Write-Host 'Tox library: installed in tox\bin (checksums OK).'
} finally {
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
