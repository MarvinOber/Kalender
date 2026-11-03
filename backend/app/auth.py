"""Google-Anmeldung per OAuth (Autorisierungscode) mit Kalenderzugriff.

Der Server tauscht den Code selbst ein und bewahrt das Refresh-Token in der Datenbank auf – das Wand-Tablet
bleibt so über Wochen angemeldet, ohne dass ein Token im Browser liegt. Im Browser steht nur ein signiertes
Sitzungs-Cookie mit der E-Mail-Adresse. Zugang nur für ``KALENDER_ALLOWED_EMAILS``.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from .docstore import DocStore, get_store
from .errors import AppError, ReauthRequired
from .server_config import ServerConfig, get_config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
SCOPES = [
    "openid", "email", "profile",
    CALENDAR_SCOPE,  # Termine lesen und anlegen
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",  # Kalenderauswahl in den Einstellungen
]
LOCAL_USER = "lokal@example.com"

router = APIRouter()


@dataclass(frozen=True)
class User:
    email: str
    name: str = ""


def _user_path(email: str) -> str:
    return f"users/{email.lower()}"


def _redirect_uri(request: Request, cfg: ServerConfig) -> str:
    base = cfg.public_url or str(request.base_url).rstrip("/")
    return f"{base}/auth/callback"


def _decode_id_token(id_token: str) -> dict:
    """Nutzdaten des ID-Tokens. Keine Signaturprüfung nötig: Es kommt direkt per TLS vom Token-Endpunkt."""
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@router.get("/auth/login")
def login(request: Request) -> RedirectResponse:
    cfg = get_config()
    if cfg.auth_mode == "none":
        return RedirectResponse("/")
    # Cloud Run hat mehrere Adressen; Sitzung und Rücksprung müssen auf derselben liegen
    if cfg.public_url and str(request.base_url).rstrip("/") != cfg.public_url:
        return RedirectResponse(f"{cfg.public_url}/auth/login")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    params = {
        "client_id": cfg.oauth_client_id,
        "redirect_uri": _redirect_uri(request, cfg),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # Refresh-Token für den Dauerbetrieb
        "prompt": "consent select_account",  # liefert das Refresh-Token auch bei erneuter Anmeldung
        "include_granted_scopes": "true",
        "state": state,
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")


@router.get("/auth/callback", name="auth_callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    cfg = get_config()
    expected = request.session.pop("oauth_state", None)
    if error:
        return RedirectResponse("/?login_error=abgebrochen")
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/?login_error=ungueltig")
    try:
        resp = httpx.post(TOKEN_URL, timeout=20, data={
            "code": code, "client_id": cfg.oauth_client_id, "client_secret": cfg.oauth_client_secret,
            "redirect_uri": _redirect_uri(request, cfg), "grant_type": "authorization_code"})
    except httpx.HTTPError:
        return RedirectResponse("/?login_error=google")
    if resp.status_code != 200:
        return RedirectResponse("/?login_error=google")
    tokens = resp.json()
    claims = _decode_id_token(tokens.get("id_token", ""))
    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified") or email not in cfg.allowed_emails:
        request.session.clear()
        return RedirectResponse("/?login_error=nicht_freigegeben")
    if CALENDAR_SCOPE not in tokens.get("scope", "").split():
        return RedirectResponse("/?login_error=kein_kalender")
    store = get_store()
    user = store.get(_user_path(email)) or {}
    refresh = tokens.get("refresh_token") or user.get("refresh_token")
    if not refresh:
        return RedirectResponse("/?login_error=kein_refresh")
    store.set(_user_path(email), {"email": email, "name": claims.get("name") or "", "refresh_token": refresh,
                                  "updated": int(time.time())})
    _token_cache.pop(email, None)
    request.session["email"] = email
    return RedirectResponse("/")


@router.post("/auth/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


def access_token(email: str, store: DocStore, cfg: ServerConfig, client: httpx.Client | None = None) -> str:
    """Gültiges Zugriffstoken; erneuert es über das Refresh-Token, wenn es in weniger als 2 Min abläuft."""
    with _token_lock:
        cached = _token_cache.get(email)
        if cached and cached[1] - time.time() > 120:
            return cached[0]
    user = store.get(_user_path(email)) or {}
    if not user.get("refresh_token"):
        raise ReauthRequired()
    try:
        resp = (client or httpx).post(TOKEN_URL, timeout=20, data={
            "client_id": cfg.oauth_client_id, "client_secret": cfg.oauth_client_secret,
            "refresh_token": user["refresh_token"], "grant_type": "refresh_token"})
    except httpx.HTTPError as exc:
        raise AppError(503, "google_unreachable", "Google ist gerade nicht erreichbar.") from exc
    if resp.status_code in (400, 401):
        # invalid_grant: widerrufen, Passwort geändert oder (Testmodus des OAuth-Clients) nach 7 Tagen abgelaufen
        store.set(_user_path(email), {**user, "refresh_token": ""})
        raise ReauthRequired()
    if resp.status_code != 200:
        raise AppError(503, "google_unreachable", "Google ist gerade nicht erreichbar.")
    data = resp.json()
    token = data["access_token"]
    with _token_lock:
        _token_cache[email] = (token, time.time() + int(data.get("expires_in", 3600)))
    return token


def current_user(request: Request) -> User:
    cfg = get_config()
    if cfg.auth_mode == "none":
        return User(LOCAL_USER, "Lokal")
    email = request.session.get("email") if "session" in request.scope else None
    if not email:
        raise AppError(401, "login", "Bitte mit Google anmelden.")
    if email not in cfg.allowed_emails:
        request.session.clear()
        raise AppError(403, "not_allowed", "Diese Adresse ist nicht freigegeben.")
    user = get_store().get(_user_path(email)) or {}
    if not user.get("refresh_token"):
        raise ReauthRequired()
    return User(email, user.get("name") or "")


CurrentUser = Depends(current_user)
