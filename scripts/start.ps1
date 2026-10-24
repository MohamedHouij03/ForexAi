# Start the API (http://localhost:8000) and the dashboard (http://localhost:3000), each in its own window.
# Close a window (or press Ctrl+C in it) to stop that server.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Backend is not set up yet. Run scripts\setup.cmd first." -ForegroundColor Red
    exit 1
}

Start-Process powershell -WorkingDirectory $backend -ArgumentList @(
    "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'Forex AI - API'; & '$venvPython' -m uvicorn app.main:app --reload --port 8000"
)
Start-Process powershell -WorkingDirectory $frontend -ArgumentList @(
    "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'Forex AI - Dashboard'; npm run dev"
)

Write-Host "Starting... API: http://localhost:8000/docs   Dashboard: http://localhost:3000" -ForegroundColor Green
Start-Sleep -Seconds 6
Start-Process "http://localhost:3000"
