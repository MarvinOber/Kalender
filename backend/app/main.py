"""Familienkalender – API und Auslieferung der Oberfläche aus einem Cloud-Run-Dienst."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.sessions import SessionMiddleware

from . import auth
from .auth import CurrentUser, User
from .calendar_api import CalendarClient, GoogleCalendar, LocalCalendar
from .docstore import DocStore, get_store
from .errors import AppError, CalendarError
from .events import (
    DraftError,
    EventDraft,
    ViewEvent,
    from_google,
    to_draft,
    to_google,
    to_google_patch,
    validate_draft,
)
from .extraction import extract_events, extract_events_from_photo
from .fake_llm import FakeLlm
from .openrouter import LlmClient, OpenRouter, list_models
from .server_config import get_config
from .settings import Settings, load_settings, save_settings
from .weather import WeatherClient, get_weather

log = logging.getLogger("kalender")
MAX_AUDIO_BYTES = 15 * 1024 * 1024
AUDIO_FORMATS = {"wav", "mp3", "ogg", "flac", "m4a", "aac", "webm"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # die Oberfläche verkleinert vorher auf 2048 px (meist unter 1 MB)

cfg = get_config()
app = FastAPI(title="Familienkalender", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Schreibende Aufrufe nur mit eigenem Header – ein fremdes Formular kann ihn nicht setzen."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith(("/api/", "/auth/logout")):
        if request.headers.get("x-kalender") != "1":
            return JSONResponse({"code": "csrf", "message": "Ungültige Anfrage."}, status_code=403)
    return await call_next(request)


# Nach csrf_guard registriert = äußere Schicht: Die Sitzung steht schon bereit, wenn der Guard läuft.
app.add_middleware(SessionMiddleware, secret_key=cfg.session_secret, session_cookie="kalender_session",
                   max_age=180 * 24 * 3600, same_site="lax", https_only=cfg.cloud)
app.include_router(auth.router)


@app.exception_handler(AppError)
async def app_error(_: Request, exc: AppError) -> JSONResponse:
    if exc.status >= 500:
        log.warning("%s: %s", exc.code, exc.message)
    return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", [])[1:])
    return JSONResponse({"code": "invalid", "message": f"Ungültige Eingabe ({where}): {first.get('msg', '')}"},
                        status_code=422)


# ---------- Abhängigkeiten (in Tests über app.dependency_overrides ersetzt) ----------

def store_dep() -> DocStore:
    return get_store()


def settings_dep(store: DocStore = Depends(store_dep)) -> Settings:
    return load_settings(store)


def llm_dep() -> LlmClient:
    return FakeLlm() if cfg.fake_llm else OpenRouter(cfg.openrouter_api_key, referer=cfg.public_url)


def calendar_dep(user: User = CurrentUser, store: DocStore = Depends(store_dep)) -> CalendarClient:
    if cfg.auth_mode == "none":
        return LocalCalendar(store)
    return GoogleCalendar(lambda: auth.access_token(user.email, store, cfg))


def weather_dep() -> WeatherClient:
    return get_weather()


def now_dep(settings: Settings = Depends(settings_dep)) -> datetime:
    return datetime.now(settings.tz)


# ---------- API ----------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/me")
def me(user: User = CurrentUser) -> dict[str, Any]:
    return {"email": user.email, "name": user.name, "auth_mode": cfg.auth_mode, "fake_llm": cfg.fake_llm}


@app.get("/api/settings")
def get_settings(_: User = CurrentUser, settings: Settings = Depends(settings_dep)) -> Settings:
    return settings


@app.put("/api/settings")
def put_settings(body: dict[str, Any], _: User = CurrentUser, store: DocStore = Depends(store_dep)) -> Settings:
    try:
        settings = Settings.model_validate(body)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", []))
        raise AppError(422, "invalid", f"Einstellungen ungültig ({where}): {first.get('msg', '')}") from exc
    return save_settings(store, settings)


@app.get("/api/models")
def models(_: User = CurrentUser) -> dict[str, Any]:
    return {"models": list_models()}


@app.get("/api/weather")
def weather(_: User = CurrentUser, settings: Settings = Depends(settings_dep),
            client: WeatherClient = Depends(weather_dep)) -> dict[str, Any]:
    place = settings.weather_place.strip()
    if not place:
        return {"place": ""}
    return {"place": place, **client.current(settings.weather_lat, settings.weather_lon)}


@app.get("/api/calendars")
def calendars(_: User = CurrentUser, calendar: CalendarClient = Depends(calendar_dep)) -> dict[str, Any]:
    return {"calendars": calendar.list_calendars()}


@app.get("/api/events")
def events(start: date = Query(...), days: int = Query(7, ge=1, le=42), _: User = CurrentUser,
           settings: Settings = Depends(settings_dep),
           calendar: CalendarClient = Depends(calendar_dep)) -> dict[str, Any]:
    tz = settings.tz
    time_min = datetime.combine(start, time.min, tzinfo=tz)
    time_max = datetime.combine(start + timedelta(days=days), time.min, tzinfo=tz)
    items = calendar.list_events(settings.calendar_id, time_min, time_max)
    return {"events": [from_google(e, settings) for e in items],
            "fetched_at": datetime.now(tz).isoformat(timespec="seconds")}


class ParseRequest(BaseModel):
    text: str = Field(max_length=4000)


def _drafts_response(transcript: str, drafts: list[EventDraft]) -> dict[str, Any]:
    message = ""
    if not transcript.strip():
        message = "In der Aufnahme war nichts zu verstehen. Bitte noch einmal deutlich einsprechen."
    elif not drafts:
        message = "Im Gesagten wurde kein Termin erkannt."
    return {"transcript": transcript, "events": [d.model_dump(mode="json") for d in drafts], "message": message}


@app.post("/api/voice")
async def voice(audio: UploadFile = File(...), _: User = CurrentUser, settings: Settings = Depends(settings_dep),
                llm: LlmClient = Depends(llm_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    # Die Aufnahme bleibt nur im Arbeitsspeicher dieser Anfrage – sie wird nirgends abgelegt.
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise AppError(413, "too_large", "Die Aufnahme ist zu lang. Bitte kürzer fassen.")
    if len(data) < 1000:
        return _drafts_response("", [])
    fmt = Path(audio.filename or "").suffix.lstrip(".").lower() or "wav"
    if fmt not in AUDIO_FORMATS:
        raise AppError(415, "audio_format", f"Audioformat „{fmt}“ wird nicht unterstützt.")
    transcript = llm.transcribe(settings.transcription_model, data, fmt, settings.language)
    del data
    drafts = extract_events(llm, transcript, settings, now)
    return _drafts_response(transcript, drafts)


def image_type(data: bytes) -> str | None:
    """Bildformat am Dateianfang erkennen – Dateiname und Content-Type kommen vom Browser und sagen wenig."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


