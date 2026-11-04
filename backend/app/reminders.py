"""Erinnerungen per Push aufs Handy – standardmäßig 1 Woche, 1 Tag und 1 Stunde vor jedem Termin.

Cloud Run läuft nur, solange eine Anfrage da ist. Deshalb ruft Cloud Scheduler alle 5 Minuten
``POST /api/cron/reminders`` auf; jeder Lauf liest je angemeldetem Familienmitglied die kommenden Termine mit dessen
Google-Zugang und schickt, was seit dem letzten Lauf fällig geworden ist. Welche Erinnerung an welches Gerät schon
ging, steht in ``config/reminders_sent`` – ein doppelter oder wiederholter Lauf schickt nichts zweimal.

Regeln:
- Ganztägige Termine zählen ab 9 Uhr am Tag selbst („1 Tag vorher“ = 9 Uhr am Vortag).
- Nichts nachträglich: keine Erinnerung, die fällig war, bevor es den Termin oder das Abo gab, und keine nach
  Beginn des Termins.
- Ein Gerät kann sich auf Personen beschränken; Termine ohne Person (Familientermine) kommen immer.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from pydantic import BaseModel, Field

from .calendar_api import CalendarClient
from .docstore import DocStore
from .errors import AppError
from .events import ViewEvent, from_google
from .settings import Settings
from .webpush import PushFailed, PushGone, PushSender, Target

log = logging.getLogger("kalender.reminders")

SUBSCRIPTIONS = "push_subscriptions"
SENT_PATH = "config/reminders_sent"
ALL_DAY_HOUR = 9
LOOKBACK = timedelta(hours=2)  # verpasste Läufe (Neustart, Störung) holen höchstens so weit nach


# ---------- Abos (ein Dokument je Gerät) ----------

class Subscription(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    email: str
    persons: list[str] = Field(default_factory=list)  # leer = alle Termine
    device: str = ""
    created: float  # Unix-Zeit; Erinnerungen, die vorher fällig waren, gehen nicht an dieses Gerät

    @property
    def id(self) -> str:
        return subscription_id(self.endpoint)

    @property
    def target(self) -> Target:
        return Target(self.endpoint, self.p256dh, self.auth)


def subscription_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:32]


def _path(endpoint: str) -> str:
    return f"{SUBSCRIPTIONS}/{subscription_id(endpoint)}"


def get_subscription(store: DocStore, endpoint: str) -> Subscription | None:
    raw = store.get(_path(endpoint))
    return Subscription.model_validate(raw) if raw else None


def save_subscription(store: DocStore, sub: Subscription) -> Subscription:
    store.set(_path(sub.endpoint), sub.model_dump())
    return sub


def delete_subscription(store: DocStore, endpoint: str) -> None:
    store.delete(_path(endpoint))


def list_subscriptions(store: DocStore) -> list[Subscription]:
    subs = []
    for raw in store.list_docs(SUBSCRIPTIONS):
        try:
            subs.append(Subscription.model_validate(raw))
        except ValueError:
            log.warning("Unlesbares Push-Abo übersprungen")
    return subs


# ---------- Fällige Erinnerungen ----------

@dataclass(frozen=True)
class Reminder:
    event: ViewEvent
    anchor: datetime  # Beginn; ganztägig 9 Uhr am ersten Tag
    due: datetime
    offset_min: int
    created: datetime | None  # wann der Termin angelegt wurde (Google: ``created``)

    @property
    def key(self) -> str:
        return f"{self.event.id}|{self.anchor.isoformat()}|{self.offset_min}"


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def anchor_of(raw: dict[str, Any], settings: Settings) -> datetime | None:
    start = raw.get("start") or {}
    tz = settings.tz
    try:
        if "date" in start:
            return datetime.combine(date.fromisoformat(start["date"]), time(ALL_DAY_HOUR), tzinfo=tz)
        if "dateTime" in start:
            return datetime.fromisoformat(start["dateTime"]).astimezone(tz)
    except ValueError:
        return None
    return None


def reminders_for(events: list[dict[str, Any]], settings: Settings) -> list[Reminder]:
    out: list[Reminder] = []
    for raw in events:
        anchor = anchor_of(raw, settings)
        if anchor is None or not raw.get("id"):
            continue
        view = from_google(raw, settings)
        created = _parse_ts(raw.get("created"))
        for minutes in settings.reminder_offsets_min:
            out.append(Reminder(view, anchor, anchor - timedelta(minutes=minutes), minutes, created))
    return out


def is_due(rem: Reminder, now: datetime) -> bool:
    if not (now - LOOKBACK < rem.due <= now) or rem.anchor <= now:
        return False
    return rem.created is None or rem.created <= rem.due


def wants(sub: Subscription, event: ViewEvent) -> bool:
    return not sub.persons or not event.persons or bool(set(sub.persons) & set(event.persons))


# ---------- Text der Benachrichtigung ----------

_WEEKDAYS = {"de": ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."],
             "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
_MONTHS = {"de": ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."],
           "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
_WORDS = {"de": {"today": "Heute", "tomorrow": "Morgen", "until": "bis", "clock": " Uhr"},
          "en": {"today": "Today", "tomorrow": "Tomorrow", "until": "until", "clock": ""}}


def day_label(day: date, today: date, lang: str) -> str:
    words = _WORDS.get(lang, _WORDS["de"])
    if day == today:
        return words["today"]
    if day == today + timedelta(days=1):
        return words["tomorrow"]
    wd, mon = _WEEKDAYS.get(lang, _WEEKDAYS["de"])[day.weekday()], _MONTHS.get(lang, _MONTHS["de"])[day.month - 1]
    return f"{wd} {day.day}. {mon}" if lang != "en" else f"{wd} {day.day} {mon}"


def when_text(event: ViewEvent, now: datetime, lang: str) -> str:
    words = _WORDS.get(lang, _WORDS["de"])
    today = now.date()
    if event.all_day:
        first = date.fromisoformat(event.start)
        last = date.fromisoformat(event.end) - timedelta(days=1)
        text = day_label(first, today, lang)
        return f"{text} {words['until']} {day_label(last, today, lang)}" if last > first else text
    start = datetime.fromisoformat(event.start)
    return f"{day_label(start.date(), today, lang)}, {start:%H:%M}{words['clock']}"


def message(rem: Reminder, settings: Settings, now: datetime) -> dict[str, Any]:
    event = rem.event
    parts = [when_text(event, now, settings.language)]
    names = [p.name for p in settings.persons if p.id in event.persons]
    if names:
        parts.append(", ".join(names))
    if event.location:
        parts.append(event.location)
    return {
        "title": event.title,
        "body": " · ".join(parts),
        # gleiche Kennung je Termin: Die nächste Erinnerung ersetzt die vorige, statt sich zu stapeln
        "tag": f"termin-{event.id}",
        "url": "/",
        "lang": settings.language,
    }


# ---------- Lauf (Cloud Scheduler) ----------

def _sent_key(sub: Subscription, rem: Reminder) -> str:
    # Hash statt Klartext: Firestore-Feldnamen vertragen nicht jedes Zeichen der Termin-IDs
    return hashlib.sha256(f"{sub.id}|{rem.key}".encode()).hexdigest()[:32]


def run_reminders(store: DocStore, settings: Settings, now: datetime, sender: PushSender,
                  calendar_for: Callable[[str], CalendarClient], allowed: Callable[[str], bool]) -> dict[str, int]:
    stats = {"sent": 0, "failed": 0, "removed": 0, "skipped_users": 0}
    subs = list_subscriptions(store)
    offsets = settings.reminder_offsets_min
    if not subs or not offsets:
        return stats
    sent: dict[str, float] = dict((store.get(SENT_PATH) or {}).get("sent", {}))
    by_user: dict[str, list[Subscription]] = {}
    for sub in subs:
        by_user.setdefault(sub.email, []).append(sub)
    time_min = now - timedelta(days=1)
    time_max = now + timedelta(minutes=max(offsets)) + LOOKBACK + timedelta(days=1)

    for email, user_subs in by_user.items():
        if not allowed(email):
            stats["skipped_users"] += 1
            continue
        try:
            events = calendar_for(email).list_events(settings.calendar_id, time_min, time_max)
        except AppError as exc:  # z. B. Google-Anmeldung abgelaufen – die anderen sollen trotzdem Erinnerungen bekommen
            log.warning("Erinnerungen für ein Konto übersprungen: %s", exc.message)
            stats["skipped_users"] += 1
            continue
        gone: set[str] = set()
        for rem in reminders_for(events, settings):
            if not is_due(rem, now):
                continue
            payload = None
            for sub in user_subs:
                key = _sent_key(sub, rem)
                if sub.id in gone or key in sent or sub.created > rem.due.timestamp() or not wants(sub, rem.event):
                    continue
                payload = payload or message(rem, settings, now)
                try:
                    sender.send(sub.target, payload, ttl=int((rem.anchor - now).total_seconds()))
                except PushGone:
                    delete_subscription(store, sub.endpoint)
                    gone.add(sub.id)
                    stats["removed"] += 1
                except PushFailed as exc:  # nicht als gesendet merken: der nächste Lauf versucht es noch einmal
                    log.warning("Push fehlgeschlagen: %s", exc)
                    stats["failed"] += 1
                else:
                    sent[key] = rem.anchor.timestamp()
                    stats["sent"] += 1

    cutoff = (now - timedelta(days=1)).timestamp()
    store.set(SENT_PATH, {"sent": {k: v for k, v in sent.items() if v > cutoff},
                          "last_run": now.isoformat(timespec="seconds")})
    if stats["sent"] or stats["failed"] or stats["removed"]:
        log.info("Erinnerungen: %s", stats)
    return stats


def sample_message(settings: Settings) -> dict[str, Any]:
    offsets = settings.reminder_offsets_min
    if settings.language == "en":
        body = ("This is how reminders look." if offsets else "Reminders are switched off in the settings.")
        return {"title": "Family calendar", "body": body, "tag": "test", "url": "/", "lang": "en"}
    body = (f"So sehen Erinnerungen aus – {offset_list(offsets)} vor jedem Termin." if offsets
            else "Erinnerungen sind in den Einstellungen ausgeschaltet.")
    return {"title": "Familienkalender", "body": body, "tag": "test", "url": "/", "lang": "de"}


def offset_label(minutes: int) -> str:
    if minutes % (7 * 1440) == 0:
        n = minutes // (7 * 1440)
        return f"{n} Woche" if n == 1 else f"{n} Wochen"
    if minutes % 1440 == 0:
        n = minutes // 1440
        return f"{n} Tag" if n == 1 else f"{n} Tage"
    if minutes % 60 == 0:
        n = minutes // 60
        return f"{n} Stunde" if n == 1 else f"{n} Stunden"
    return f"{minutes} Minuten"


def offset_list(offsets: list[int]) -> str:
    labels = [offset_label(m) for m in offsets]
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} und {labels[-1]}"
