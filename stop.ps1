<#
.SYNOPSIS
  Stop the AuricTerminal backend (kills python holding the port).
#>
param(
  [int]$Port = ([int]($env:PORT, $env:AURIC_PORT, 8000 | Where-Object { $_ } | Select-Object -First 1))
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$killed = 0

$conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
foreach ($c in $conns) {
  try {
    $proc = Get-Process -Id $c.OwningProcess -ErrorAction Stop
    if ($proc.ProcessName -match '^(python|pythonw|uvicorn)$') {
      Stop-Process -Id $proc.Id -Force
      Write-Host "[auric] Stopped $($proc.ProcessName) (PID $($proc.Id)) on port $Port"
      $killed++
    } else {
      Write-Host "[auric] Port $Port is held by $($proc.ProcessName) (PID $($proc.Id)) — not touching it"
    }
  } catch { }
}
if ($killed -eq 0) { Write-Host '[auric] Nothing running on port ' + $Port }
