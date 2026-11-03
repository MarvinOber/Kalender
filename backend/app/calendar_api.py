"""Google Calendar API v3 direkt über REST (kein SDK) – und eine lokale Attrappe für den Betrieb ohne Anmeldung."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .docstore import DocStore
from .errors import CalendarError, ReauthRequired

API = "https://www.googleapis.com/calendar/v3"
EVENT_GONE = "Termin nicht gefunden – vielleicht wurde er inzwischen gelöscht."


class CalendarClient(Protocol):
    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]: ...
    def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]: ...
    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def patch_event(self, calendar_id: str, event_id: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def delete_event(self, calendar_id: str, event_id: str) -> None: ...
    def list_calendars(self) -> list[dict[str, Any]]: ...


def merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Wie ``events.patch`` bei Google: Objekte zusammenführen, ``None`` löscht ein Feld, Listen ersetzen."""
    out = dict(target)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict):
            out[key] = merge_patch(out[key] if isinstance(out.get(key), dict) else {}, value)
        else:
            out[key] = value
    return out


def _event_path(calendar_id: str, event_id: str = "") -> str:
    path = f"/calendars/{quote(calendar_id, safe='')}/events"
    return f"{path}/{quote(event_id, safe='')}" if event_id else path


class GoogleCalendar:
    """``token`` liefert ein gültiges Zugriffstoken (erneuert es bei Bedarf über das Refresh-Token)."""

    def __init__(self, token: Callable[[], str], client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(timeout=20)

    def _request(self, method: str, path: str, not_found: str = "", **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            resp = self._client.request(method, API + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise CalendarError("Google Calendar ist gerade nicht erreichbar.") from exc
        if resp.status_code == 401:
            raise ReauthRequired()
        if not_found and resp.status_code in (404, 410):
            raise CalendarError(not_found, 404)
        if resp.status_code in (403, 404):
            reason = _reason(resp)
            if reason in ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"):
                raise CalendarError("Google Calendar ist kurz überlastet. Bitte gleich noch einmal.", 503)
            raise CalendarError(
                "Kalender nicht gefunden oder keine Schreibrechte. Kalender-ID in den Einstellungen prüfen.", 400)
        if resp.status_code >= 400:
            raise CalendarError(f"Google Calendar meldet Fehler {resp.status_code}.")
        return resp.json() if resp.content else {}

    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": 250,
        }
        while True:
            data = self._request("GET", _event_path(calendar_id), params=params)
            items += [e for e in data.get("items", []) if e.get("status") != "cancelled"]
            if not data.get("nextPageToken"):
                return items
            params["pageToken"] = data["nextPageToken"]

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        event = self._request("GET", _event_path(calendar_id, event_id), not_found=EVENT_GONE)
        if event.get("status") == "cancelled":
            raise CalendarError(EVENT_GONE, 404)
        return event

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", _event_path(calendar_id), json=body)

    def patch_event(self, calendar_id: str, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", _event_path(calendar_id, event_id), not_found=EVENT_GONE, json=body)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._request("DELETE", _event_path(calendar_id, event_id), not_found=EVENT_GONE)

    def list_calendars(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/users/me/calendarList", params={"minAccessRole": "writer"})
        return [{"id": c["id"], "summary": c.get("summaryOverride") or c.get("summary") or c["id"],
                 "primary": bool(c.get("primary"))} for c in data.get("items", [])]


def _reason(resp: httpx.Response) -> str:
    try:
        return resp.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


class LocalCalendar:
    """Attrappe für ``KALENDER_AUTH=none``: Termine im lokalen Dokumentenspeicher, Serien nur als erster Termin."""

    PATH = "local/calendar"

    def __init__(self, store: DocStore) -> None:
        self._store = store

    def _events(self) -> list[dict[str, Any]]:
        return (self._store.get(self.PATH) or {}).get("events", [])

    def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        def bounds(e: dict[str, Any]) -> tuple[datetime, datetime]:
            s, n = e["start"], e["end"]
            tz = time_min.tzinfo
            if "date" in s:
                return (datetime.fromisoformat(s["date"]).replace(tzinfo=tz),
                        datetime.fromisoformat(n["date"]).replace(tzinfo=tz))
            return (datetime.fromisoformat(s["dateTime"]).replace(tzinfo=tz),
                    datetime.fromisoformat(n["dateTime"]).replace(tzinfo=tz))

        hits = [e for e in self._events() if bounds(e)[0] < time_max and bounds(e)[1] > time_min]
        return sorted(hits, key=lambda e: bounds(e)[0])

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        for event in self._events():
            if event["id"] == event_id:
                return event
        raise CalendarError(EVENT_GONE, 404)

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        event = {**body, "id": uuid.uuid4().hex, "htmlLink": ""}
        self._store.set(self.PATH, {"events": [*self._events(), event]})
        return event

    def patch_event(self, calendar_id: str, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        updated = merge_patch(self.get_event(calendar_id, event_id), body)
        self._store.set(self.PATH, {"events": [updated if e["id"] == event_id else e for e in self._events()]})
        return updated

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.get_event(calendar_id, event_id)
        self._store.set(self.PATH, {"events": [e for e in self._events() if e["id"] != event_id]})

    def list_calendars(self) -> list[dict[str, Any]]:
        return [{"id": "primary", "summary": "Lokaler Testkalender", "primary": True}]
