<#
.SYNOPSIS
  Familienkalender in Google Cloud einrichten bzw. aktualisieren (idempotent – nach jeder Änderung erneut laufen lassen).

.DESCRIPTION
  Aktiviert die Dienste, legt Firestore, Dienstkonto, Artifact Registry und fehlende Secrets an, baut das Image
  mit Cloud Build und veröffentlicht es als Cloud-Run-Dienst. Umgebungsvariablen und Secrets setzt NUR dieses
  Skript – und zwar immer vollständig (--set-env-vars ersetzt die ganze Liste).

  Vorher von Hand (siehe README): OAuth-Client anlegen, Secrets kalender-openrouter-key und
  kalender-oauth-client-secret füllen.

.EXAMPLE
  .\scripts\deploy.ps1 -ProjectId mein-projekt -OAuthClientId 123-abc.apps.googleusercontent.com `
    -AllowedEmails "mama@gmail.com,papa@gmail.com,tablet@gmail.com"
#>
param(
  [Parameter(Mandatory = $true)] [string] $ProjectId,
  [Parameter(Mandatory = $true)] [string] $OAuthClientId,
  [Parameter(Mandatory = $true)] [string] $AllowedEmails,
  [string] $Region = "europe-west1",
  [string] $FirestoreLocation = "eur3",
  [string] $Service = "kalender",
  [string] $PublicUrl = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Gcloud {
  # gcloud schreibt Hinweise nach stderr; nur der Exit-Code zählt
  & gcloud @args
  if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') ist fehlgeschlagen ($LASTEXITCODE)." }
}

function Test-Gcloud {
  & gcloud @args 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

Write-Host "== Projekt $ProjectId, Region $Region" -ForegroundColor Cyan
Invoke-Gcloud config set project $ProjectId --quiet
$Sa = "$Service-run@$ProjectId.iam.gserviceaccount.com"
$Repo = "$Region-docker.pkg.dev/$ProjectId/$Service"

Write-Host "== Dienste aktivieren" -ForegroundColor Cyan
Invoke-Gcloud services enable run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com `
  artifactregistry.googleapis.com cloudbuild.googleapis.com calendar-json.googleapis.com iam.googleapis.com --quiet

Write-Host "== Firestore" -ForegroundColor Cyan
if (-not (Test-Gcloud firestore databases describe --database="(default)")) {
  Invoke-Gcloud firestore databases create --database="(default)" --location=$FirestoreLocation --type=firestore-native --quiet
}

Write-Host "== Dienstkonto $Sa" -ForegroundColor Cyan
if (-not (Test-Gcloud iam service-accounts describe $Sa)) {
  Invoke-Gcloud iam service-accounts create "$Service-run" --display-name="Familienkalender (Cloud Run)"
}
Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$Sa" --role=roles/datastore.user `
  --condition=None --quiet | Out-Null

Write-Host "== Secrets" -ForegroundColor Cyan
foreach ($name in @("$Service-openrouter-key", "$Service-oauth-client-secret")) {
  if (-not (Test-Gcloud secrets versions access latest --secret=$name)) {
    throw "Secret $name fehlt oder ist leer. Anlegen siehe README, Abschnitt 'Secrets'."
  }
}
$SessionSecret = "$Service-session-secret"
if (-not (Test-Gcloud secrets describe $SessionSecret)) {
  # Zufälliger Schlüssel für die Sitzungs-Cookies – wird nie angezeigt
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $tmp = New-TemporaryFile
  [IO.File]::WriteAllText($tmp, [Convert]::ToBase64String($bytes))
  Invoke-Gcloud secrets create $SessionSecret --data-file=$tmp --replication-policy=automatic --quiet
  Remove-Item $tmp
}
foreach ($name in @("$Service-openrouter-key", "$Service-oauth-client-secret", $SessionSecret)) {
  Invoke-Gcloud secrets add-iam-policy-binding $name --member="serviceAccount:$Sa" `
    --role=roles/secretmanager.secretAccessor --quiet | Out-Null
}

Write-Host "== Artifact Registry" -ForegroundColor Cyan
if (-not (Test-Gcloud artifacts repositories describe $Service --location=$Region)) {
  Invoke-Gcloud artifacts repositories create $Service --repository-format=docker --location=$Region --quiet
}
# Aufräumen: die letzten 3 Images behalten, ältere als 7 Tage löschen
$policy = New-TemporaryFile
@'
[
  {"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"olderThan": "604800s"}}
]
'@ | Set-Content -Path $policy -Encoding utf8
Invoke-Gcloud artifacts repositories set-cleanup-policies $Service --location=$Region --policy=$policy --no-dry-run --quiet | Out-Null
Remove-Item $policy

Write-Host "== Image bauen (Cloud Build)" -ForegroundColor Cyan
$Tag = (Get-Date -Format "yyyyMMdd-HHmmss")
$Image = "$Repo/app:$Tag"
Push-Location $Root
try { Invoke-Gcloud builds submit . --tag $Image --region=$Region --quiet } finally { Pop-Location }

Write-Host "== Cloud Run" -ForegroundColor Cyan
if (-not $PublicUrl) {
  $PublicUrl = (& gcloud run services describe $Service --region=$Region --format="value(status.url)" 2>$null)
}
# „^;^“: Semikolon als Trenner, weil die Freigabeliste Kommas enthält
$envVars = "^;^KALENDER_BACKEND=cloud;GOOGLE_CLOUD_PROJECT=$ProjectId;GOOGLE_OAUTH_CLIENT_ID=$OAuthClientId;" +
  "KALENDER_ALLOWED_EMAILS=$AllowedEmails;KALENDER_PUBLIC_URL=$PublicUrl"
$secrets = "OPENROUTER_API_KEY=$Service-openrouter-key:latest,GOOGLE_OAUTH_CLIENT_SECRET=$Service-oauth-client-secret:latest," +
  "KALENDER_SESSION_SECRET=${SessionSecret}:latest"
Invoke-Gcloud run deploy $Service --image $Image --region $Region --service-account $Sa --allow-unauthenticated `
  --memory 512Mi --cpu 1 --concurrency 20 --min-instances 0 --max-instances 2 --timeout 120 --cpu-boost `
  --set-env-vars $envVars --set-secrets $secrets --quiet

$Url = (& gcloud run services describe $Service --region=$Region --format="value(status.url)")
if (-not $PublicUrl) {
  # Erstes Deployment: Adresse war vorher unbekannt – jetzt fest eintragen
  Invoke-Gcloud run services update $Service --region $Region --update-env-vars "KALENDER_PUBLIC_URL=$Url" --quiet
  $PublicUrl = $Url
}

Write-Host ""
Write-Host "Fertig: $PublicUrl" -ForegroundColor Green
Write-Host "Beim OAuth-Client als autorisierte Weiterleitungs-URI eintragen (einmalig, von Hand):"
Write-Host "  $PublicUrl/auth/callback"
