<#
.SYNOPSIS
  Start AuricTerminal on Windows reliably (double-click start.bat or run this).
.DESCRIPTION
  - Uses .venv if present, otherwise system python
  - Installs backend deps if fastapi is missing
  - Builds web/dist if missing and npm is available
  - Kills any stale instance on the port (single-instance guard)
  - Rotates server.log past 10 MB, starts backend detached
  - Waits for /api/health, then opens the browser
  - With -KeepAlive, restarts the backend automatically if it crashes
.PARAMETER Port
  Backend port (default 8000). Also honored via PORT / AURIC_PORT env.
.PARAMETER KeepAlive
  Restart the backend with backoff if it exits unexpectedly.
.PARAMETER NoBrowser
  Don't open the browser automatically.
#>
param(
  [int]$Port = ([int]($env:PORT, $env:AURIC_PORT, 8000 | Where-Object { $_ } | Select-Object -First 1)),
  [switch]$KeepAlive,
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$Url = "http://127.0.0.1:$Port"

function Write-Step([string]$msg) { Write-Host "[auric] $msg" }

function Get-Python {
  $venv = Join-Path $Root '.venv\Scripts\python.exe'
  if (Test-Path -LiteralPath $venv) { return $venv }
  return 'python'
}

function Ensure-Backend-Deps([string]$py) {
  try {
    & $py -c "import fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -eq 0) { return }
  } catch { }
  Write-Step 'Backend deps missing - installing requirements.txt ...'
  & $py -m pip install -r (Join-Path $Root 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
}

function Ensure-Web-Dist {
  $dist = Join-Path $Root 'web\dist\index.html'
  if (Test-Path -LiteralPath $dist) { return }
  Write-Step 'web/dist missing - building web UI ...'
  $npm = Get-Command npm -ErrorAction SilentlyContinue
  if (-not $npm) { Write-Step 'WARNING: npm not found, falling back to index.html'; return }
  Push-Location (Join-Path $Root 'web')
  try {
    if (-not (Test-Path -LiteralPath 'node_modules')) { npm install }
    npm run build
  } finally { Pop-Location }
  if (-not (Test-Path -LiteralPath $dist)) { throw 'web build failed' }
}

function Stop-StaleInstance([int]$port) {
  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    try {
      $proc = Get-Process -Id $c.OwningProcess -ErrorAction Stop
      if ($proc.ProcessName -match '^(python|pythonw|uvicorn)$') {
        Write-Step "Stopping stale $($proc.ProcessName) (PID $($proc.Id)) on port $port ..."
        Stop-Process -Id $proc.Id -Force
        Start-Sleep -Seconds 2
      } else {
        Write-Step "WARNING: port $port is held by $($proc.ProcessName) (PID $($proc.Id)) - not touching it"
      }
    } catch { }
  }
}

function Rotate-Log([string]$path, [long]$maxBytes = 10MB) {
  if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Length -gt $maxBytes)) {
    $backup = "$path.1"
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
    Rename-Item -LiteralPath $path -NewName (Split-Path -Leaf $backup) -Force
  }
}

function Start-Backend([string]$py, [int]$port) {
  Rotate-Log (Join-Path $Root 'server.log')
  Rotate-Log (Join-Path $Root 'server_err.log')
  $env:PORT = "$port"
  return Start-Process -FilePath $py -ArgumentList 'run_server.py' `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $Root 'server.log') `
    -RedirectStandardError (Join-Path $Root 'server_err.log')
}

function Wait-Healthy([string]$url, [int]$timeoutSec = 90) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $h = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 5
      if ($h.ok) { return $h }
    } catch { }
    Start-Sleep -Seconds 2
  }
  throw "Backend did not become healthy at $url within ${timeoutSec}s (see server_err.log)"
}

# --- main ---------------------------------------------------------------
try {
  $py = Get-Python
  Write-Step "Using python: $py"
  Ensure-Backend-Deps $py
  Ensure-Web-Dist
  Stop-StaleInstance $Port

  $proc = Start-Backend $py $Port
  Write-Step "Backend starting (PID $($proc.Id)) ..."
  $health = Wait-Healthy $Url
  Write-Step "Healthy: source=$($health.source) liveTrading=$($health.liveTrading)"

  if (-not $NoBrowser) { Start-Process $Url }
  Write-Step "AuricTerminal is up at $Url"

  if ($KeepAlive) {
    Write-Step 'KeepAlive ON - watching backend, Ctrl+C to stop ...'
    $backoff = 2
    while ($true) {
      $proc.WaitForExit()
      $code = $proc.ExitCode
      Write-Step "Backend exited (code $code) - restarting in ${backoff}s ..."
      Start-Sleep -Seconds $backoff
      $backoff = [Math]::Min(30, $backoff * 2)
      Stop-StaleInstance $Port
      $proc = Start-Backend $py $Port
      try {
        Wait-Healthy $Url | Out-Null
        Write-Step 'Backend recovered.'
        $backoff = 2
      } catch {
        Write-Step "WARNING: restarted backend not healthy yet: $($_.Exception.Message)"
      }
    }
  } else {
    Write-Step 'Backend is detached (logs: server.log / server_err.log). Run stop.bat to shut it down.'
  }
} catch {
  Write-Host "[auric] FAILED: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host '[auric] Press any key to close ...'
  $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
  exit 1
}
