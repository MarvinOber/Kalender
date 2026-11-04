<#
.SYNOPSIS
  Familienkalender in Google Cloud einrichten bzw. aktualisieren (idempotent – nach jeder Änderung erneut laufen lassen).

.DESCRIPTION
  Aktiviert die Dienste, legt Firestore, Dienstkonto, Artifact Registry und fehlende Secrets an, baut das Image
  mit Cloud Build und veröffentlicht es als Cloud-Run-Dienst. Danach richtet es den Cloud-Scheduler-Job ein, der
  alle 5 Minuten die Erinnerungen per Push anstößt. Umgebungsvariablen und Secrets setzt NUR dieses Skript – und
  zwar immer vollständig (--set-env-vars ersetzt die ganze Liste).

  Vorher von Hand (siehe README): OAuth-Client anlegen, Secrets kalender-openrouter-key und
  kalender-oauth-client-secret füllen.

  Bei einem bestehenden Dienst reicht ".\scripts\deploy.ps1" ohne Parameter: Projekt kommt aus
  "gcloud config", OAuth-Client-ID, Freigabeliste und öffentliche Adresse aus dem laufenden Dienst.

.EXAMPLE
  .\scripts\deploy.ps1 -ProjectId mein-projekt -OAuthClientId 123-abc.apps.googleusercontent.com `
    -AllowedEmails "mama@gmail.com,papa@gmail.com,tablet@gmail.com" -BillingAccount 0123-4567-89AB -BudgetEur 5
#>
param(
  [string] $ProjectId = "",
  [string] $OAuthClientId = "",
  [string] $AllowedEmails = "",
  [string] $Region = "europe-west1",
  [string] $FirestoreLocation = "eur3",
  [string] $Service = "kalender",
  [string] $PublicUrl = "",
  [string] $BillingAccount = "",
  [int] $BudgetEur = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# gcloud schreibt Hinweise nach stderr; Windows PowerShell macht daraus bei "Stop" abbrechende Fehler.
# Deshalb in den Helfern "Continue" – es zählt nur der Exit-Code.
function Invoke-Gcloud {
  $ErrorActionPreference = "Continue"
  & gcloud @args 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') ist fehlgeschlagen ($LASTEXITCODE)." }
}

function Test-Gcloud {
  $ErrorActionPreference = "Continue"
  & gcloud @args 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

function Get-Gcloud {
  $ErrorActionPreference = "Continue"
  $out = & gcloud @args 2>$null
  if ($LASTEXITCODE -ne 0) { return "" }
  return ($out -join "`n").Trim()
}

if (-not $ProjectId) { $ProjectId = Get-Gcloud config get-value project }
if (-not $ProjectId) { throw "Kein Projekt: -ProjectId angeben oder 'gcloud config set project …'." }

# Fehlende Angaben aus dem laufenden Dienst übernehmen (Folge-Deployments ohne Parameter)
if (-not $OAuthClientId -or -not $AllowedEmails -or -not $PublicUrl) {
  $json = Get-Gcloud run services describe $Service --region=$Region --project=$ProjectId --format=json
  if ($json) {
    $current = @{}
    foreach ($e in (ConvertFrom-Json $json).spec.template.spec.containers[0].env) { $current[$e.name] = $e.value }
    if (-not $OAuthClientId) { $OAuthClientId = $current["GOOGLE_OAUTH_CLIENT_ID"] }
    if (-not $AllowedEmails) { $AllowedEmails = $current["KALENDER_ALLOWED_EMAILS"] }
    # Adresse behalten, die beim OAuth-Client als Weiterleitung eingetragen ist (Cloud Run kennt zwei Formen)
    if (-not $PublicUrl) { $PublicUrl = $current["KALENDER_PUBLIC_URL"] }
  }
}
if (-not $OAuthClientId -or -not $AllowedEmails) {
  throw "Erstes Deployment: -OAuthClientId und -AllowedEmails angeben (siehe README)."
}

