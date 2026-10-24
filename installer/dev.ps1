# Development run: hot-reloading UI + debug Tauri shell; the shell starts the backend from .venv automatically.
#   powershell -ExecutionPolicy Bypass -File installer\dev.ps1
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "toolchain.ps1")
Set-Location (Join-Path $root "app")
if (-not (Test-Path node_modules)) { npm install }
npx tauri dev
