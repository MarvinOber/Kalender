"""Termin-Erkennung: Transkript → strukturierte Termine (JSON-Schema über OpenRouter) → geprüfte Entwürfe.

Das Modell bekommt das heutige Datum in der Familien-Zeitzone und eine Tabelle der nächsten Wochen mit
Wochentagen – „nächsten Dienstag“ oder „übermorgen“ muss es dann nicht selbst ausrechnen, nur nachschlagen.
Personen und Ereignis-Tags sind im Schema als feste Liste vorgegeben; was das Modell trotzdem Fremdes
liefert, fällt in ``normalize`` heraus. Fehlt eine Angabe, wird das Feld markiert statt geraten.

Fotos (Kalenderseite, Terminzettel, Brief) gehen mit demselben Kontext an ein Bildmodell; es liefert zusätzlich
eine kurze Abschrift (``text``), die der Dialog zeigt und die sich bearbeitet neu erkennen lässt.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from pydantic import ValidationError

from .events import WEEKDAYS, EventDraft, Recurrence
from .openrouter import LlmClient
from .settings import Settings

FIELDS = ["title", "start_date", "start_time", "end_date", "end_time", "location", "persons", "tags", "recurrence"]
WEEKDAY_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
LOOKAHEAD_DAYS = 70


def _nullable(t: str, **extra: Any) -> dict[str, Any]:
    return {"type": [t, "null"], **extra}


def _id_list(ids: list[str]) -> dict[str, Any]:
    if not ids:
        return {"type": "array", "items": {"type": "string"}, "maxItems": 0}
    return {"type": "array", "items": {"type": "string", "enum": ids}}


def build_schema(settings: Settings, with_text: bool = False) -> dict[str, Any]:
    recurrence = {
        "type": ["object", "null"],
        "properties": {
            "freq": {"type": "string", "enum": ["daily", "weekly", "monthly", "yearly"]},
            "interval": {"type": "integer"},
            "by_day": {"type": "array", "items": {"type": "string", "enum": WEEKDAYS}},
            "until": _nullable("string", description="letzter Tag YYYY-MM-DD"),
            "count": _nullable("integer"),
        },
        "required": ["freq", "interval", "by_day", "until", "count"],
        "additionalProperties": False,
    }
    event = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "all_day": {"type": "boolean"},
            "start_date": _nullable("string", description="YYYY-MM-DD"),
            "start_time": _nullable("string", description="HH:MM, 24 Stunden"),
            "end_date": _nullable("string", description="YYYY-MM-DD, bei ganztägig letzter Tag einschließlich"),
            "end_time": _nullable("string", description="HH:MM, nur wenn genannt"),
            "location": {"type": "string"},
            "description": {"type": "string"},
            "persons": _id_list([p.id for p in settings.persons]),
            "tags": _id_list([t.id for t in settings.event_tags]),
            "recurrence": recurrence,
            "uncertain": {"type": "array", "items": {"type": "string", "enum": FIELDS}},
            "hint": {"type": "string"},
        },
        "required": ["title", "all_day", "start_date", "start_time", "end_date", "end_time", "location",
                     "description", "persons", "tags", "recurrence", "uncertain", "hint"],
        "additionalProperties": False,
    }
    if with_text:
        # Abschrift zuerst: Das Modell liest erst ab und ordnet dann zu
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}, "events": {"type": "array", "items": event}},
            "required": ["text", "events"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {"events": {"type": "array", "items": event}},
        "required": ["events"],
        "additionalProperties": False,
    }


def _date_table(today: date) -> str:
    rows = []
    for i in range(LOOKAHEAD_DAYS):
        d = today + timedelta(days=i)
        label = " (heute)" if i == 0 else " (morgen)" if i == 1 else " (übermorgen)" if i == 2 else ""
        rows.append(f"{WEEKDAY_DE[d.weekday()]} {d.isoformat()}{label}")
    return "\n".join(rows)


def _context(settings: Settings, now: datetime) -> str:
    """Heute, Datumstabelle, Personen und Tags – gleich für Sprache, Text und Foto."""
    now = now.astimezone(settings.tz)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    persons = "\n".join(
        f'- id "{p.id}": {p.name}' + (f" (auch: {', '.join(p.aliases)})" if p.aliases else "")
        for p in settings.persons) or "- (keine)"
    tags = "\n".join(
        f'- id "{t.id}": {t.name}' + (f" (z. B. {', '.join(t.aliases)})" if t.aliases else "")
        for t in settings.event_tags) or "- (keine)"
    return f"""\
Jetzt ist {WEEKDAY_DE[today.weekday()]}, {today.isoformat()}, {now:%H:%M} Uhr (Zeitzone {settings.timezone}).
Diese Woche geht von Montag {week_start.isoformat()} bis Sonntag {(week_start + timedelta(days=6)).isoformat()}.

Kalender zum Nachschlagen (Wochentag und Datum):
{_date_table(today)}

Familienmitglieder (Feld "persons", nur diese ids):
{persons}

