"""Termine: Entwurf aus der Spracheingabe ↔ Google-Calendar-Eintrag ↔ Anzeige in der Wochenansicht.

Tags stehen zweimal im Google-Termin: maschinenlesbar in ``extendedProperties.private`` (Kennungen) und lesbar
als Block am Ende der Beschreibung (Namen), damit sie auch in der Google-Kalender-App zu sehen sind.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .settings import Settings

PROP_PERSONS = "fkPersons"
PROP_TAGS = "fkTags"
PROP_SOURCE = "fkSource"
TAG_BLOCK_MARK = "— Familienkalender —"
_TAG_BLOCK = re.compile(r"\n*" + re.escape(TAG_BLOCK_MARK) + r".*\Z", re.S)

Weekday = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
WEEKDAYS: list[str] = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class Recurrence(BaseModel):
    freq: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=99)
    by_day: list[Weekday] = Field(default_factory=list)  # nur wöchentlich: „jeden Dienstag und Donnerstag“
    until: date | None = None  # letzter Tag (einschließlich)
    count: int | None = Field(default=None, ge=1, le=999)


class EventDraft(BaseModel):
    """Ein erkannter oder bearbeiteter Termin, wie ihn der Bestätigungsdialog zeigt.

    ``end_date`` ist bei ganztägigen Terminen der letzte Tag *einschließlich* – Google erwartet den Folgetag,
    das rechnet ``to_google`` um. ``uncertain`` nennt Felder, die das Modell nicht sicher bestimmen konnte.
    """

    title: str = ""
    all_day: bool = False
    start_date: date | None = None
    start_time: time | None = None
    end_date: date | None = None
    end_time: time | None = None
    location: str = ""
    description: str = ""
    persons: list[str] = Field(default_factory=list)  # Kennungen aus settings.persons
    tags: list[str] = Field(default_factory=list)  # Kennungen aus settings.event_tags
    recurrence: Recurrence | None = None
    uncertain: list[str] = Field(default_factory=list)
    hint: str = ""  # kurze Erklärung des Modells zu unsicheren Feldern


class ViewEvent(BaseModel):
    """Ein Termin für die Wochenansicht; Zeiten als Wanduhrzeit in der eingestellten Zeitzone."""

    id: str
    title: str
    all_day: bool
    start: str  # ganztägig „YYYY-MM-DD“, sonst „YYYY-MM-DDTHH:MM“
    end: str  # ganztägig: Folgetag des letzten Tages (wie bei Google), sonst Ende
    location: str = ""
    description: str = ""
    persons: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    recurring: bool = False
    link: str = ""


class DraftError(ValueError):
    pass


def validate_draft(draft: EventDraft, settings: Settings) -> list[str]:
    """Fehler, die das Anlegen verhindern (deutsche Meldungen für den Dialog)."""
    errors: list[str] = []
    if not draft.title.strip():
        errors.append("Titel fehlt")
    if draft.start_date is None:
        errors.append("Datum fehlt")
    if not draft.all_day and draft.start_time is None:
        errors.append("Uhrzeit fehlt (oder „ganztägig“ wählen)")
    if errors:
        return errors
    if draft.all_day:
        if draft.end_date and draft.end_date < draft.start_date:
            errors.append("Ende liegt vor dem Beginn")
    else:
        start, end = timed_range(draft, settings)
        if end <= start:
            errors.append("Ende liegt vor dem Beginn")
    if draft.recurrence and draft.recurrence.until and draft.recurrence.until < draft.start_date:
        errors.append("Wiederholung endet vor dem ersten Termin")
    known_p = {p.id for p in settings.persons}
    known_t = {t.id for t in settings.event_tags}
    if unknown := [p for p in draft.persons if p not in known_p]:
        errors.append(f"Unbekannte Person: {', '.join(unknown)}")
    if unknown := [t for t in draft.tags if t not in known_t]:
        errors.append(f"Unbekannter Tag: {', '.join(unknown)}")
    return errors


def timed_range(draft: EventDraft, settings: Settings) -> tuple[datetime, datetime]:
    """Beginn und Ende als Wanduhrzeit; fehlt das Ende, gilt die Standarddauer."""
    assert draft.start_date and draft.start_time
    start = datetime.combine(draft.start_date, draft.start_time)
    if draft.end_time is not None:
        end = datetime.combine(draft.end_date or draft.start_date, draft.end_time)
        # „von 22 bis 1 Uhr“ ohne Enddatum: über Mitternacht
        if end <= start and draft.end_date is None:
            end += timedelta(days=1)
    else:
        end = start + timedelta(minutes=settings.default_duration_min)
    return start, end


def _names(ids: list[str], items: list[Any]) -> list[str]:
    by_id = {i.id: i.name for i in items}
    return [by_id.get(i, i) for i in ids]


def tag_block(persons: list[str], tags: list[str], settings: Settings) -> str:
    lines = []
    if persons:
        lines.append("Personen: " + ", ".join(_names(persons, settings.persons)))
    if tags:
        lines.append("Tags: " + ", ".join(_names(tags, settings.event_tags)))
    return f"{TAG_BLOCK_MARK}\n" + "\n".join(lines) if lines else ""


def strip_tag_block(description: str) -> str:
    return _TAG_BLOCK.sub("", description or "").rstrip()


def rrule(rec: Recurrence, all_day: bool, tz: ZoneInfo) -> str:
    parts = [f"FREQ={rec.freq.upper()}"]
    if rec.interval > 1:
        parts.append(f"INTERVAL={rec.interval}")
    if rec.freq == "weekly" and rec.by_day:
        parts.append("BYDAY=" + ",".join(d for d in WEEKDAYS if d in rec.by_day))
    if rec.count:
        parts.append(f"COUNT={rec.count}")
    elif rec.until:
        if all_day:
            parts.append(f"UNTIL={rec.until:%Y%m%d}")
        else:
            # Zeitbehaftete Serien verlangen UNTIL in UTC – Ende des letzten Tages in der Familien-Zeitzone
            last = datetime.combine(rec.until, time(23, 59, 59), tzinfo=tz).astimezone(ZoneInfo("UTC"))
            parts.append(f"UNTIL={last:%Y%m%dT%H%M%SZ}")
    return "RRULE:" + ";".join(parts)


def to_google(draft: EventDraft, settings: Settings) -> dict[str, Any]:
    """Request-Body für ``events.insert`` der Google Calendar API v3."""
    if errors := validate_draft(draft, settings):
        raise DraftError("; ".join(errors))
    assert draft.start_date
    body: dict[str, Any] = {"summary": draft.title.strip()}
    if draft.all_day:
        last = draft.end_date or draft.start_date
        body["start"] = {"date": draft.start_date.isoformat()}
        body["end"] = {"date": (last + timedelta(days=1)).isoformat()}
    else:
        start, end = timed_range(draft, settings)
        body["start"] = {"dateTime": start.isoformat(timespec="seconds"), "timeZone": settings.timezone}
        body["end"] = {"dateTime": end.isoformat(timespec="seconds"), "timeZone": settings.timezone}
    if draft.location.strip():
        body["location"] = draft.location.strip()
    desc = draft.description.strip()
    block = tag_block(draft.persons, draft.tags, settings)
    if desc or block:
        body["description"] = "\n\n".join(x for x in (desc, block) if x)
    if draft.recurrence:
        body["recurrence"] = [rrule(draft.recurrence, draft.all_day, settings.tz)]
    body["extendedProperties"] = {"private": {
        PROP_PERSONS: ",".join(draft.persons),
        PROP_TAGS: ",".join(draft.tags),
        PROP_SOURCE: "sprache",
    }}
    return body


def _split(value: str | None) -> list[str]:
    return [x for x in (value or "").split(",") if x]


def _ids_from_block(description: str, label: str, items: list[Any]) -> list[str]:
    """Rückfall für Termine, deren Tags jemand in der Google-App von Hand in den Block geschrieben hat."""
    m = re.search(rf"^{label}:\s*(.+)$", description or "", re.M)
    if not m:
        return []
    by_name = {i.name.lower(): i.id for i in items}
    return [by_name[n.strip().lower()] for n in m.group(1).split(",") if n.strip().lower() in by_name]


def _persons_from_title(title: str, settings: Settings) -> list[str]:
    """Rückfall für fremd angelegte Termine: Personennamen als ganzes Wort im Titel („Lena Zahnarzt“)."""
    return [p.id for p in settings.persons if re.search(rf"\b{re.escape(p.name)}\b", title, re.I)]


def from_google(event: dict[str, Any], settings: Settings) -> ViewEvent:
    tz = settings.tz
    start, end = event.get("start", {}), event.get("end", {})
    all_day = "date" in start
    if all_day:
        s, e = start["date"], end.get("date") or start["date"]
    else:
        s_dt = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
        e_dt = datetime.fromisoformat(end.get("dateTime") or start["dateTime"]).astimezone(tz)
        s, e = s_dt.strftime("%Y-%m-%dT%H:%M"), e_dt.strftime("%Y-%m-%dT%H:%M")
    title = event.get("summary") or "(ohne Titel)"
    raw_desc = event.get("description") or ""
    private = (event.get("extendedProperties") or {}).get("private") or {}
    if PROP_PERSONS in private or PROP_TAGS in private:
        persons, tags = _split(private.get(PROP_PERSONS)), _split(private.get(PROP_TAGS))
    else:
        persons = _ids_from_block(raw_desc, "Personen", settings.persons) or _persons_from_title(title, settings)
        tags = _ids_from_block(raw_desc, "Tags", settings.event_tags)
    return ViewEvent(
        id=event.get("id", ""),
        title=title,
        all_day=all_day,
        start=s,
        end=e,
        location=event.get("location") or "",
        description=strip_tag_block(raw_desc),
        persons=persons,
        tags=tags,
        recurring=bool(event.get("recurringEventId") or event.get("recurrence")),
        link=event.get("htmlLink") or "",
    )
