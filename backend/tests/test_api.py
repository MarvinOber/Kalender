"""Abläufe über die API: einsprechen → bestätigen → im Kalender; Einstellungen; Fehlerfälle."""

from __future__ import annotations

import io
import json
import wave

import httpx

from app import main
from app.calendar_api import GoogleCalendar
from app.fake_llm import DEMO_SENTENCE
from app.openrouter import ModelUnavailable

from .conftest import ScriptedLlm
from .test_calendar import FakeGoogleCalendarServer


def wav_bytes(seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_abnahme_einsprechen_bestaetigen_anzeigen(client):
    # 1. Aufnahme senden (FakeLlm: feste Beispielaufnahme)
    resp = client.post("/api/voice", files={"audio": ("aufnahme.wav", wav_bytes(), "audio/wav")})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["transcript"] == DEMO_SENTENCE
    fussball, geburtstag = data["events"]
    assert (fussball["start_date"], fussball["start_time"], fussball["persons"], fussball["tags"]) == \
        ("2026-11-06", "16:00:00", ["lena"], ["sport"])
    assert (geburtstag["start_date"], geburtstag["all_day"], geburtstag["tags"]) == ("2026-11-07", True, ["geburtstag"])

    # 2. Vor „Anlegen“ steht nichts im Kalender
    assert client.get("/api/events", params={"start": "2026-11-02"}).json()["events"] == []

    # 3. Anlegen
    resp = client.post("/api/events", json={"events": data["events"]})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["created"]) == 2

    # 4. Wochenansicht liest beide mit Tags zurück
    week = client.get("/api/events", params={"start": "2026-11-02"}).json()["events"]
    by_title = {e["title"]: e for e in week}
    assert by_title["Fußball"]["start"] == "2026-11-06T16:00" and by_title["Fußball"]["persons"] == ["lena"]
    assert by_title["Omas Geburtstag"]["all_day"] and by_title["Omas Geburtstag"]["start"] == "2026-11-07"
    # Filter „Lena“ (in der Oberfläche): nur Lenas Termin trägt die Person
    assert [e["title"] for e in week if "lena" in e["persons"]] == ["Fußball"]
    # andere Woche: leer
    assert client.get("/api/events", params={"start": "2026-11-09"}).json()["events"] == []


def test_modellwechsel_wirkt_ohne_deployment(client):
    llm = ScriptedLlm(transcript="Morgen um 8 Arzt")
    main.app.dependency_overrides[main.llm_dep] = lambda: llm
    settings = client.get("/api/settings").json()
    assert settings["transcription_model"] == "xiaomi/mimo-v2.6-pro"
    client.post("/api/voice", files={"audio": ("a.wav", wav_bytes(), "audio/wav")})
    assert [c["model"] for c in llm.calls] == ["xiaomi/mimo-v2.6-pro", "xiaomi/mimo-v2.6-pro"]

    settings |= {"transcription_model": "google/gemini-3.5-flash", "extraction_model": "openai/gpt-audio-mini"}
    assert client.put("/api/settings", json=settings).status_code == 200
    llm.calls.clear()
    client.post("/api/voice", files={"audio": ("a.wav", wav_bytes(), "audio/wav")})
    assert [c["model"] for c in llm.calls] == ["google/gemini-3.5-flash", "openai/gpt-audio-mini"]
    assert llm.calls[0]["format"] == "wav"


def test_einstellungen_pruefen(client):
    settings = client.get("/api/settings").json()
    bad = settings | {"timezone": "Mond/Krater"}
    resp = client.put("/api/settings", json=bad)
    assert resp.status_code == 422 and "Zeitzone" in resp.json()["message"]
    settings["persons"].append({"name": "Oma Inge", "color": "#aabbcc", "aliases": ["Oma"]})
    saved = client.put("/api/settings", json=settings).json()
    assert saved["persons"][-1]["id"] == "oma-inge"
    # neue Person steht sofort im Schema des Modells
    llm = ScriptedLlm()
    main.app.dependency_overrides[main.llm_dep] = lambda: llm
    client.post("/api/parse", json={"text": "Oma kommt Sonntag"})
    assert "oma-inge" in llm.calls[0]["schema"]["properties"]["events"]["items"]["properties"]["persons"]["items"][
        "enum"]


def test_nichts_erkannt(client):
    llm = ScriptedLlm(transcript="")
    main.app.dependency_overrides[main.llm_dep] = lambda: llm
    data = client.post("/api/voice", files={"audio": ("a.wav", wav_bytes(), "audio/wav")}).json()
    assert data["events"] == [] and "nichts zu verstehen" in data["message"]
    assert [c["kind"] for c in llm.calls] == ["transcribe"]  # ohne Transkript keine Erkennung
    data = client.post("/api/parse", json={"text": "Hallo"}).json()
    assert data["events"] == [] and data["message"] == "Im Gesagten wurde kein Termin erkannt."


def test_modell_nicht_erreichbar(client):
    class Down(ScriptedLlm):
        def transcribe(self, *a, **k):
            raise ModelUnavailable("Das Modell xiaomi/mimo-v2.6-pro ist nicht erreichbar (Fehler 503).")

    main.app.dependency_overrides[main.llm_dep] = lambda: Down()
    resp = client.post("/api/voice", files={"audio": ("a.wav", wav_bytes(), "audio/wav")})
    assert resp.status_code == 502
    assert resp.json() == {"code": "model_unavailable",
                           "message": "Das Modell xiaomi/mimo-v2.6-pro ist nicht erreichbar (Fehler 503)."}


