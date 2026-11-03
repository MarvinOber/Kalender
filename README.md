# Familienkalender

Wochenkalender für ein Tablet oder einen Bildschirm an der Wand. Termine werden eingesprochen, von einer KI in
strukturierte Einträge verwandelt, im Dialog bestätigt und dann in einen Google-Kalender geschrieben.

- **Wochenansicht** Mo–So aus Google Calendar (eigene Darstellung über die Calendar API), Pfeile, „Heute“,
  Linie für die aktuelle Uhrzeit, ganztägige Termine oben, Farben je Person. Querformat: Zeitraster ohne
  Scrollen; Hochformat: Tagesliste. Aktualisierung alle 5 Minuten und beim Aufwachen des Geräts; nach
  3 Minuten ohne Bedienung springt die Anzeige zurück zur aktuellen Woche. Wischen blättert.
- **Spracheingabe**: großer Mikrofon-Knopf (gedrückt halten *oder* antippen/erneut tippen). Aufnahme im
  Browser → WAV 16 kHz mono → Backend → Transkription (OpenRouter) → Termin-Erkennung mit JSON-Schema
  (OpenRouter) → Bestätigungsdialog. Erst „Anlegen“ schreibt in Google. Daneben ein ⌨-Knopf zum Tippen.
- **Tags**: Personen (mit Farbe und Zusätzen wie „Mama“, „Kinder“) und Ereignisse (Schule, Arzt, Sport …).
  Filterleiste mit Mehrfachauswahl, im Gerät gespeichert.
- **Einstellungen** für die ganze Familie in Firestore: Kalender, beide Modelle (mit Vorschlägen aus der
  OpenRouter-Modellliste), Personen, Ereignis-Tags, Sprache, Zeitzone, Standarddauer. Wirkt beim nächsten
  Aufruf – kein Deployment.

## Modellprüfung MiMo-V2.6-Pro (Stand 2026-11-03)

| Frage | Ergebnis (Quelle: `GET https://openrouter.ai/api/v1/models`) |
| --- | --- |
| Exakte Modell-ID | **`xiaomi/mimo-v2.6-pro`** (Name „Xiaomi: MiMo-V2.6-Pro“, Stand `-20260921`) |
| Audio-Eingabe | **ja** – `input_modalities: text, image, video, audio` |
| JSON-Schema | ja – `response_format` und `structured_outputs` |
| Preis | 0,435 $ / 1 Mio. Eingabe-Token, 0,87 $ / 1 Mio. Ausgabe-Token |

Audio geht über `POST /chat/completions` als Inhaltsteil `input_audio` (base64, `format: "wav"`). Die
Oberfläche wandelt jede Aufnahme vorher in WAV um, weil Chrome WebM/Opus und Safari MP4/AAC aufnimmt und nicht
jeder Anbieter jedes Format versteht. Es gibt also keinen Grund für eine Alternative; falls das Modell einmal
ausfällt, lassen sich in den Einstellungen andere Audio-Modelle wählen, z. B. `xiaomi/mimo-v2.6-flash`
(deutlich günstiger) oder `google/gemini-3.5-flash`. Standard für **beide** Aufgaben ist MiMo-V2.6-Pro.

## Aufbau

```
Browser (Tablet) ──HTTPS──▶ Cloud Run „kalender“ (ein Image)
                              ├─ /            gebaute React-Oberfläche
                              ├─ /auth/*      Google-OAuth (Code-Flow, Refresh-Token serverseitig)
                              └─ /api/*       FastAPI
                                   ├─ Firestore: config/settings, users/<email>
                                   ├─ Secret Manager: OpenRouter-Key, OAuth-Secret, Sitzungsschlüssel
                                   ├─ OpenRouter: Transkription + Termin-Erkennung
                                   └─ Google Calendar API v3 (REST)
```