Ereignis-Tags (Feld "tags", nur diese ids):
{tags}"""


def _lang(settings: Settings) -> str:
    return "Deutsch" if settings.language == "de" else "Englisch"


def build_messages(text: str, settings: Settings, now: datetime) -> list[dict[str, Any]]:
    system = f"""Du trägst Termine in einen Familienkalender ein. Wandle die gesprochene Eingabe in Termine um.

{_context(settings, now)}

Regeln:
- Eine Eingabe kann mehrere Termine enthalten: für jeden Termin ein eigener Eintrag.
  Kein Termin erkennbar → leere Liste.
{_rules(_lang(settings))}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


PHOTO_REQUEST = "Lies die Termine von diesem Foto ab."


def build_photo_messages(image: bytes, mime: str, settings: Settings, now: datetime) -> list[dict[str, Any]]:
    lang = _lang(settings)
    system = f"""Du trägst Termine in einen Familienkalender ein. Lies die Termine von einem Foto ab – z. B. einer
Kalenderseite, einem Terminzettel (Arzt, Zahnarzt, Friseur), einem Brief oder Elternbrief, einer Einladung oder
einem Aushang.

{_context(settings, now)}

Regeln für das Foto:
- Jeden Termin auf dem Foto als eigenen Eintrag aufnehmen (jede Zeile eines Terminzettels, jeden Eintrag einer
  Kalenderseite). Kein Termin erkennbar → leere Liste.
- Termine, die vor heute liegen, weglassen.
- Datum ohne Jahr: Jahr aus dem Foto nehmen (Kalenderblatt, Datum des Briefs), sonst das nächste solche Datum ab heute.
- Kalenderseite: Ein Eintrag gehört zu dem Tag, in dessen Feld er steht; Monat und Jahr stehen meist oben.
- Passen Wochentag und Datum nicht zusammen: dem Datum folgen, "start_date" in "uncertain" und im hint nennen.
- Handschrift sorgfältig lesen. Unleserliches nicht raten: Feld in "uncertain" und im hint nennen.
- location: Name und Adresse von Praxis, Schule oder Veranstaltungsort, wenn angegeben.
- description: wichtige Hinweise vom Foto knapp übernehmen (z. B. "Versichertenkarte mitbringen",
  "Absagen bis 24 Std. vorher, Tel. …"), sonst "".
- persons: Namen auf dem Foto (Patient, Schülerin, Eingeladener) den Familienmitgliedern zuordnen.
- text: kurze Abschrift auf {lang} der Stellen, aus denen du die Termine gelesen hast, je Termin eine Zeile
  (z. B. "Do 12.11. 15:30 Kontrolle Zahnarzt, Max"), ohne Werbung, Versicherten- und Kontonummern.
  Ist kein Text lesbar: "".

Allgemeine Regeln:
{_rules(lang)}"""
    url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
    content = [{"type": "text", "text": PHOTO_REQUEST}, {"type": "image_url", "image_url": {"url": url}}]
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def _rules(lang: str) -> str:
    """Regeln für Datum, Uhrzeit, Zuordnung und Markierung – gleich für Sprache, Text und Foto."""
    return f"""\
- Relative Angaben immer über die Tabelle auflösen. "am Freitag" / "Freitag" / "nächsten Freitag" = der nächste
  Freitag nach heute. "übermorgen" = heute + 2 Tage. "nächste Woche Dienstag" = Dienstag der Woche nach dieser Woche.
- Uhrzeiten im 24-Stunden-Format. "um drei" bei einem Termin am Tag = 15:00, "halb vier" = 15:30,
  "Viertel nach vier" = 16:15. Wenn nicht klar ist, ob morgens oder abends gemeint ist: plausibelste Zeit nehmen
  und "start_time" in "uncertain" aufnehmen.
- Keine Uhrzeit genannt: Geburtstage, Feiertage, Ferien, Urlaub und ähnliche Tagesereignisse sind ganztägig
  (all_day=true, start_time=null). Bei allen anderen Terminen all_day=false, start_time=null und "start_time" in
  "uncertain" – nicht raten.
- Kein Datum erkennbar: start_date=null und "start_date" in "uncertain".
- end_time nur, wenn ein Ende oder eine Dauer genannt wird ("bis 17 Uhr", "zwei Stunden"), sonst null.
  end_date nur bei mehrtägigen Terminen, sonst null.
- persons: nur ids aus der Liste. Namen auch in Abwandlungen, Koseformen und über die genannten Zusätze erkennen
  ("Mama", "die Kinder" → alle, bei denen das als Zusatz steht). Personen, die nicht in der Liste stehen (z. B. "Oma"),
  sind keine Familienmitglieder: nicht zuordnen, aber im Titel lassen ("Omas Geburtstag").
- tags: nur ids aus der Liste, nach Bedeutung zuordnen (Fußball → Sport). Passt keiner, leere Liste.
- title: kurz und auf {lang}, ohne Datum, Uhrzeit und ohne die zugeordneten Familienmitglieder ("Lena hat Fußball"
  → "Fußball"). location nur, wenn ein Ort genannt wird. description für weitere Details, sonst "".
- recurrence nur bei Wiederholungen ("jeden Dienstag", "alle zwei Wochen", "jährlich"), sonst null.
  Wöchentlich mit Wochentagen in by_day; until bzw. count nur, wenn ein Ende genannt wird.
- hint: kurzer Satz auf {lang}, was unklar ist; sonst "".
- Felder, die du nicht sicher bestimmen konntest, in "uncertain" aufnehmen."""


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.S)
    if fence:
        raw = fence.group(1)
    try:
        data = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {"events": []}
        try:
            data = json.loads(raw[start:end + 1])
        except ValueError:
            return {"events": []}
    if isinstance(data, list):
        return {"events": data}
    return data if isinstance(data, dict) else {"events": []}


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _time(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d{1,2})(?::|\.|h)?(\d{2})?", value)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour == 24 and minute == 0:
        return time(23, 59)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _map_ids(values: Any, items: list[Any]) -> list[str]:
    """Kennungen übernehmen; liefert das Modell Namen oder Zusätze, auf die Kennung abbilden. Rest verwerfen."""
    if not isinstance(values, list):
        return []
    lookup: dict[str, list[str]] = {}
    for item in items:
        for key in [item.id, item.name, *getattr(item, "aliases", [])]:
            lookup.setdefault(key.strip().lower(), []).append(item.id)
    out: list[str] = []
    for v in values:
        for i in lookup.get(str(v).strip().lower(), []):
            if i not in out:
                out.append(i)
    return out


