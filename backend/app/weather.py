"""Aktuelles Wetter für das Icon in der Kopfzeile – Open-Meteo (frei, ohne Schlüssel).

Die Antwort wird 15 Minuten im Arbeitsspeicher gehalten: Alle Geräte der Familie teilen sich einen Abruf,
Open-Meteo aktualisiert die Werte ohnehin nur viertelstündlich.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Protocol

import httpx

from .errors import AppError

BASE_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL = 15 * 60


class WeatherClient(Protocol):
    def current(self, lat: float, lon: float) -> dict[str, Any]: ...


class OpenMeteo:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=httpx.Timeout(8, connect=4))

    def current(self, lat: float, lon: float) -> dict[str, Any]:
        params = {"latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code,is_day",
                  "timezone": "auto"}
        try:
            resp = self._client.get(BASE_URL, params=params)
            resp.raise_for_status()
            cur = resp.json()["current"]
            return {"temperature": round(float(cur["temperature_2m"])), "code": int(cur["weather_code"]),
                    "is_day": bool(cur["is_day"])}
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise AppError(502, "weather_unavailable", "Das Wetter ist gerade nicht abrufbar.") from exc


class CachedWeather:
    """Hält je Ort die letzte Antwort; ein Fehler fällt auf den letzten Stand zurück, solange es einen gibt."""

    def __init__(self, inner: WeatherClient, ttl: float = CACHE_TTL) -> None:
        self._inner = inner
        self._ttl = ttl
        self._lock = threading.Lock()
        self._cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}

    def current(self, lat: float, lon: float) -> dict[str, Any]:
        key = (round(lat, 3), round(lon, 3))
        with self._lock:
            hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        try:
            data = self._inner.current(lat, lon)
        except AppError:
            if hit:
                return hit[1]
            raise
        with self._lock:
            self._cache[key] = (time.monotonic(), data)
        return data


_weather = CachedWeather(OpenMeteo())


def get_weather() -> WeatherClient:
    return _weather
