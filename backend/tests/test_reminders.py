"""Erinnerungen: wann was an welches Gerät geht, Texte, Abos über die API, Erinnerungslauf von Cloud Scheduler."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Any

import pytest

from app import main
from app.auth import LOCAL_USER
from app.errors import ReauthRequired
from app.reminders import (
    SENT_PATH,
    Subscription,
    list_subscriptions,
    run_reminders,
    save_subscription,
)
from app.webpush import PushFailed, PushGone, Target, b64url, b64url_decode

from .conftest import BERLIN, NOW
from .test_push import browser_keys

LONG_AGO = "2026-09-01T08:00:00.000Z"


class FakeSender:
    """Statt Push-Dienst: merkt sich jede Nachricht; ``fail`` erzwingt Fehler je Adresse."""

    public_key = "test"

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any], int]] = []
        self.fail: dict[str, Exception] = {}

    def send(self, target: Target, message: dict[str, Any], ttl: int) -> None:
        if target.endpoint in self.fail:
            raise self.fail[target.endpoint]
        self.sent.append((target.endpoint, message, ttl))

    def bodies(self) -> list[str]:
        return [f"{m['title']}: {m['body']}" for _, m, _ in self.sent]


class FakeCalendar:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.calls: list[tuple[datetime, datetime]] = []

    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        self.calls.append((time_min, time_max))
        return self.events


def timed(eid: str, title: str, start: str, persons: str = "", created: str = LONG_AGO, **extra: Any) -> dict:
    begin = datetime.fromisoformat(start).replace(tzinfo=BERLIN)
    event = {"id": eid, "summary": title, "created": created,
             "start": {"dateTime": begin.isoformat(), "timeZone": "Europe/Berlin"},
             "end": {"dateTime": (begin + timedelta(hours=1)).isoformat(), "timeZone": "Europe/Berlin"}, **extra}
    if persons:
        event["extendedProperties"] = {"private": {"fkPersons": persons}}
    return event


def all_day(eid: str, title: str, first: str, last_excl: str, created: str = LONG_AGO) -> dict:
    return {"id": eid, "summary": title, "created": created, "start": {"date": first}, "end": {"date": last_excl}}


def subscribe(store, n: int = 1, email: str = LOCAL_USER, persons: list[str] | None = None,
              created: datetime = NOW - timedelta(days=30)) -> Subscription:
    _, p256dh, auth = browser_keys()
    return save_subscription(store, Subscription(
        endpoint=f"https://fcm.googleapis.com/fcm/send/{n}", p256dh=p256dh, auth=b64url(auth), email=email,
        persons=persons or [], created=created.timestamp()))


def run(store, settings, events, now=NOW, sender=None, calendars=None, allowed=lambda _e: True):
    sender = sender or FakeSender()
    calendar = FakeCalendar(events)
    stats = run_reminders(store, settings, now, sender, calendars or (lambda _e: calendar), allowed)
    return sender, stats


# ---------- Wann ----------

def test_eine_stunde_ein_tag_eine_woche_vorher(store, settings):
    subscribe(store)
    events = [timed("a", "Fußball", "2026-11-03T15:00", "lena", location="Sportplatz"),
              timed("b", "Zahnarzt", "2026-11-04T14:00", "max"),
              timed("c", "Elternabend", "2026-11-10T14:00")]
    sender, stats = run(store, settings, events)
    assert sorted(sender.bodies()) == [
        "Elternabend: Di. 10. Nov., 14:00 Uhr",
        "Fußball: Heute, 15:00 Uhr · Lena · Sportplatz",
        "Zahnarzt: Morgen, 14:00 Uhr · Max",
    ]
    assert stats["sent"] == 3
    ttl = {m["title"]: t for _, m, t in sender.sent}
    assert ttl["Fußball"] == 3600 and ttl["Zahnarzt"] == 24 * 3600
    # Kennung je Termin: Die Erinnerung „1 Tag“ ersetzt auf dem Handy die von „1 Woche“
    assert {m["tag"] for _, m, _ in sender.sent} == {"termin-a", "termin-b", "termin-c"}


def test_nichts_doppelt_auch_bei_wiederholtem_lauf(store, settings):
    subscribe(store)
    events = [timed("a", "Fußball", "2026-11-03T15:00")]
    first, _ = run(store, settings, events)
    again, _ = run(store, settings, events)
    later, _ = run(store, settings, events, now=NOW + timedelta(minutes=5))
    assert len(first.sent) == 1 and again.sent == [] and later.sent == []


def test_erst_wenn_faellig(store, settings):
    subscribe(store)
    events = [timed("a", "Fußball", "2026-11-03T15:10")]
    assert run(store, settings, events)[0].sent == []
    assert run(store, settings, events, now=NOW + timedelta(minutes=9))[0].sent == []
    assert len(run(store, settings, events, now=NOW + timedelta(minutes=10))[0].sent) == 1


def test_ganztaegig_ab_9_uhr(store, settings):
    subscribe(store)
    events = [all_day("g", "Omas Geburtstag", "2026-11-04", "2026-11-05")]
    at_9 = datetime(2026, 11, 3, 9, 0, tzinfo=BERLIN)
    assert run(store, settings, events, now=at_9 - timedelta(minutes=1))[0].sent == []
    assert run(store, settings, events, now=at_9)[0].bodies() == ["Omas Geburtstag: Morgen"]
    # „1 Stunde vorher“ = 8 Uhr am Tag selbst
    assert run(store, settings, events, now=datetime(2026, 11, 4, 8, 0, tzinfo=BERLIN))[0].bodies() == \
        ["Omas Geburtstag: Heute"]


def test_mehrtaegig_ganztaegig(store, settings):
    subscribe(store)
    events = [all_day("f", "Herbstferien", "2026-11-10", "2026-11-14")]
    sender, _ = run(store, settings, events, now=datetime(2026, 11, 3, 9, 0, tzinfo=BERLIN))
    assert sender.bodies() == ["Herbstferien: Di. 10. Nov. bis Fr. 13. Nov."]


def test_verpasste_laeufe_hoechstens_zwei_stunden_nachholen(store, settings):
    subscribe(store)
    events = [timed("a", "Training", "2026-11-04T12:30"),  # 1 Tag vorher war 12:30 – vor 1,5 Std
              timed("b", "Chor", "2026-11-04T11:30")]  # 11:30 – vor 2,5 Std: zu alt
    assert run(store, settings, events)[0].bodies() == ["Training: Morgen, 12:30 Uhr"]


def test_keine_erinnerung_nach_beginn(store, settings):
    subscribe(store)
    events = [timed("a", "Läuft schon", "2026-11-03T14:00")]  # 1 Std vorher = 13:00, aber Beginn = jetzt
    assert run(store, settings, events)[0].sent == []


def test_termin_angelegt_nachdem_die_erinnerung_faellig_war(store, settings):
    subscribe(store)
    # um 13:50 angelegt, beginnt 14:30: „1 Stunde vorher“ wäre 13:30 gewesen – kommt nicht nachträglich
    events = [timed("a", "Spontan", "2026-11-03T14:30", created="2026-11-03T12:50:00.000Z")]
    assert run(store, settings, events)[0].sent == []


def test_geraet_bekommt_nichts_von_vor_dem_einschalten(store, settings):
    subscribe(store, created=NOW - timedelta(minutes=1))
    events = [timed("a", "Fußball", "2026-11-03T14:58"),  # fällig 13:58, Gerät seit 13:59
              timed("b", "Klavier", "2026-11-03T15:00")]  # fällig 14:00
    assert run(store, settings, events)[0].bodies() == ["Klavier: Heute, 15:00 Uhr"]


# ---------- An wen ----------

def test_geraet_nur_fuer_bestimmte_personen(store, settings):
    subscribe(store, 1, persons=["max"])
    subscribe(store, 2)
    events = [timed("a", "Fußball", "2026-11-03T15:00", "lena"),
              timed("b", "Zahnarzt", "2026-11-03T15:00", "max,lena"),
              timed("c", "Grillen", "2026-11-03T15:00")]  # ohne Person: Familientermin
    sender, _ = run(store, settings, events)
    by_device: dict[str, set[str]] = {}
    for endpoint, msg, _ in sender.sent:
        by_device.setdefault(endpoint[-1], set()).add(msg["title"])
    assert by_device == {"1": {"Zahnarzt", "Grillen"}, "2": {"Fußball", "Zahnarzt", "Grillen"}}


def test_je_konto_der_eigene_kalenderzugang(store, settings):
    subscribe(store, 1, email="mama@example.com")
    subscribe(store, 2, email="papa@example.com")
    subscribe(store, 3, email="fremd@example.com")
    calendars = {"mama@example.com": FakeCalendar([timed("a", "Yoga", "2026-11-03T15:00")]),
                 "papa@example.com": FakeCalendar([timed("b", "Squash", "2026-11-03T15:00")])}
    sender, stats = run(store, settings, [], calendars=calendars.__getitem__,
                        allowed=lambda e: e != "fremd@example.com")
    assert sorted((e[-1], m["title"]) for e, m, _ in sender.sent) == [("1", "Yoga"), ("2", "Squash")]
    assert stats["skipped_users"] == 1
    # Abfragezeitraum deckt die längste Vorlaufzeit ab (1 Woche)
    time_min, time_max = calendars["mama@example.com"].calls[0]
    assert time_min < NOW and time_max >= NOW + timedelta(days=7, hours=2)


def test_abgelaufene_anmeldung_bremst_die_anderen_nicht(store, settings):
    subscribe(store, 1, email="mama@example.com")
    subscribe(store, 2, email="papa@example.com")

    class Expired:
        def list_events(self, *_):
            raise ReauthRequired()

    ok = FakeCalendar([timed("b", "Squash", "2026-11-03T15:00")])
    sender, stats = run(store, settings, [], calendars=lambda e: Expired() if e.startswith("mama") else ok)
    assert sender.bodies() == ["Squash: Heute, 15:00 Uhr"] and stats["skipped_users"] == 1


# ---------- Fehler beim Versand ----------

def test_beendetes_abo_wird_entfernt(store, settings):
    gone = subscribe(store, 1)
    subscribe(store, 2)
    sender = FakeSender()
    sender.fail[gone.endpoint] = PushGone()
    events = [timed("a", "Fußball", "2026-11-03T15:00"), timed("b", "Klavier", "2026-11-03T15:00")]
    _, stats = run(store, settings, events, sender=sender)
    assert stats == {"sent": 2, "failed": 0, "removed": 1, "skipped_users": 0}
    assert [s.endpoint[-1] for s in list_subscriptions(store)] == ["2"]


def test_stoerung_wird_im_naechsten_lauf_nachgeholt(store, settings):
    sub = subscribe(store)
    sender = FakeSender()
    sender.fail[sub.endpoint] = PushFailed("503")
    events = [timed("a", "Fußball", "2026-11-03T15:00")]
    assert run(store, settings, events, sender=sender)[1]["failed"] == 1
    sender.fail.clear()
    run(store, settings, events, sender=sender, now=NOW + timedelta(minutes=5))
    assert sender.bodies() == ["Fußball: Heute, 15:00 Uhr"]


# ---------- Einstellungen, Sprache, Aufräumen ----------

def test_vorlaufzeiten_aus_den_einstellungen(store, settings):
    subscribe(store)
    # um 13:55 angelegt: „1 Stunde vorher“ (13:15) war schon vorbei, „15 Minuten vorher“ ist jetzt fällig
    events = [timed("a", "Fußball", "2026-11-03T14:15", created="2026-11-03T12:55:00.000Z")]
    assert run(store, settings, events)[0].sent == []
    settings.reminder_offsets_min = [15]
    assert len(run(store, settings, events)[0].sent) == 1
    settings.reminder_offsets_min = []
    assert run(store, settings, [timed("b", "Klavier", "2026-11-03T15:00")])[0].sent == []


def test_englisch(store, settings):
    subscribe(store)
    settings.language = "en"
    events = [timed("a", "Football", "2026-11-03T15:00", "lena"), timed("c", "Parents' evening", "2026-11-10T14:00")]
    assert sorted(run(store, settings, events)[0].bodies()) == [
        "Football: Today, 15:00 · Lena", "Parents' evening: Tue 10 Nov, 14:00"]


def test_gemerkte_erinnerungen_werden_aufgeraeumt(store, settings):
    subscribe(store)
    run(store, settings, [timed("a", "Fußball", "2026-11-03T15:00")])
    assert len(store.get(SENT_PATH)["sent"]) == 1
    run(store, settings, [], now=NOW + timedelta(days=2))
    assert store.get(SENT_PATH)["sent"] == {}


# ---------- API ----------

def subscription_json(n: int = 1) -> dict[str, Any]:
    _, p256dh, auth = browser_keys()
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/{n}", "expirationTime": None,
            "keys": {"p256dh": p256dh, "auth": b64url(auth)}}


@pytest.fixture
def sender():
    fake = FakeSender()
    main.app.dependency_overrides[main.push_dep] = lambda: fake
    return fake


def test_schluessel_fuer_den_browser_bleibt_gleich(client):
    key = client.get("/api/push").json()["key"]
    assert len(b64url_decode(key)) == 65 and b64url_decode(key)[0] == 4
    assert client.get("/api/push").json()["key"] == key


def test_abo_anlegen_personen_behalten(client, store):
    sub = subscription_json()
    assert client.post("/api/push/subscribe", json=sub | {"persons": ["lena", "gibts-nicht"]}).json() == \
        {"persons": ["lena"]}
    created = list_subscriptions(store)[0].created
    # Abgleich beim Start der App: ohne Personen → Auswahl und Zeitpunkt bleiben
    assert client.post("/api/push/subscribe", json=sub).json() == {"persons": ["lena"]}
    assert list_subscriptions(store)[0].created == created
    assert client.post("/api/push/subscribe", json=sub | {"persons": []}).json() == {"persons": []}
    assert client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]}).json() == {"ok": True}
    assert list_subscriptions(store) == []


def test_abo_pruefen(client):
    sub = subscription_json()
    assert client.post("/api/push/subscribe", json=sub | {"endpoint": "http://intern/x"}).status_code == 422
    bad = sub | {"keys": {"p256dh": b64url(b"\x04" + b"\x00" * 64), "auth": "x"}}
    assert client.post("/api/push/subscribe", json=bad).status_code == 422


def test_testnachricht(client, store, sender):
    sub = subscription_json()
    client.post("/api/push/subscribe", json=sub)
    assert client.post("/api/push/test", json={"endpoint": sub["endpoint"]}).status_code == 200
    (endpoint, msg, _), = sender.sent
    assert endpoint == sub["endpoint"] and msg["title"] == "Familienkalender"
    assert "1 Woche, 1 Tag und 1 Stunde vor jedem Termin" in msg["body"]
    assert client.post("/api/push/test", json={"endpoint": "https://fcm.googleapis.com/x"}).status_code == 404
    sender.fail[sub["endpoint"]] = PushGone()
    resp = client.post("/api/push/test", json={"endpoint": sub["endpoint"]})
    assert resp.status_code == 410 and resp.json()["code"] == "push_gone"
    assert list_subscriptions(store) == []


def test_einstellungen_vorlaufzeiten(client):
    settings = client.get("/api/settings").json()
    assert settings["reminder_offsets_min"] == [10080, 1440, 60]
    saved = client.put("/api/settings", json=settings | {"reminder_offsets_min": [60, 15, 60]}).json()
    assert saved["reminder_offsets_min"] == [60, 15]
    assert client.put("/api/settings", json=settings | {"reminder_offsets_min": [1]}).status_code == 422
    assert client.put("/api/settings", json=settings | {"reminder_offsets_min": []}).json()["reminder_offsets_min"] \
        == []


def test_abnahme_termin_anlegen_handy_erinnert_einen_tag_vorher(client, sender):
    # Der lokale Kalender stempelt „created“ mit der echten Uhr – deshalb relativ zu jetzt rechnen
    start = (datetime.now(BERLIN) + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
    draft = {"title": "Zahnarzt", "all_day": False, "start_date": start.date().isoformat(), "start_time": "10:00",
             "end_date": None, "end_time": None, "location": "Praxis Dr. Weiß", "description": "",
             "persons": ["max"], "tags": ["arzt"], "recurrence": None, "uncertain": [], "hint": ""}
    assert client.post("/api/events", json={"events": [draft]}).status_code == 200
    client.post("/api/push/subscribe", json=subscription_json())

    main.app.dependency_overrides[main.now_dep] = lambda: start - timedelta(days=1, minutes=1)
    assert client.post("/api/cron/reminders").json()["sent"] == 0
    main.app.dependency_overrides[main.now_dep] = lambda: start - timedelta(days=1) + timedelta(minutes=3)
    assert client.post("/api/cron/reminders").json()["sent"] == 1
    assert sender.bodies() == ["Zahnarzt: Morgen, 10:00 Uhr · Max · Praxis Dr. Weiß"]
    assert client.post("/api/cron/reminders").json()["sent"] == 0


def test_erinnerungslauf_nur_mit_geheimnis(client, sender, monkeypatch):
    monkeypatch.setattr(main, "cfg", dataclasses.replace(main.cfg, cron_secret="geheim"))
    assert client.post("/api/cron/reminders").status_code == 403
    assert client.post("/api/cron/reminders", headers={"X-Kalender-Cron": "falsch"}).status_code == 403
    assert client.post("/api/cron/reminders", headers={"X-Kalender-Cron": "geheim"}).status_code == 200
    # in der Cloud ohne Geheimnis: abgeschaltet statt offen
    monkeypatch.setattr(main, "cfg", dataclasses.replace(main.cfg, cron_secret="", backend="cloud"))
    assert client.post("/api/cron/reminders").status_code == 503
