<#
.SYNOPSIS
  Lokal starten: Backend auf http://localhost:8080 (ohne Anmeldung, Kalender-Attrappe, Demo-KI).

.DESCRIPTION
  Liest backend/.env (Vorlage: backend/.env.example). Mit -Frontend zusätzlich den Vite-Server auf
  http://localhost:5173 (Hot Reload, leitet /api und /auth an das Backend weiter). Ohne -Frontend liefert das
  Backend die zuletzt gebaute Oberfläche aus frontend/dist aus.
#>
param([switch] $Frontend)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
  python -m venv (Join-Path $Backend ".venv")
  & $Python -m pip install -r (Join-Path $Backend "requirements-dev.txt")
}
if (-not (Test-Path (Join-Path $Backend ".env"))) {
  Copy-Item (Join-Path $Backend ".env.example") (Join-Path $Backend ".env")
}
$FrontendDir = Join-Path $Root "frontend"
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) { npm --prefix $FrontendDir install }
if ($Frontend) {
  Start-Process -FilePath "npm" -ArgumentList "--prefix", $FrontendDir, "run", "dev" -NoNewWindow
} elseif (-not (Test-Path (Join-Path $FrontendDir "dist"))) {
  npm --prefix $FrontendDir run build
}
& $Python -m uvicorn app.main:app --app-dir $Backend --port 8080 --reload --reload-dir (Join-Path $Backend "app")
