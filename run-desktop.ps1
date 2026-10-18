[CmdletBinding()]
param(
    [switch]$NoBanner
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Set up Python using README.md first.' }
    & .venv/Scripts/python.exe -c 'import webview'
    if ($LASTEXITCODE -ne 0) { throw 'Install requirements-desktop.txt first.' }
    if (-not (Test-Path 'frontend/dist/index.html')) {
        & npm.cmd --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
        & npm.cmd --prefix frontend run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    }
    if (-not $NoBanner) {
        Write-Host ""
        Write-Host "=========================================" -ForegroundColor Green
        Write-Host "  Melon" -ForegroundColor Green
        Write-Host "  Frontend URL: http://127.0.0.1:8765" -ForegroundColor Cyan
        Write-Host "  API Docs:     http://127.0.0.1:8765/docs" -ForegroundColor DarkGray
        Write-Host "=========================================" -ForegroundColor Green
        Write-Host ""
    }
    & .venv/Scripts/python.exe desktop_app.py
    if ($LASTEXITCODE -ne 0) { throw 'Melon Desktop exited with an error. See .data/desktop.log.' }
} finally { Pop-Location }
