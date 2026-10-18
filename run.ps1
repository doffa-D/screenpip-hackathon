$port = 8765

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Melon" -ForegroundColor Green
Write-Host "  Frontend URL: http://127.0.0.1:$port" -ForegroundColor Cyan
Write-Host "  API Docs:     http://127.0.0.1:$port/docs" -ForegroundColor DarkGray
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""

& "$PSScriptRoot/run-desktop.ps1" -NoBanner

