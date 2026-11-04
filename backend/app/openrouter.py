"""OpenRouter: ein Schlüssel für alle Modelle (OpenAI-kompatibel). Der Schlüssel verlässt nie den Server."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from .errors import ModelTimeout, ModelUnavailable

BASE_URL = "https://openrouter.ai/api/v1"
APP_TITLE = "Familienkalender"
MODELS_TTL = 24 * 3600
# Gesamtfrist für alle Modellaufrufe einer Anfrage (Sprache: Transkription + Erkennung). Cloud Run bricht nach
# 120 s ab (scripts/deploy.ps1, --timeout); die Lücke bleibt für Upload und Antwort.
MODEL_BUDGET_SECONDS = 90

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
    """Ein Objekt je Anfrage (``llm_dep``): Die Frist beginnt beim Anlegen und gilt für alle Aufrufe zusammen."""

    def __init__(self, api_key: str, referer: str = "", client: httpx.Client | None = None,
                 budget: float = MODEL_BUDGET_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._key = api_key
        self._referer = referer
        self._client = client or httpx.Client()
        self._budget = budget
        self._clock = clock
        self._deadline = clock() + budget

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._key}", "X-OpenRouter-Title": APP_TITLE}
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        return headers

    def _timeout(self, model: str) -> ModelTimeout:
        return ModelTimeout(f"Das Modell {model} hat nicht rechtzeitig geantwortet (Abbruch nach "
                            f"{self._budget:.0f} Sekunden). Bitte noch einmal versuchen oder in den Einstellungen "
                            "ein schnelleres Modell wählen.")

    def _post(self, model: str, body: dict[str, Any]) -> tuple[int, bytes]:
        """Antwort stückweise lesen: OpenRouter hält langsame Antworten mit Leerzeichen wach, dann greift das
        Lese-Timeout von httpx nie – die Gesamtfrist wird deshalb nach jedem Stück geprüft."""
        remaining = self._deadline - self._clock()
        if remaining <= 1:
            raise self._timeout(model)
        timeout = httpx.Timeout(remaining, connect=min(10.0, remaining))
        try:
            with self._client.stream("POST", f"{BASE_URL}/chat/completions", headers=self._headers(),
                                     json=body, timeout=timeout) as resp:
                chunks = []
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    if self._clock() > self._deadline:
                        raise self._timeout(model)  # verlässt den Block und schließt die Verbindung
                return resp.status_code, b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise self._timeout(model) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable("OpenRouter ist gerade nicht erreichbar.") from exc

    def _chat(self, model: str, payload: dict[str, Any]) -> str:
        if not self._key:
            raise ModelUnavailable("Kein OpenRouter-Schlüssel eingerichtet (Secret OPENROUTER_API_KEY).")
        status, raw = self._post(model, {"model": model, **payload})
        if status >= 400:
            raise ModelUnavailable(_error_message(status, raw, model))
        try:
            data = json.loads(raw)  # führende Leerzeichen vom Wachhalten stören json nicht
        except ValueError as exc:
            raise ModelUnavailable(f"Unerwartete Antwort von {model}.") from exc
        if not isinstance(data, dict):
            raise ModelUnavailable(f"Unerwartete Antwort von {model}.")
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


def _error_message(status: int, raw: bytes, model: str) -> str:
    try:
        detail = str(json.loads(raw).get("error", {}).get("message", ""))
    except (ValueError, AttributeError):
        detail = ""
    if status == 401:
        return "Der OpenRouter-Schlüssel ist ungültig."
    if status == 402:
        return "Das Guthaben bei OpenRouter ist aufgebraucht."
    if status == 404 or "not a valid model" in detail.lower():
        return f"Das Modell {model} gibt es bei OpenRouter nicht (Einstellungen prüfen)."
    if status == 408 or status == 504:
        return (f"Das Modell {model} hat nicht rechtzeitig geantwortet. Bitte noch einmal versuchen oder in den "
                "Einstellungen ein schnelleres Modell wählen.")
    if status == 429:
        return f"Das Modell {model} ist gerade ausgelastet. Bitte gleich noch einmal."
    if status == 400:
        return f"Das Modell {model} kann diese Anfrage nicht verarbeiten. {detail}".strip()
    return f"Das Modell {model} ist nicht erreichbar (Fehler {status})."


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
        inputs = arch.get("input_modalities") or []
        models.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "audio": "audio" in inputs,
            "image": "image" in inputs,
            "structured": "structured_outputs" in params or "response_format" in params,
            "prompt_price": (m.get("pricing") or {}).get("prompt"),
        })
    models.sort(key=lambda x: x["id"])
    with _models_lock:
        _models_cache.update(at=time.time(), data=models)
    return models
