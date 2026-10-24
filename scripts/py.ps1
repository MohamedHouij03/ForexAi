# Run a backend module with the project's virtual environment, from the backend folder.
# Usage: scripts\py.ps1 <module> [args...]    e.g. scripts\py.ps1 training.download_data -i XAU_USD
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Backend is not set up yet. Run scripts\setup.cmd first." -ForegroundColor Red
    exit 1
}
Push-Location $backend
try {
    & $venvPython -m @args
    exit $LASTEXITCODE
} finally { Pop-Location }
