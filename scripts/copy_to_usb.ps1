# Copy project to a USB drive for Orange Pi (no WiFi needed).
# Usage:
#   1. Plug USB into THIS PC
#   2. See drive letter (e.g. E:)
#   3. powershell -ExecutionPolicy Bypass -File scripts\copy_to_usb.ps1 E:

param(
  [Parameter(Mandatory = $true)]
  [string]$DriveLetter
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$letter = $DriveLetter.TrimEnd(':').TrimEnd('\').ToUpper()
$destRoot = "${letter}:\roboparty_rp_server"

if (-not (Test-Path "${letter}:\")) {
  Write-Error "Drive ${letter}: not found. Plug USB and check letter in Explorer."
}

Write-Host "Source: $Root"
Write-Host "Dest:   $destRoot"

if (Test-Path $destRoot) {
  Remove-Item -Recurse -Force $destRoot
}
New-Item -ItemType Directory -Path $destRoot | Out-Null

# Exclude bulky / useless dirs
$excludeDirNames = @(
  '.git', '.pytest_cache', '__pycache__', '.venv', 'venv',
  'node_modules', 'debian/roboparty-rp-server', '.idea', '.vscode'
)

function ShouldSkip([string]$fullPath) {
  $rel = $fullPath.Substring($Root.Length).TrimStart('\')
  foreach ($name in $excludeDirNames) {
    if ($rel -like "$name" -or $rel -like "$name\*" -or $rel -like "*\$name" -or $rel -like "*\$name\*") {
      return $true
    }
  }
  if ($rel -like '*.pyc') { return $true }
  return $false
}

Get-ChildItem -Path $Root -Recurse -Force | ForEach-Object {
  if (ShouldSkip $_.FullName) { return }
  $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
  $target = Join-Path $destRoot $rel
  if ($_.PSIsContainer) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
  } else {
    $parent = Split-Path $target -Parent
    if (-not (Test-Path $parent)) {
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -Force $_.FullName $target
  }
}

Write-Host "DONE. Safely eject USB, plug into Orange Pi USB port."
Write-Host "On board serial, run commands in docs/无网上板_U盘拷贝.md"
Get-ChildItem $destRoot | Select-Object Name
