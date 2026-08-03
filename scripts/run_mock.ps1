# Start rp_server in mock mode on this Windows PC.
# Usage: right-click → Run with PowerShell, or:
#   powershell -ExecutionPolicy Bypass -File scripts\run_mock.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$env:PYTHONPATH = Join-Path $Root "src"
$env:RP_MOCK = "1"
$env:RP_SERVER_CONFIG = Join-Path $Root "config\server.yaml"

# Load local secrets from .env if present (gitignored)
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $i = $line.IndexOf("=")
    if ($i -lt 1) { return }
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim()
    Set-Item -Path "Env:$k" -Value $v
  }
  Write-Host "Loaded secrets from .env"
}

Write-Host "Starting rp_server mock at http://127.0.0.1:8765/"
Write-Host "Demo UI:  http://127.0.0.1:8765/"
Write-Host "API docs: http://127.0.0.1:8765/docs"
Write-Host "Ctrl+C to stop."

python -m rp_server --config (Join-Path $Root "config\dev_robot.yaml") --mock --host 127.0.0.1 --port 8765 --log-level info