def test_anlegen_prueft_alle_vorher(client):
    good = {"title": "A", "start_date": "2026-11-06", "start_time": "10:00"}
    bad = {"title": "B", "start_date": "2026-11-06"}
    resp = client.post("/api/events", json={"events": [good, bad]})
    assert resp.status_code == 422 and "Termin 2: Uhrzeit fehlt" in resp.json()["message"]
    assert client.get("/api/events", params={"start": "2026-11-02"}).json()["events"] == []


def test_schreiben_braucht_eigenen_header(client):
    resp = client.post("/api/parse", json={"text": "x"}, headers={"X-Kalender": ""})
    assert resp.status_code == 403


def test_falsches_audioformat(client):
    resp = client.post("/api/voice", files={"audio": ("a.exe", b"x" * 5000, "application/octet-stream")})
    assert resp.status_code == 415


def test_termin_bearbeiten_und_loeschen(client):
    draft = {"title": "Fußball", "start_date": "2026-11-06", "start_time": "16:00", "persons": ["lena"],
             "tags": ["sport"]}
    event_id = client.post("/api/events", json={"events": [draft]}).json()["created"][0]["id"]

    data = client.get(f"/api/events/{event_id}").json()
    assert data["id"] == event_id and data["recurrence_editable"] and not data["series"]
    loaded = data["draft"]
    assert (loaded["start_time"], loaded["end_time"], loaded["persons"]) == ("16:00:00", "17:00:00", ["lena"])

    loaded |= {"title": "Fußball (Halle)", "start_time": "15:00", "end_time": "16:30", "persons": ["lena", "max"]}
    resp = client.put(f"/api/events/{event_id}", json={"draft": loaded})
    assert resp.status_code == 200, resp.text
    assert resp.json()["event"]["start"] == "2026-11-06T15:00"
    week = client.get("/api/events", params={"start": "2026-11-02"}).json()["events"]
    assert [(e["title"], e["end"], e["persons"]) for e in week] == [("Fußball (Halle)", "2026-11-06T16:30",
                                                                     ["lena", "max"])]

    bad = client.put(f"/api/events/{event_id}", json={"draft": loaded | {"title": " "}})
    assert bad.status_code == 422 and "Titel fehlt" in bad.json()["message"]

    assert client.delete(f"/api/events/{event_id}").json() == {"ok": True}
    assert client.get("/api/events", params={"start": "2026-11-02"}).json()["events"] == []
    gone = client.get(f"/api/events/{event_id}")
    assert gone.status_code == 404 and "gelöscht" in gone.json()["message"]


def test_serie_oder_einzelner_termin(client):
    """Wochenansicht zeigt Vorkommen; „Ganze Serie“ wirkt auf den Serientermin, sonst nur auf das Vorkommen."""
    server = FakeGoogleCalendarServer()
    gcal = GoogleCalendar(lambda: "tok-1", httpx.Client(transport=httpx.MockTransport(server)))
    main.app.dependency_overrides[main.calendar_dep] = lambda: gcal
    master = {"id": "s1", "summary": "Schwimmen", "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU"],
              "start": {"dateTime": "2026-11-03T17:00:00+01:00", "timeZone": "Europe/Berlin"},
              "end": {"dateTime": "2026-11-03T18:00:00+01:00", "timeZone": "Europe/Berlin"}}
    instance = {"id": "s1_20261110T160000Z", "recurringEventId": "s1", "summary": "Schwimmen",
                "start": {"dateTime": "2026-11-10T17:00:00+01:00"}, "end": {"dateTime": "2026-11-10T18:00:00+01:00"}}
    server.events["primary"] = [master, instance]

    series = client.get("/api/events/s1_20261110T160000Z", params={"scope": "series"}).json()
    assert series["id"] == "s1" and series["series"] and series["recurrence_editable"]
    assert series["draft"]["start_date"] == "2026-11-03" and series["draft"]["recurrence"]["by_day"] == ["TU"]

    single = client.get("/api/events/s1_20261110T160000Z").json()
    assert single["id"] == "s1_20261110T160000Z" and not single["recurrence_editable"]
    # Ein Vorkommen bekommt nie eine eigene Wiederholung – auch wenn der Dialog eine mitschickt
    daily = {"freq": "daily", "interval": 1, "by_day": [], "until": None, "count": None}
    draft = single["draft"] | {"start_time": "18:00", "end_time": "19:00", "recurrence": daily}
    assert client.put("/api/events/s1_20261110T160000Z", json={"draft": draft}).status_code == 200
    sent = json.loads(server.requests[-1].content)
    assert "recurrence" not in sent and sent["start"]["dateTime"] == "2026-11-10T18:00:00"

    # Serie mit unveränderter Wiederholung: Regel bleibt, wie Google sie hat
    series_draft = series["draft"] | {"title": "Schwimmkurs"}
    client.put("/api/events/s1", json={"draft": series_draft, "recurrence_unchanged": True})
    assert "recurrence" not in json.loads(server.requests[-1].content)
    assert server.events["primary"][0]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]

    assert client.delete("/api/events/s1_20261110T160000Z", params={"scope": "series"}).status_code == 200
    assert server.requests[-1].method == "DELETE" and server.requests[-1].url.path.endswith("/events/s1")
    assert [e["id"] for e in server.events["primary"]] == ["s1_20261110T160000Z"]