def normalize(data: dict[str, Any], settings: Settings) -> list[EventDraft]:
    drafts: list[EventDraft] = []
    for raw in data.get("events") or []:
        if not isinstance(raw, dict):
            continue
        uncertain = [f for f in (raw.get("uncertain") or []) if f in FIELDS]
        start_date, start_time = _date(raw.get("start_date")), _time(raw.get("start_time"))
        end_date, end_time = _date(raw.get("end_date")), _time(raw.get("end_time"))
        all_day = bool(raw.get("all_day")) and start_time is None
        if all_day:
            end_time = None
        if end_date and start_date and end_date < start_date:
            end_date, uncertain = None, uncertain + ["end_date"]
        if end_date == start_date and not all_day:
            end_date = None
        recurrence = None
        if isinstance(raw.get("recurrence"), dict):
            rec = dict(raw["recurrence"])
            rec["until"] = _date(rec.get("until"))
            rec["interval"] = rec.get("interval") or 1
            rec["by_day"] = [d for d in (rec.get("by_day") or []) if d in WEEKDAYS]
            try:
                recurrence = Recurrence.model_validate(rec)
            except ValidationError:
                uncertain.append("recurrence")
        title = str(raw.get("title") or "").strip()
        if not title:
            uncertain.append("title")
        if start_date is None:
            uncertain.append("start_date")
        if not all_day and start_time is None:
            uncertain.append("start_time")
        drafts.append(EventDraft(
            title=title,
            all_day=all_day,
            start_date=start_date,
            start_time=start_time,
            end_date=end_date,
            end_time=end_time,
            location=str(raw.get("location") or "").strip(),
            description=str(raw.get("description") or "").strip(),
            persons=_map_ids(raw.get("persons"), settings.persons),
            tags=_map_ids(raw.get("tags"), settings.event_tags),
            recurrence=recurrence,
            uncertain=sorted(set(uncertain), key=FIELDS.index),
            hint=str(raw.get("hint") or "").strip(),
        ))
    return drafts


def extract_events(llm: LlmClient, text: str, settings: Settings, now: datetime) -> list[EventDraft]:
    if not text.strip():
        return []
    raw = llm.complete_json(settings.extraction_model, build_messages(text, settings, now), build_schema(settings))
    return normalize(_parse_json(raw), settings)


PAST_HINT = "Das Datum liegt in der Vergangenheit – bitte prüfen."


def extract_events_from_photo(llm: LlmClient, image: bytes, mime: str, settings: Settings,
                              now: datetime) -> tuple[str, list[EventDraft]]:
    """Foto → (Abschrift, Entwürfe). Vergangene Termine bleiben drin, werden aber markiert (falsches Jahr?)."""
    raw = llm.complete_json(settings.photo_model, build_photo_messages(image, mime, settings, now),
                            build_schema(settings, with_text=True))
    data = _parse_json(raw)
    text = data.get("text")
    drafts = normalize(data, settings)
    today = now.astimezone(settings.tz).date()
    for d in drafts:
        last = d.end_date or d.start_date
        if last and last < today and d.recurrence is None:
            d.uncertain = sorted({*d.uncertain, "start_date"}, key=FIELDS.index)
            d.hint = d.hint or PAST_HINT
    return (text.strip() if isinstance(text, str) else ""), drafts
