# Familienkalender – Regeln für Agenten

- Muster: Skill `webapp-baukasten` (Referenz Topicetto). Bewusste Abweichungen stehen im README unter
  „Getroffene Annahmen“ (ein Cloud-Run-Dienst für alles, eigener OAuth-Flow statt Firebase Auth).
- Einstellungen der Familie (Modelle, Kalender, Tags) liegen in Firestore `config/settings`, nie im Code;
  Server-Konfiguration nur über Umgebungsvariablen in `backend/app/server_config.py`.
- Umgebungsvariablen und Secrets setzt nur `scripts/deploy.ps1`, immer vollständig.
- Der OpenRouter-Schlüssel geht nie an den Browser; Audio wird nicht gespeichert.
- Tests ohne Netz: `cd backend; .venv\Scripts\python -m pytest` und `cd frontend; npm test`.
  Abhängigkeiten über `app.dependency_overrides` ersetzen (`store_dep`, `llm_dep`, `now_dep`).
- Lokal: `scripts\dev.ps1` (ohne Anmeldung, Kalender-Attrappe, Demo-KI).
- Texte deutsch; der deutsche Text ist der Übersetzungsschlüssel (`t("…")` in `frontend/src/i18n.ts`).
- CSS ist global: neue Klassen vorher gegen `frontend/src/styles.css` prüfen.
