# One-time setup: Python virtual environment + backend packages, frontend packages, .env file.
# Run from anywhere:  scripts\setup.cmd   (or: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if ($root -like "*OneDrive*") {
    Write-Host "WARNING: this project is inside OneDrive ($root)." -ForegroundColor Yellow
    Write-Host "         OneDrive syncing can lock the SQLite database and slow down node_modules." -ForegroundColor Yellow
    Write-Host "         Recommended: move the folder to e.g. C:\dev\forex-ai and run setup again." -ForegroundColor Yellow
}

Step "Checking Python (3.11+ required)"
$python = $null   # command + fixed arguments, e.g. @("py", "-3")
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    $exe = $candidate[0]
    $fixed = @($candidate | Select-Object -Skip 1)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $ver = & $exe @fixed -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -and [version]$ver -ge [version]"3.11") { $python = $candidate; break }
    }
}
if (-not $python) { Fail "Python 3.11+ not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH')." }
Write-Host "Using $($python -join ' ') (Python $ver)"

Step "Checking Node.js (20+ required)"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js not found. Install the LTS version from https://nodejs.org/" }
$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 20) { Fail "Node.js 20+ required (found $(node --version))." }
Write-Host "Using Node $(node --version)"

Step "Creating backend virtual environment (backend\.venv)"
if (-not (Test-Path $venvPython)) {
    $fixed = @($python | Select-Object -Skip 1)
    & $python[0] @fixed -m venv (Join-Path $backend ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
}
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $backend "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }
Write-Host "Backend packages installed."

Step "Installing frontend packages (npm)"
Push-Location $frontend
try {
    npm install --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { Fail "npm install failed." }
} finally { Pop-Location }

Step "Configuration file (.env)"
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created .env from .env.example. Put your TWELVEDATA_API_KEY in it:" -ForegroundColor Yellow
    Write-Host "  notepad `"$envFile`""
} else {
    Write-Host ".env already exists (left unchanged)."
}

Write-Host "`nSetup complete. Next:" -ForegroundColor Green
Write-Host "  1. Put your Twelve Data API key in .env (TWELVEDATA_API_KEY=...)"
Write-Host "  2. scripts\download.cmd        download + validate every instrument in INSTRUMENTS"
Write-Host "  3. scripts\start.cmd           start the API and the dashboard (http://localhost:3000)"
