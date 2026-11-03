"""Schreiben in den Kalender: Google-Body, REST-Aufrufe gegen eine Attrappe der Calendar API, Rückweg zur Anzeige."""

from __future__ import annotations

import json
from datetime import date, datetime, time

import httpx
import pytest

from app.calendar_api import GoogleCalendar
from app.errors import CalendarError, ReauthRequired
from app.events import EventDraft, Recurrence, from_google, to_google, validate_draft

from .conftest import BERLIN


class FakeGoogleCalendarServer:
    """Attrappe der Google Calendar API v3 für ``httpx.MockTransport`` – speichert Termine wie Google."""

    def __init__(self, page_size: int = 2) -> None:
        self.events: dict[str, list[dict]] = {}
        self.requests: list[httpx.Request] = []
        self.page_size = page_size
        self.status: int | None = None  # erzwungene Antwort (Fehlerfälle)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status:
            return httpx.Response(self.status, json={"error": {"errors": [{"reason": "notFound"}]}})
        assert request.headers["Authorization"] == "Bearer tok-1"
        parts = request.url.path.split("/")  # /calendar/v3/calendars/<id>/events
        if parts[-1] == "calendarList":
            return httpx.Response(200, json={"items": [
                {"id": "familie@group.calendar.google.com", "summary": "Familie"},
                {"id": "ich@example.com", "summary": "ich@example.com", "primary": True}]})
        cal = parts[-2]
        if request.method == "POST":
            body = json.loads(request.content)
            event = {**body, "id": f"e{sum(map(len, self.events.values())) + 1}", "htmlLink": "https://cal/x"}
            self.events.setdefault(cal, []).append(event)
            return httpx.Response(200, json=event)
        items = self.events.get(cal, [])
        offset = int(request.url.params.get("pageToken", "0"))
        page = items[offset:offset + self.page_size]
        data: dict = {"items": page}
        if offset + self.page_size < len(items):
            data["nextPageToken"] = str(offset + self.page_size)
        return httpx.Response(200, json=data)


@pytest.fixture
def server():
    return FakeGoogleCalendarServer()


@pytest.fixture
def gcal(server):
    return GoogleCalendar(lambda: "tok-1", httpx.Client(transport=httpx.MockTransport(server)))


def fussball() -> EventDraft:
    return EventDraft(title="Fußball", start_date=date(2026, 11, 6), start_time=time(16, 0),
                      persons=["lena"], tags=["sport"])


def test_zeittermin_mit_standarddauer_und_tags(settings):
    body = to_google(fussball(), settings)
    assert body["summary"] == "Fußball"
    assert body["start"] == {"dateTime": "2026-11-06T16:00:00", "timeZone": "Europe/Berlin"}
    assert body["end"] == {"dateTime": "2026-11-06T17:00:00", "timeZone": "Europe/Berlin"}
    assert body["extendedProperties"]["private"] == {"fkPersons": "lena", "fkTags": "sport", "fkSource": "sprache"}
    assert body["description"] == "— Familienkalender —\nPersonen: Lena\nTags: Sport"


def test_ganztaegig_ende_ist_folgetag(settings):
    draft = EventDraft(title="Omas Geburtstag", all_day=True, start_date=date(2026, 11, 7), tags=["geburtstag"],
                       description="Kuchen mitbringen")
    body = to_google(draft, settings)
    assert body["start"] == {"date": "2026-11-07"} and body["end"] == {"date": "2026-11-08"}
    assert body["description"].startswith("Kuchen mitbringen\n\n— Familienkalender —\nTags: Geburtstag")
    assert "Personen" not in body["description"]


def test_ueber_mitternacht_und_dauer(settings):
    draft = EventDraft(title="Party", start_date=date(2026, 11, 7), start_time=time(22, 0), end_time=time(1, 0))
    assert to_google(draft, settings)["end"]["dateTime"] == "2026-11-08T01:00:00"
    settings.default_duration_min = 90
    draft = EventDraft(title="Arzt", start_date=date(2026, 11, 7), start_time=time(9, 0))
    assert to_google(draft, settings)["end"]["dateTime"] == "2026-11-07T10:30:00"