| Ordner | Inhalt |
| --- | --- |
| `backend/app/main.py` | API, Auslieferung der Oberfläche, Fehlerbehandlung |
| `backend/app/auth.py` | OAuth-Anmeldung, Freigabeliste, Token-Erneuerung |
| `backend/app/extraction.py` | Prompt, JSON-Schema, Prüfung der Modellantwort |
| `backend/app/events.py` | Entwurf ↔ Google-Termin ↔ Anzeige, Tags, Wiederholung (RRULE) |
| `backend/app/calendar_api.py` | Google Calendar über REST, lokale Attrappe |
| `backend/app/openrouter.py` | OpenRouter-Aufrufe, Modellliste (24 Std im Speicher) |
| `backend/app/settings.py` | Einstellungen der Familie (Firestore-Dokument `config/settings`) |
| `frontend/src/` | React 18 + TypeScript + Vite |
| `scripts/deploy.ps1` | Einrichtung und Deployment (idempotent) |

**Tags im Google-Termin:** maschinenlesbar in `extendedProperties.private` (`fkPersons=lena,max`,
`fkTags=sport`) und lesbar am Ende der Beschreibung:

```
— Familienkalender —
Personen: Lena, Max
Tags: Sport
```

Termine, die jemand in der Google-App anlegt, werden auch erkannt: über diesen Block (wer ihn von Hand schreibt)
oder über einen Personennamen im Titel („Lena Klavier“).

**Audio** bleibt nur im Arbeitsspeicher der Anfrage und wird nirgends abgelegt. Der OpenRouter-Schlüssel liegt nur
im Secret Manager; alle KI-Aufrufe laufen über das Backend.

## Lokal ausführen

Voraussetzungen: Python 3.12+, Node 20+.

```powershell
.\scripts\dev.ps1
```

Öffnet nichts selbst – im Browser `http://localhost:8080` aufrufen. Standard laut `backend/.env.example`:
ohne Anmeldung (`KALENDER_AUTH=none`), Kalender als lokale Attrappe (`backend/data/store.json`), Demo-KI
(`KALENDER_FAKE_LLM=1`: jede Aufnahme ergibt „Am Freitag um 16 Uhr hat Lena Fussball und Samstag ist Omas
Geburtstag“). Mit Hot Reload der Oberfläche:

```powershell
.\scripts\dev.ps1 -Frontend
```

dann `http://localhost:5173`. Echte KI lokal: in `backend/.env` `KALENDER_FAKE_LLM=0` und
`OPENROUTER_API_KEY=sk-or-v1-…` setzen. Echte Google-Anmeldung lokal: `KALENDER_AUTH=google` plus die
Variablen aus `backend/.env.example` und `http://localhost:8080/auth/callback` als Weiterleitungs-URI beim
OAuth-Client.

Das Mikrofon funktioniert nur über HTTPS oder `localhost`.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
cd ..\frontend
npm test
```

- `test_extraction.py` – Beispielsätze → Modellantwort → erwartetes JSON (Abnahmesatz, „übermorgen um drei“,
  fehlende Uhrzeit wird markiert, „die Kinder“, Wiederholung, Namen statt Kennungen, mehrtägig, kein Termin),
  dazu Prompt (Datumstabelle, Zeitzone) und Schema (nur eigene Tags).
- `test_calendar.py` – Schreiben in den Kalender gegen eine Attrappe der Google Calendar API
  (`httpx.MockTransport`): Request-Body, Ganztägig/Standarddauer/Mitternacht, RRULE, Seitenweise lesen,
  Fehlerfälle, Rückweg zur Anzeige.
- `test_api.py` – Abnahme Ende zu Ende (einsprechen → bestätigen → Wochenansicht, Filter „Lena“),
  Modellwechsel ohne Deployment, nichts erkannt, Modell nicht erreichbar, CSRF-Schutz.
- `test_auth.py` – Token-Erneuerung, abgelaufenes Token → neue Anmeldung, Pflichtangaben im Cloud-Betrieb.
- `frontend/src/logic.test.ts` – Wochenrechnung, Filter, Überschneidungen, ganztägige Balken.
- `test_extraction_live.py` – dieselben Sätze gegen das echte Modell (nur auf Wunsch, kostet Cent-Beträge):

```powershell
$env:OPENROUTER_API_KEY = "sk-or-v1-…"; $env:KALENDER_LIVE_TESTS = "1"
.venv\Scripts\python -m pytest -m live -v
```

## Einrichtung in Google Cloud

Alle Befehle in PowerShell, angemeldet mit `gcloud auth login`. `PROJEKT` durch die eigene Projekt-ID ersetzen.

### 1. Projekt

```powershell
$P = "PROJEKT"
gcloud config set project $P
gcloud services enable calendar-json.googleapis.com
```

### 2. OAuth-Zustimmungsbildschirm und Client (einmalig, von Hand)

In der Cloud Console unter **Google Auth Platform**:

1. **Branding**: App-Name „Familienkalender“, Support-Adresse.
2. **Zielgruppe**: *Extern*. Dann **„App veröffentlichen“ (In Produktion)**. Wichtig: Im Status *Testen*
   laufen Refresh-Tokens nach **7 Tagen** ab – das Wand-Tablet wäre dann jede Woche abgemeldet. Google zeigt
   bei der Anmeldung den Hinweis „Google hat diese App nicht überprüft“ (*Erweitert → Weiter*); für eine
   Familie (unter 100 Konten) braucht es keine Überprüfung. Bei einem Google-Workspace-Konto geht stattdessen
   *Intern*.
3. **Datenzugriff** → Bereiche hinzufügen: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`,
   `https://www.googleapis.com/auth/calendar.events`,
   `https://www.googleapis.com/auth/calendar.calendarlist.readonly`.
