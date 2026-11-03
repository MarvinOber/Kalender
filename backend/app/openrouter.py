"""OpenRouter: ein Schlüssel für alle Modelle (OpenAI-kompatibel). Der Schlüssel verlässt nie den Server."""

from __future__ import annotations

import base64
import threading
import time
from typing import Any, Protocol

import httpx

from .errors import ModelUnavailable

BASE_URL = "https://openrouter.ai/api/v1"
APP_TITLE = "Familienkalender"
MODELS_TTL = 24 * 3600

TRANSCRIBE_PROMPT = {
    "de": ("Transkribiere diese Sprachaufnahme wortgetreu auf Deutsch. Gib nur den gesprochenen Text aus – "
           "ohne Anführungszeichen, Zeitstempel oder Kommentar. Ist nichts Verständliches zu hören, antworte "
           "mit einer leeren Nachricht."),
    "en": ("Transcribe this voice recording verbatim. Output only the spoken text – no quotes, timestamps or "
           "comments. If nothing intelligible can be heard, reply with an empty message."),
}


class LlmClient(Protocol):
    def transcribe(self, model: str, audio: bytes, audio_format: str, language: str) -> str: ...
    def complete_json(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> str: ...


class OpenRouter:
    def __init__(self, api_key: str, referer: str = "", client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._referer = referer
        self._client = client or httpx.Client(timeout=httpx.Timeout(90, connect=10))

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._key}", "X-OpenRouter-Title": APP_TITLE}
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        return headers

    def _chat(self, model: str, payload: dict[str, Any]) -> str:
        if not self._key:
            raise ModelUnavailable("Kein OpenRouter-Schlüssel eingerichtet (Secret OPENROUTER_API_KEY).")
        try:
            resp = self._client.post(f"{BASE_URL}/chat/completions", headers=self._headers(),
                                     json={"model": model, **payload})
        except httpx.TimeoutException as exc:
            raise ModelUnavailable(f"Das Modell {model} antwortet nicht rechtzeitig. Bitte erneut versuchen.") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable("OpenRouter ist gerade nicht erreichbar.") from exc
        if resp.status_code >= 400:
            raise ModelUnavailable(_error_message(resp, model))
        data = resp.json()
        if data.get("error"):
            raise ModelUnavailable(f"Das Modell {model} meldet einen Fehler: {data['error'].get('message', '')}")
        try:
            return (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable(f"Unerwartete Antwort von {model}.") from exc

    def transcribe(self, model: str, audio: bytes, audio_format: str, language: str) -> str:
        content = [
            {"type": "text", "text": TRANSCRIBE_PROMPT.get(language, TRANSCRIBE_PROMPT["de"])},
            {"type": "input_audio",
             "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": audio_format}},
        ]
        return self._chat(model, {"messages": [{"role": "user", "content": content}], "temperature": 0})

    def complete_json(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> str:
        return self._chat(model, {
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "termine", "strict": True, "schema": schema}},
            # nur Anbieter, die das JSON-Schema wirklich durchsetzen
            "provider": {"require_parameters": True},
        })


def _error_message(resp: httpx.Response, model: str) -> str:
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except ValueError:
        detail = ""
    if resp.status_code == 401:
        return "Der OpenRouter-Schlüssel ist ungültig."
    if resp.status_code == 402:
        return "Das Guthaben bei OpenRouter ist aufgebraucht."
    if resp.status_code == 404 or "not a valid model" in detail.lower():
        return f"Das Modell {model} gibt es bei OpenRouter nicht (Einstellungen prüfen)."
    if resp.status_code == 429:
        return f"Das Modell {model} ist gerade ausgelastet. Bitte gleich noch einmal."
    if resp.status_code == 400:
        return f"Das Modell {model} kann diese Anfrage nicht verarbeiten. {detail}".strip()
    return f"Das Modell {model} ist nicht erreichbar (Fehler {resp.status_code})."


_models_cache: dict[str, Any] = {"at": 0.0, "data": []}
_models_lock = threading.Lock()


def list_models(client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Modellkatalog (öffentlich, ohne Schlüssel), 24 Std im Speicher – kurz und für die Auswahl aufbereitet."""
    with _models_lock:
        if _models_cache["data"] and time.time() - _models_cache["at"] < MODELS_TTL:
            return _models_cache["data"]
    try:
        resp = (client or httpx.Client(timeout=20)).get(f"{BASE_URL}/models")
        resp.raise_for_status()
        raw = resp.json().get("data", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise ModelUnavailable("Die Modellliste von OpenRouter ist gerade nicht abrufbar.") from exc
    models = []
    for m in raw:
        arch = m.get("architecture") or {}
        params = m.get("supported_parameters") or []
        models.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "audio": "audio" in (arch.get("input_modalities") or []),
            "structured": "structured_outputs" in params or "response_format" in params,
            "prompt_price": (m.get("pricing") or {}).get("prompt"),
        })
    models.sort(key=lambda x: x["id"])
    with _models_lock:
        _models_cache.update(at=time.time(), data=models)
    return models
