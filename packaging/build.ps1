# Builds dist\YouTube Music Cleanup.exe (one file, no console window).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    "Creating .venv (needs Python 3.11 or later on PATH)..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Couldn't create .venv. Install Python 3.11+ from python.org first." }
}

& $py -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    & $py -m pip install -e ".[app,build]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

$locales = & $py -c "import ytmusicapi, pathlib; print(pathlib.Path(ytmusicapi.__file__).parent / 'locales')"
$env:PATH = (Join-Path $root ".venv\Scripts") + ";" + $env:PATH  # nicegui-pack calls bare "pyinstaller"
$pack = Join-Path $root ".venv\Scripts\nicegui-pack.exe"
# nicegui-pack adds the nicegui package data itself; locales is ytmusicapi's translations.
& $pack --name "YouTube Music Cleanup" --windowed --onefile --clean --noconfirm `
    --add-data "$locales;ytmusicapi\locales" `
    packaging\app_entry.py
if ($LASTEXITCODE -ne 0) { throw "build failed" }

$exe = Join-Path $root "dist\YouTube Music Cleanup.exe"
if (-not (Test-Path $exe)) { throw "Build finished but $exe is missing" }
"Built: $exe ({0:N1} MB)" -f ((Get-Item $exe).Length / 1MB)