4. **Clients** → *Client erstellen* → *Webanwendung*. Weiterleitungs-URI kommt nach dem ersten Deployment dazu
   (Schritt 5). Client-ID notieren, Client-Secret für Schritt 3 bereithalten.

### 3. Secrets

```powershell
"sk-or-v1-…" | gcloud secrets create kalender-openrouter-key --replication-policy=automatic --data-file=-
"GOCSPX-…"   | gcloud secrets create kalender-oauth-client-secret --replication-policy=automatic --data-file=-
```

(Den Zeilenumbruch, den PowerShell anhängt, entfernt der Server beim Einlesen.) Den Sitzungsschlüssel
`kalender-session-secret` legt das Deploy-Skript selbst zufällig an. Neuer Schlüssel später:

```powershell
"sk-or-v1-NEU" | gcloud secrets versions add kalender-openrouter-key --data-file=-
```

### 4. Deployment

```powershell
.\scripts\deploy.ps1 -ProjectId $P -OAuthClientId "123-abc.apps.googleusercontent.com" `
  -AllowedEmails "mama@gmail.com,papa@gmail.com"
```

Das Skript aktiviert Dienste (Cloud Run, Firestore, Secret Manager, Artifact Registry, Cloud Build, Calendar
API), legt Firestore (`eur3`), das Dienstkonto `kalender-run` (nur `roles/datastore.user` und Zugriff auf die
drei Secrets) und die Artifact Registry mit Aufräumregel an, baut das Image mit Cloud Build und veröffentlicht
den Dienst `kalender` in `europe-west1`. Erneut ausführen nach jeder Code- oder Einstellungsänderung; es setzt
Umgebungsvariablen und Secrets immer vollständig.

Die Freigabeliste (`-AllowedEmails`) ist Pflicht: Ohne sie startet der Dienst nicht.

### 5. Weiterleitungs-URI eintragen (einmalig)

Das Skript gibt am Ende die Adresse aus, z. B. `https://kalender-123456789.europe-west1.run.app`. Beim
OAuth-Client unter *Autorisierte Weiterleitungs-URIs* eintragen:

```
https://kalender-123456789.europe-west1.run.app/auth/callback
```

### 6. Kalender freigeben

Der gemeinsame Familienkalender muss für **jedes** Konto der Freigabeliste mit „Änderungen an Terminen
vornehmen“ freigegeben sein (Google Kalender → Einstellungen des Kalenders → *Für bestimmte Personen freigeben*).
Die Kalender-ID steht dort unter *Kalender integrieren* (`…@group.calendar.google.com`); in den Einstellungen
der App lässt sie sich auch direkt aus der Liste wählen.

### 7. Tablet einrichten

