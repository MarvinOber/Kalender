"""Wetter-Icon: Abruf bei Open-Meteo (Attrappe über ``httpx.MockTransport``), Zwischenspeicher, API."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app import main
from app.errors import AppError
from app.weather import CachedWeather, OpenMeteo


def open_meteo(handler) -> OpenMeteo:
    return OpenMeteo(httpx.Client(transport=httpx.MockTransport(handler)))


def test_open_meteo_liest_aktuelles_wetter():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"current": {"temperature_2m": 9.6, "weather_code": 3, "is_day": 0}})

    assert open_meteo(handler).current(53.86667, 9.73333) == {"temperature": 10, "code": 3, "is_day": False}
    params = seen[0].url.params
    assert params["latitude"] == "53.86667" and params["longitude"] == "9.73333"
    assert params["current"] == "temperature_2m,weather_code,is_day"


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, json={"error": True})])
def test_open_meteo_fehler_wird_app_error(response):
    with pytest.raises(AppError) as err:
        open_meteo(lambda _: response).current(1, 2)
    assert err.value.code == "weather_unavailable"


class CountingWeather:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def current(self, lat: float, lon: float) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise AppError(502, "weather_unavailable", "weg")
        return {"temperature": self.calls, "code": 0, "is_day": True}


def test_zwischenspeicher_und_rueckfall_auf_letzten_stand():
    inner = CountingWeather()
    cached = CachedWeather(inner, ttl=60)
    assert cached.current(53.8, 9.7)["temperature"] == 1
    assert cached.current(53.8, 9.7)["temperature"] == 1  # aus dem Speicher
    assert inner.calls == 1

    expired = CachedWeather(inner, ttl=0)
    assert expired.current(1, 1)["temperature"] == 2
    inner.fail = True
    assert expired.current(1, 1)["temperature"] == 2  # Fehler → letzter Stand
    with pytest.raises(AppError):
        expired.current(2, 2)  # ohne Stand bleibt der Fehler


def test_api_wetter_fuer_ort_aus_den_einstellungen(client):
    calls: list[tuple[float, float]] = []

    class Fake:
        def current(self, lat: float, lon: float) -> dict[str, Any]:
            calls.append((lat, lon))
            return {"temperature": 8, "code": 61, "is_day": True}

    main.app.dependency_overrides[main.weather_dep] = Fake
    assert client.get("/api/weather").json() == {"place": "Bokel", "temperature": 8, "code": 61, "is_day": True}
    assert calls == [(53.86667, 9.73333)]

    settings = client.get("/api/settings").json() | {"weather_place": "Elmshorn", "weather_lat": 53.75,
                                                     "weather_lon": 9.65}
    assert client.put("/api/settings", json=settings).status_code == 200
    assert client.get("/api/weather").json()["place"] == "Elmshorn"
    assert calls[-1] == (53.75, 9.65)

    assert client.put("/api/settings", json=settings | {"weather_place": " "}).status_code == 200
    assert client.get("/api/weather").json() == {"place": ""}
    assert len(calls) == 2

    assert client.put("/api/settings", json=settings | {"weather_lat": 123}).status_code == 422
