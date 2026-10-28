$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed. Install Python 3.13.' }
    }
    & '.\.venv\Scripts\python.exe' -c "import importlib.util, sys; sys.exit(not all(importlib.util.find_spec(m) for m in 'fastapi uvicorn sklearn httpx reportlab'.split()))"
    if ($LASTEXITCODE -ne 0) {
        & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection.' }
    }
    & '.\.venv\Scripts\python.exe' enthi.py @args
} finally {
    Pop-Location
}