- Adresse in Chrome öffnen, anmelden, Mikrofon erlauben, *Zum Startbildschirm hinzufügen* (startet im Vollbild).
- Bildschirm-Timeout des Geräts hochsetzen bzw. Ladebetrieb „immer an“; die App hält den Bildschirm zusätzlich
  per Wake-Lock wach, solange sie sichtbar ist.
- Die Anmeldung gilt 180 Tage (Sitzungs-Cookie); das Google-Token erneuert der Server selbst.

### Kosten

Cloud Run, Firestore, Secret Manager und Artifact Registry bleiben bei Familiennutzung im Gratiskontingent.
Echte Kosten entstehen nur bei OpenRouter (eine Aufnahme mit MiMo-V2.6-Pro: deutlich unter einem Cent). Budget
mit Warnung empfohlen:

```powershell
gcloud billing budgets create --billing-account=KONTO-ID --display-name="Familienkalender" `
  --budget-amount=5EUR --threshold-rule=percent=0.8 --filter-projects=projects/$P
```

## Fehlerfälle

| Fall | Anzeige |
| --- | --- |
| Kein Mikrofonzugriff / kein Mikrofon / kein HTTPS | Meldung mit Knopf „Text eingeben“ |
| Modell nicht erreichbar, Schlüssel ungültig, Guthaben leer, Modell-ID falsch | Meldung mit dem Modellnamen (HTTP 502) |
| Nichts verstanden / kein Termin erkannt | Hinweis im Dialog, Text lässt sich bearbeiten und neu erkennen |
| Google-Token abgelaufen oder widerrufen | Banner „Die Google-Anmeldung ist abgelaufen“ mit „Erneut anmelden“ |
| Kalender-ID falsch oder ohne Schreibrecht | Meldung mit Hinweis auf die Einstellungen |
| Server nicht erreichbar | letzter Stand bleibt sichtbar, Fußzeile „offline“ |

## Getroffene Annahmen

| Entscheidung | Begründung / Quelle |
| --- | --- |
| Ein Cloud-Run-Dienst liefert Oberfläche und API aus (kein Firebase Hosting) | Auftrag: „Cloud Run für Frontend und Backend“; gleicher Ursprung erspart CORS und Cookie-Probleme. Abweichung vom Baukasten (2.2) bewusst. |
| Eigener OAuth-Code-Flow statt Firebase Authentication | Kalenderzugriff braucht ein Refresh-Token, das der Server hält; Firebase Auth liefert keins. Freigabeliste wie im Baukasten (`*_ALLOWED_EMAILS`). |
| Termine werden mit dem Google-Konto des angemeldeten Familienmitglieds geschrieben | Jeder sieht nur Kalender, die ihm freigegeben sind; kein Dienstkonto mit Kalenderrechten nötig. |
| Standard für beide Modelle `xiaomi/mimo-v2.6-pro` | Auftrag; Modell nimmt Audio an und kann JSON-Schema. |
| Startwerte Personen Mama, Papa, Lena, Max; Tags Schule, Arzt, Sport, Geburtstag, Arbeit, Freizeit | Beispiel aus dem Auftrag; in den Einstellungen änderbar. |
| Titel ohne Personennamen („Fußball“), Person über Farbe und Tag-Block | lesbarer an der Wand; in der Google-App steht „Personen: …“ in der Beschreibung. |
| Wochentag ohne Zusatz und „nächsten Freitag“ = nächstes Vorkommen nach heute | häufigste Lesart; im Dialog änderbar. |
| Keine Uhrzeit → ganztägig nur bei Tagesereignissen (Geburtstag, Ferien), sonst Feld markiert | Auftrag: „markieren statt raten“. |
| Modellliste 24 Std im Arbeitsspeicher statt Cloud Storage | Baukasten 2.8 nutzt Cloud Storage; bei einem Dienst ohne Bucket reicht der Speicher. |
| Filter: innerhalb einer Gruppe *oder*, zwischen Personen und Ereignissen *und* | übliche Mehrfachfilter-Logik. |
| Lokale Kalender-Attrappe zeigt Serien nur mit dem ersten Termin | Google expandiert Serien selbst (`singleEvents=true`); die Attrappe dient nur der Entwicklung. |
