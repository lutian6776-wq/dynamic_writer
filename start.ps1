$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

Write-Host "Starting Moji Backend (FastAPI on port 8000)..." -ForegroundColor Cyan
$BackendProc = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
    -WorkingDirectory $BackendDir `
    -PassThru

Write-Host "Starting Moji Frontend (Vite on port 5173)..." -ForegroundColor Cyan
$FrontendProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev -- --host" `
    -WorkingDirectory $FrontendDir `
    -PassThru

Start-Sleep -Seconds 2
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "App is running:" -ForegroundColor Green
Write-Host "  Desktop UI : http://localhost:5173"
Write-Host "  Backend API: http://localhost:8000/docs"
Write-Host "  Tablet Page: http://<LAN_IP>:8000/mobile"
Write-Host ""
Write-Host "Press ENTER to stop both servers..." -ForegroundColor Yellow
[void][System.Console]::ReadLine()

if (-not $BackendProc.HasExited) { Stop-Process -Id $BackendProc.Id -Force }
if (-not $FrontendProc.HasExited) { Stop-Process -Id $FrontendProc.Id -Force }
