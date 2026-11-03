"""Google-Anmeldung: Token-Erneuerung, abgelaufenes Refresh-Token, Pflichtangaben im Cloud-Betrieb."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app import auth, server_config
from app.errors import ReauthRequired
from app.server_config import ServerConfig, get_config


@pytest.fixture(autouse=True)
def _clear_cache():
    auth._token_cache.clear()
    yield
    auth._token_cache.clear()


def token_client(status: int, body: dict, seen: list) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(x.split("=", 1) for x in request.content.decode().split("&")))
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def cfg() -> ServerConfig:
    return get_config()


def test_erneuert_und_merkt_sich_das_token(store):
    store.set("users/mama@example.com", {"refresh_token": "r1"})
    seen: list = []
    client = token_client(200, {"access_token": "a1", "expires_in": 3599}, seen)
    assert auth.access_token("mama@example.com", store, cfg(), client) == "a1"
    assert auth.access_token("mama@example.com", store, cfg(), client) == "a1"
    assert len(seen) == 1 and seen[0]["grant_type"] == "refresh_token" and seen[0]["refresh_token"] == "r1"


def test_widerrufenes_token_verlangt_neue_anmeldung(store):
    store.set("users/mama@example.com", {"refresh_token": "r1", "name": "Mama"})
    client = token_client(400, {"error": "invalid_grant"}, [])
    with pytest.raises(ReauthRequired) as exc:
        auth.access_token("mama@example.com", store, cfg(), client)
    assert exc.value.code == "reauth" and "abgelaufen" in exc.value.message
    assert store.get("users/mama@example.com")["refresh_token"] == ""


def test_ohne_refresh_token_neue_anmeldung(store):
    with pytest.raises(ReauthRequired):
        auth.access_token("unbekannt@example.com", store, cfg(), token_client(200, {}, []))


def test_id_token_nutzdaten():
    payload = base64.urlsafe_b64encode(json.dumps({"email": "Papa@Example.com"}).encode()).decode().rstrip("=")
    assert auth._decode_id_token(f"kopf.{payload}.sig")["email"] == "Papa@Example.com"


@pytest.mark.parametrize(("env", "message"), [
    ({"KALENDER_AUTH": "none"}, "nur im lokalen Betrieb"),
    ({}, "KALENDER_ALLOWED_EMAILS fehlt"),
    ({"KALENDER_ALLOWED_EMAILS": "a@b.de"}, "KALENDER_SESSION_SECRET fehlt"),
])
def test_cloud_betrieb_verlangt_freigabeliste(monkeypatch, env, message):
    for key in ("KALENDER_AUTH", "KALENDER_ALLOWED_EMAILS", "KALENDER_SESSION_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(server_config, "_read_dotenv", lambda: None)  # eine lokale backend/.env nicht einlesen
    monkeypatch.setenv("KALENDER_BACKEND", "cloud")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_config.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=message):
            get_config()
    finally:
        get_config.cache_clear()