Write-Host "== Projekt $ProjectId, Region $Region" -ForegroundColor Cyan
Invoke-Gcloud config set project $ProjectId --quiet
$Sa = "$Service-run@$ProjectId.iam.gserviceaccount.com"
$Repo = "$Region-docker.pkg.dev/$ProjectId/$Service"

Write-Host "== Dienste aktivieren" -ForegroundColor Cyan
Invoke-Gcloud services enable run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com `
  artifactregistry.googleapis.com cloudbuild.googleapis.com calendar-json.googleapis.com iam.googleapis.com `
  billingbudgets.googleapis.com cloudscheduler.googleapis.com --quiet

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
function New-Secret([string] $Name, [string] $Value) {
  # Ohne Zeilenumbruch und ohne BOM über eine Datei – der Wert erscheint nie in Kommandozeile oder Ausgabe
  $tmp = New-TemporaryFile
  try {
    [IO.File]::WriteAllText($tmp, $Value)
    Invoke-Gcloud secrets create $Name --data-file=$tmp --replication-policy=automatic --quiet | Out-Null
  } finally { Remove-Item $tmp }
}

function New-RandomBytes([int] $Count) {
  $bytes = New-Object byte[] $Count
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return , $bytes
}

$SessionSecret = "$Service-session-secret"
if (-not (Test-Gcloud secrets describe $SessionSecret)) {
  # Zufälliger Schlüssel für die Sitzungs-Cookies – wird nie angezeigt
  New-Secret $SessionSecret ([Convert]::ToBase64String((New-RandomBytes 48)))
}
$VapidSecret = "$Service-vapid-key"
if (-not (Test-Gcloud secrets describe $VapidSecret)) {
  # P-256-Schlüssel für Web Push (VAPID): die 32 Byte des privaten Teils als base64url, den öffentlichen leitet der
  # Server ab. Ein neuer Schlüssel macht alle Abos ungültig; die App abonniert beim nächsten Start selbst neu.
  $ec = [System.Security.Cryptography.ECDsa]::Create([System.Security.Cryptography.ECCurve+NamedCurves]::nistP256)
  $d = $ec.ExportParameters($true).D
  New-Secret $VapidSecret ([Convert]::ToBase64String($d).TrimEnd("=").Replace("+", "-").Replace("/", "_"))
}
$CronSecret = "$Service-cron-secret"
if (-not (Test-Gcloud secrets describe $CronSecret)) {
  # Kopfzeile, mit der Cloud Scheduler den Erinnerungslauf anstößt (hex: passt in die --headers-Liste)
  New-Secret $CronSecret (((New-RandomBytes 32) | ForEach-Object { $_.ToString("x2") }) -join "")
}
foreach ($name in @("$Service-openrouter-key", "$Service-oauth-client-secret", $SessionSecret, $VapidSecret,
    $CronSecret)) {
  Invoke-Gcloud secrets add-iam-policy-binding $name --member="serviceAccount:$Sa" `
    --role=roles/secretmanager.secretAccessor --quiet | Out-Null
}

Write-Host "== Artifact Registry" -ForegroundColor Cyan
if (-not (Test-Gcloud artifacts repositories describe $Service --location=$Region)) {
  Invoke-Gcloud artifacts repositories create $Service --repository-format=docker --location=$Region --quiet
}
# Aufräumen: die letzten 3 Images behalten, ältere als 7 Tage löschen
$policy = New-TemporaryFile
# Ohne BOM schreiben – "Set-Content -Encoding utf8" setzt in Windows PowerShell eins, das gcloud nicht liest
[IO.File]::WriteAllText($policy, @'
[
  {"name": "keep-recent", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 3}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"olderThan": "604800s"}}
]
'@)
Invoke-Gcloud artifacts repositories set-cleanup-policies $Service --location=$Region --policy=$policy --no-dry-run --quiet | Out-Null
Remove-Item $policy

Write-Host "== Image bauen (Cloud Build)" -ForegroundColor Cyan
$Tag = (Get-Date -Format "yyyyMMdd-HHmmss")
$Image = "$Repo/app:$Tag"
Push-Location $Root
try { Invoke-Gcloud builds submit . --tag $Image --region=$Region --quiet } finally { Pop-Location }

Write-Host "== Cloud Run" -ForegroundColor Cyan
if (-not $PublicUrl) {
  $PublicUrl = Get-Gcloud run services describe $Service --region=$Region --format="value(status.url)"
}
# „^;^“: Semikolon als Trenner, weil die Freigabeliste Kommas enthält
$envVars = "^;^KALENDER_BACKEND=cloud;GOOGLE_CLOUD_PROJECT=$ProjectId;GOOGLE_OAUTH_CLIENT_ID=$OAuthClientId;" +
  "KALENDER_ALLOWED_EMAILS=$AllowedEmails;KALENDER_PUBLIC_URL=$PublicUrl"
$secrets = "OPENROUTER_API_KEY=$Service-openrouter-key:latest,GOOGLE_OAUTH_CLIENT_SECRET=$Service-oauth-client-secret:latest," +
  "KALENDER_SESSION_SECRET=${SessionSecret}:latest,KALENDER_VAPID_PRIVATE_KEY=${VapidSecret}:latest," +
  "KALENDER_CRON_SECRET=${CronSecret}:latest"
Invoke-Gcloud run deploy $Service --image $Image --region $Region --service-account $Sa --allow-unauthenticated `
  --memory 512Mi --cpu 1 --concurrency 20 --min-instances 0 --max-instances 2 --timeout 120 --cpu-boost `
  --set-env-vars $envVars --set-secrets $secrets --quiet

$Url = Get-Gcloud run services describe $Service --region=$Region --format="value(status.url)"
if (-not $PublicUrl) {
  # Erstes Deployment: Adresse war vorher unbekannt – jetzt fest eintragen
  Invoke-Gcloud run services update $Service --region $Region --update-env-vars "KALENDER_PUBLIC_URL=$Url" --quiet
  $PublicUrl = $Url
}

Write-Host "== Cloud Scheduler (Erinnerungen alle 5 Minuten)" -ForegroundColor Cyan
# Cloud Run läuft nur bei Anfragen – der Job weckt den Dienst, der dann fällige Erinnerungen verschickt.
# Das Geheimnis geht über eine Flags-Datei an gcloud, nicht über die Kommandozeile (auch nicht in Fehlermeldungen).
$Job = "$Service-erinnerungen"
$cronValue = Get-Gcloud secrets versions access latest --secret=$CronSecret
$exists = Test-Gcloud scheduler jobs describe $Job --location=$Region
$headerFlag = if ($exists) { "--update-headers" } else { "--headers" }
$flags = New-TemporaryFile
try {
  [IO.File]::WriteAllText($flags, "${headerFlag}: X-Kalender=1,X-Kalender-Cron=$cronValue`n")
  $jobArgs = @("--location=$Region", "--schedule=*/5 * * * *", "--time-zone=Europe/Berlin",
    "--uri=$PublicUrl/api/cron/reminders", "--http-method=POST", "--attempt-deadline=90s",
    "--flags-file=$flags", "--quiet")
  $verb = if ($exists) { "update" } else { "create" }
  Invoke-Gcloud scheduler jobs $verb http $Job @jobArgs | Out-Null
} finally { Remove-Item $flags }

if ($BudgetEur -gt 0 -and $BillingAccount) {
  Write-Host "== Budget-Warnung ($BudgetEur EUR/Monat)" -ForegroundColor Cyan
  $existing = Get-Gcloud billing budgets list --billing-account=$BillingAccount --format="value(displayName)"
  if ($existing -notmatch "Familienkalender $ProjectId") {
    Invoke-Gcloud billing budgets create --billing-account=$BillingAccount --display-name="Familienkalender $ProjectId" `
      --budget-amount="${BudgetEur}EUR" --filter-projects="projects/$ProjectId" `
      --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 --quiet
  }
}

Write-Host ""
Write-Host "Fertig: $PublicUrl (Erinnerungen: Job $Job alle 5 Minuten)" -ForegroundColor Green
Write-Host "Beim OAuth-Client als autorisierte Weiterleitungs-URI eintragen (einmalig, von Hand):"
Write-Host "  $PublicUrl/auth/callback"
