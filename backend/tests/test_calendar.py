"""Schreiben in den Kalender: Google-Body, REST-Aufrufe gegen eine Attrappe der Calendar API, Rückweg zur Anzeige."""

from __future__ import annotations

import json
from datetime import date, datetime, time

import httpx
import pytest

from app.calendar_api import GoogleCalendar, merge_patch
from app.errors import CalendarError, ReauthRequired
from app.events import (
    EventDraft,
    Recurrence,
    from_google,
    parse_recurrence,
    to_draft,
    to_google,
    to_google_patch,
    validate_draft,
)

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
        if parts[-2] == "events":  # /calendars/<id>/events/<eventId>
            return self._single(request, parts[-3], parts[-1])
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

    def _single(self, request: httpx.Request, cal: str, event_id: str) -> httpx.Response:
        items = self.events.get(cal, [])
        idx = next((i for i, e in enumerate(items) if e["id"] == event_id), None)
        if idx is None:
            return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
        if request.method == "GET":
            return httpx.Response(200, json=items[idx])
        if request.method == "PATCH":
            items[idx] = merge_patch(items[idx], json.loads(request.content))
            return httpx.Response(200, json=items[idx])
        assert request.method == "DELETE"
        del items[idx]
        return httpx.Response(204)


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


# ---------- Bearbeiten und Löschen ----------

def test_rueckweg_in_den_dialog(settings):
    """Was der Dialog anlegt, kommt beim Bearbeiten unverändert wieder heraus."""
    drafts = [
        fussball(),
        EventDraft(title="Party", start_date=date(2026, 11, 7), start_time=time(22, 0), end_date=date(2026, 11, 8),
                   end_time=time(1, 0), location="Garten", description="Grill", persons=["mama", "papa"]),
        EventDraft(title="Ferien", all_day=True, start_date=date(2026, 12, 21), end_date=date(2027, 1, 2),
                   tags=["freizeit"]),
        EventDraft(title="Schwimmen", start_date=date(2026, 11, 3), start_time=time(17, 0), end_time=time(18, 0),
                   recurrence=Recurrence(freq="weekly", interval=2, by_day=["TU"], until=date(2027, 3, 30))),
    ]
    for draft in drafts:
        event = {**to_google(draft, settings), "id": "x"}
        back, editable = to_draft(event, settings)
        expected = draft.model_copy(update={"end_time": draft.end_time or time(17, 0)} if draft is drafts[0] else {})
        assert back == expected and editable


def test_wiederholung_nicht_abbildbar():
    berlin = BERLIN
    assert parse_recurrence([], berlin) == (None, True)
    assert parse_recurrence(["RRULE:FREQ=MONTHLY;BYDAY=2TU"], berlin) == (None, False)
    assert parse_recurrence(["RRULE:FREQ=WEEKLY", "EXDATE:20261110T160000Z"], berlin) == (None, False)
    rec, ok = parse_recurrence(["RRULE:FREQ=YEARLY;COUNT=5"], berlin)
    assert ok and rec == Recurrence(freq="yearly", count=5)


def test_einzelner_termin_einer_serie_hat_keine_eigene_wiederholung(settings):
    instance = {"id": "s1_20261110", "recurringEventId": "s1", "summary": "Schwimmen",
                "start": {"dateTime": "2026-11-10T17:00:00+01:00"}, "end": {"dateTime": "2026-11-10T18:00:00+01:00"}}
    draft, editable = to_draft(instance, settings)
    assert draft.start_date == date(2026, 11, 10) and draft.recurrence is None and not editable


def test_bearbeiten_ueber_rest(gcal, server, settings):
    created = gcal.insert_event("primary", to_google(fussball(), settings) | {"location": "Sportplatz"})
    server.events["primary"][0]["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]}
    draft, _ = to_draft(gcal.get_event("primary", created["id"]), settings)
    draft = draft.model_copy(update={"title": "Fußballturnier", "all_day": True, "start_time": None, "end_time": None,
                                     "location": "", "persons": ["lena", "max"]})
    updated = gcal.patch_event("primary", created["id"], to_google_patch(draft, settings, with_recurrence=True))

    req = server.requests[-1]
    assert req.method == "PATCH" and req.url.raw_path.decode().endswith("/calendars/primary/events/e1")
    sent = json.loads(req.content)
    assert sent["start"] == {"date": "2026-11-06", "dateTime": None, "timeZone": None}
    assert sent["location"] == "" and sent["recurrence"] == []
    assert "fkSource" not in sent["extendedProperties"]["private"]  # Herkunft bleibt
    # Bei Google: Felder zusammengeführt, alte Uhrzeit weg, Erinnerung und Herkunft erhalten
    assert updated["start"] == {"date": "2026-11-06"} and updated["end"] == {"date": "2026-11-07"}
    assert updated["reminders"]["overrides"][0]["minutes"] == 30
    assert updated["extendedProperties"]["private"]["fkSource"] == "sprache"
    view = from_google(updated, settings)
    assert (view.title, view.all_day, view.location, view.persons) == ("Fußballturnier", True, "", ["lena", "max"])


def test_loeschen_ueber_rest(gcal, server, settings):
    created = gcal.insert_event("primary", to_google(fussball(), settings))
    gcal.delete_event("primary", created["id"])
    assert server.requests[-1].method == "DELETE" and server.events["primary"] == []
    with pytest.raises(CalendarError, match="gelöscht") as exc:
        gcal.get_event("primary", created["id"])
    assert exc.value.status == 404