@app.post("/api/photo")
async def photo(image: UploadFile = File(...), _: User = CurrentUser, settings: Settings = Depends(settings_dep),
                llm: LlmClient = Depends(llm_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    """Foto einer Kalenderseite, eines Terminzettels oder Briefs → Abschrift und erkannte Termine."""
    # Das Foto bleibt nur im Arbeitsspeicher dieser Anfrage – es wird nirgends abgelegt.
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise AppError(413, "too_large", "Das Foto ist zu groß (höchstens 10 MB).")
    mime = image_type(data)
    if not mime:
        raise AppError(415, "image_format", "Dieses Bildformat wird nicht unterstützt. Bitte ein Foto als JPEG, "
                                            "PNG oder WebP wählen.")
    text, drafts = extract_events_from_photo(llm, data, mime, settings, now)
    del data
    message = ""
    if not drafts:
        message = ("Auf dem Foto wurde kein Termin erkannt." if text else
                   "Auf dem Foto war nichts zu lesen. Bitte näher heran, gerade und gut beleuchtet fotografieren.")
    return {"transcript": text, "events": [d.model_dump(mode="json") for d in drafts], "message": message}


@app.post("/api/parse")
def parse(body: ParseRequest, _: User = CurrentUser, settings: Settings = Depends(settings_dep),
          llm: LlmClient = Depends(llm_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    """Wie ``/api/voice``, aber mit getipptem Text – Rückfall ohne Mikrofon."""
    return _drafts_response(body.text, extract_events(llm, body.text, settings, now))


class CreateRequest(BaseModel):
    events: list[EventDraft] = Field(min_length=1, max_length=20)


@app.post("/api/events")
def create_events(body: CreateRequest, _: User = CurrentUser, settings: Settings = Depends(settings_dep),
                  calendar: CalendarClient = Depends(calendar_dep)) -> dict[str, Any]:
    # Erst alles prüfen, dann schreiben – ein fehlerhafter Termin soll nicht die Hälfte anlegen.
    problems = [f"Termin {i + 1}: {'; '.join(errs)}" for i, d in enumerate(body.events)
                if (errs := validate_draft(d, settings))]
    if problems:
        raise AppError(422, "invalid", " · ".join(problems))
    created: list[ViewEvent] = []
    for draft in body.events:
        try:
            event = calendar.insert_event(settings.calendar_id, to_google(draft, settings))
        except DraftError as exc:
            raise AppError(422, "invalid", str(exc)) from exc
        except CalendarError as exc:
            if created:
                exc.message += f" ({len(created)} von {len(body.events)} Terminen wurden schon angelegt.)"
            raise
        created.append(from_google(event, settings))
    return {"created": [c.model_dump() for c in created]}


# ---------- Bearbeiten und Löschen ----------
# „instance“ = nur dieser Termin (bei Serien: dieses eine Vorkommen), „series“ = die ganze Serie.
Scope = Literal["instance", "series"]


def _target(calendar: CalendarClient, settings: Settings, event_id: str, scope: Scope) -> dict[str, Any]:
    event = calendar.get_event(settings.calendar_id, event_id)
    if scope == "series" and event.get("recurringEventId"):
        event = calendar.get_event(settings.calendar_id, event["recurringEventId"])
    return event


@app.get("/api/events/{event_id}")
def get_event(event_id: str, scope: Scope = "instance", _: User = CurrentUser,
              settings: Settings = Depends(settings_dep),
              calendar: CalendarClient = Depends(calendar_dep)) -> dict[str, Any]:
    """Termin für den Bearbeiten-Dialog. ``id`` ist bei ``scope=series`` die Kennung der Serie."""
    event = _target(calendar, settings, event_id, scope)
    draft, recurrence_editable = to_draft(event, settings)
    return {"id": event["id"], "draft": draft.model_dump(mode="json"),
            "recurrence_editable": recurrence_editable, "series": bool(event.get("recurrence"))}


class UpdateRequest(BaseModel):
    draft: EventDraft
    recurrence_unchanged: bool = False  # Wiederholung nicht anfassen (auch: im Dialog nicht abbildbar)


@app.put("/api/events/{event_id}")
def update_event(event_id: str, body: UpdateRequest, _: User = CurrentUser,
                 settings: Settings = Depends(settings_dep),
                 calendar: CalendarClient = Depends(calendar_dep)) -> dict[str, Any]:
    if errors := validate_draft(body.draft, settings):
        raise AppError(422, "invalid", "; ".join(errors))
    event = calendar.get_event(settings.calendar_id, event_id)
    # Ein einzelnes Vorkommen einer Serie kann keine eigene Wiederholung haben
    with_recurrence = not body.recurrence_unchanged and not event.get("recurringEventId")
    patch = to_google_patch(body.draft, settings, with_recurrence=with_recurrence)
    updated = calendar.patch_event(settings.calendar_id, event_id, patch)
    return {"event": from_google(updated, settings).model_dump()}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: str, scope: Scope = "instance", _: User = CurrentUser,
                 settings: Settings = Depends(settings_dep),
                 calendar: CalendarClient = Depends(calendar_dep)) -> dict[str, Any]:
    target = _target(calendar, settings, event_id, scope)
    calendar.delete_event(settings.calendar_id, target["id"])
    return {"ok": True}


# ---------- Oberfläche (gebaute Vite-App) ----------

@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> Response:
    static = cfg.static_dir.resolve()
    if path.startswith(("api/", "auth/")):
        return JSONResponse({"code": "not_found", "message": "Nicht gefunden."}, status_code=404)
    target = (static / path).resolve() if path else static / "index.html"
    if path and target.is_file() and static in target.parents:
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(target, headers={"Cache-Control": cache})
    index = static / "index.html"
    if not index.is_file():
        return Response("Oberfläche nicht gebaut (frontend: npm run build).", status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