def test_wiederholung_als_rrule(settings):
    draft = fussball()
    draft.recurrence = Recurrence(freq="weekly", by_day=["FR", "TU"], until=date(2026, 12, 24))
    # Ende des 24.12. in Berlin = 22:59:59 UTC; Wochentage in Kalenderreihenfolge
    assert to_google(draft, settings)["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU,FR;UNTIL=20261224T225959Z"]
    allday = EventDraft(title="Geburtstag Lena", all_day=True, start_date=date(2027, 3, 1),
                        recurrence=Recurrence(freq="yearly"))
    assert to_google(allday, settings)["recurrence"] == ["RRULE:FREQ=YEARLY"]


def test_unvollstaendiger_entwurf_wird_abgelehnt(settings):
    draft = EventDraft(title="Elternabend", start_date=date(2026, 11, 10))
    assert validate_draft(draft, settings) == ["Uhrzeit fehlt (oder „ganztägig“ wählen)"]
    draft = EventDraft(title="X", start_date=date(2026, 11, 10), start_time=time(9), persons=["oma"])
    assert validate_draft(draft, settings) == ["Unbekannte Person: oma"]


def test_anlegen_ueber_rest(gcal, server, settings):
    created = gcal.insert_event("familie@group.calendar.google.com", to_google(fussball(), settings))
    req = server.requests[-1]
    assert req.method == "POST"
    assert req.url.raw_path.decode() == "/calendar/v3/calendars/familie%40group.calendar.google.com/events"
    sent = json.loads(req.content)
    assert sent["extendedProperties"]["private"]["fkPersons"] == "lena"
    view = from_google(created, settings)
    assert (view.title, view.persons, view.tags, view.start) == ("Fußball", ["lena"], ["sport"], "2026-11-06T16:00")


def test_lesen_mit_seiten_und_ohne_abgesagte(gcal, server, settings):
    for i in range(4):
        gcal.insert_event("primary", to_google(fussball(), settings) | {"summary": f"T{i}"})
    server.events["primary"][1]["status"] = "cancelled"
    items = gcal.list_events("primary", datetime(2026, 11, 2, tzinfo=BERLIN), datetime(2026, 11, 9, tzinfo=BERLIN))
    assert [e["summary"] for e in items] == ["T0", "T2", "T3"]
    first = server.requests[-2].url.params
    assert first["singleEvents"] == "true" and first["timeMin"] == "2026-11-02T00:00:00+01:00"


def test_kalenderliste(gcal):
    cals = gcal.list_calendars()
    assert cals[0] == {"id": "familie@group.calendar.google.com", "summary": "Familie", "primary": False}


def test_fehlerfaelle(gcal, server):
    server.status = 401
    with pytest.raises(ReauthRequired):
        gcal.list_calendars()
    server.status = 404
    with pytest.raises(CalendarError, match="Kalender-ID"):
        gcal.insert_event("falsch", {"summary": "x"})


def test_fremder_termin_mit_dateTime_und_tagblock(settings):
    """Von Hand in der Google-App angelegt: Tags nur in der Beschreibung, Zeit mit Versatz in UTC."""
    event = {"id": "g1", "summary": "Zahnarzt", "start": {"dateTime": "2026-11-05T14:00:00Z"},
             "end": {"dateTime": "2026-11-05T15:00:00Z"},
             "description": "Karte mitnehmen\n\n— Familienkalender —\nPersonen: Mama, Oma\nTags: Arzt"}
    view = from_google(event, settings)
    assert (view.start, view.end) == ("2026-11-05T15:00", "2026-11-05T16:00")
    assert view.persons == ["mama"] and view.tags == ["arzt"]
    assert view.description == "Karte mitnehmen"


def test_fremder_termin_person_im_titel(settings):
    event = {"id": "g2", "summary": "Lena Klavier", "start": {"date": "2026-11-05"}, "end": {"date": "2026-11-06"}}
    view = from_google(event, settings)
    assert view.all_day and view.persons == ["lena"] and view.tags == []
