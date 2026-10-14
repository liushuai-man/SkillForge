$ErrorActionPreference = 'Continue'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\skillforge-vm.exe'
$frontend = Join-Path $project 'frontend'
$logDir = Join-Path $project 'runtime-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

function Test-Port([int]$Port) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

if ((Test-Path $python) -and -not (Test-Port 8756)) {
  Start-Process -FilePath $python -ArgumentList 'start','--host','127.0.0.1','--port','8756' -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'backend.out.log') -RedirectStandardError (Join-Path $logDir 'backend.err.log')
}

if ((Test-Path (Join-Path $frontend 'node_modules')) -and -not (Test-Port 5174)) {
  Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1' -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') -RedirectStandardError (Join-Path $logDir 'frontend.err.log')
}
