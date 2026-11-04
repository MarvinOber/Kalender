"""Server-Einstellungen aus Umgebungsvariablen (Cloud Run setzt sie beim Deployment, lokal ``backend/.env``).

Hier steht nur, was je Installation fest ist (Projekt, Schlüssel, Freigabeliste). Alles, was die Familie in
der Oberfläche ändert (Modelle, Kalender, Personen, Tags), liegt in der Datenbank – siehe ``settings.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read_dotenv() -> None:
    """``backend/.env`` für den lokalen Betrieb einlesen (vorhandene Umgebungsvariablen haben Vorrang)."""
    try:
        lines = (BACKEND_DIR / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "ja", "on")


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").replace(";", ",").split(",") if x.strip()]


@dataclass(frozen=True)
class ServerConfig:
    backend: str  # cloud (Firestore) | local (JSON-Datei)
    auth_mode: str  # google (OAuth mit Kalenderzugriff) | none (nur lokal: fester Benutzer, Kalender-Attrappe)
    project: str
    firestore_database: str
    data_dir: Path  # lokaler Speicher (nur backend=local)
    static_dir: Path  # gebaute Oberfläche (im Image: /srv/static)
    allowed_emails: list[str] = field(default_factory=list)  # Freigabeliste der Familie (Pflicht mit Google)
    public_url: str = ""  # feste Adresse für den OAuth-Rücksprung; leer = aus der Anfrage ableiten
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    session_secret: str = ""
    openrouter_api_key: str = ""
    fake_llm: bool = False  # ohne KI-Kosten: feste Beispielaufnahme
    vapid_private_key: str = ""  # Web Push; leer = lokal selbst erzeugt, in der Cloud: Push aus
    cron_secret: str = ""  # Kopfzeile X-Kalender-Cron, mit der Cloud Scheduler die Erinnerungen anstößt

    @property
    def cloud(self) -> bool:
        return self.backend == "cloud"


def _default_static() -> Path:
    """Im Image liegt die gebaute Oberfläche unter ``static``, lokal unter ``frontend/dist``."""
    image = BACKEND_DIR / "static"
    return image if image.is_dir() else BACKEND_DIR.parent / "frontend" / "dist"


@lru_cache(maxsize=1)
def get_config() -> ServerConfig:
    _read_dotenv()
    backend = os.environ.get("KALENDER_BACKEND", "local").strip().lower()
    auth = os.environ.get("KALENDER_AUTH", "google" if backend == "cloud" else "none").strip().lower()
    if backend == "cloud" and auth == "none":
        raise RuntimeError("KALENDER_AUTH=none ist nur im lokalen Betrieb erlaubt.")
    allowed = [e.lower() for e in _list("KALENDER_ALLOWED_EMAILS")]
    session_secret = os.environ.get("KALENDER_SESSION_SECRET", "").strip()
    if auth == "google":
        # Ohne Freigabeliste käme jedes Google-Konto an die gemeinsamen Einstellungen und den KI-Zugang.
        if not allowed:
            raise RuntimeError("KALENDER_ALLOWED_EMAILS fehlt (kommagetrennte Adressen der Familie).")
        if not session_secret:
            raise RuntimeError("KALENDER_SESSION_SECRET fehlt.")
        if not os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or not os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"):
            raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET fehlen.")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT") or ""
    return ServerConfig(
        backend=backend,
        auth_mode=auth,
        project=project,
        firestore_database=os.environ.get("KALENDER_FIRESTORE_DB", "(default)"),
        data_dir=Path(os.environ.get("KALENDER_DATA_DIR", str(BACKEND_DIR / "data"))),
        static_dir=Path(os.environ.get("KALENDER_STATIC_DIR", "") or _default_static()),
        allowed_emails=allowed,
        public_url=os.environ.get("KALENDER_PUBLIC_URL", "").strip().rstrip("/"),
        oauth_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        oauth_client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        session_secret=session_secret or "nur-lokal-nicht-geheim",
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        fake_llm=_flag("KALENDER_FAKE_LLM"),
        vapid_private_key=os.environ.get("KALENDER_VAPID_PRIVATE_KEY", "").strip(),
        cron_secret=os.environ.get("KALENDER_CRON_SECRET", "").strip(),
    )
