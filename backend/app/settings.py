"""Gemeinsame Einstellungen der Familie – ein Dokument ``config/settings`` in der Datenbank.

Jede Anfrage liest die Einstellungen frisch: Ein Modellwechsel in der Oberfläche wirkt beim nächsten Aufruf,
ohne neues Deployment.
"""

from __future__ import annotations

import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from .docstore import DocStore

SETTINGS_PATH = "config/settings"

DEFAULT_TRANSCRIPTION_MODEL = "xiaomi/mimo-v2.6-pro"
DEFAULT_EXTRACTION_MODEL = "xiaomi/mimo-v2.6-pro"
DEFAULT_PHOTO_MODEL = "xiaomi/mimo-v2.6-pro"  # nimmt Bilder an und kann JSON-Schema

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def slug(text: str) -> str:
    """Stabile Kennung aus einem Namen („Oma Inge“ → „oma-inge“); bleibt beim Umbenennen erhalten."""
    norm = unicodedata.normalize("NFKD", text.replace("ß", "ss")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-") or "tag"


def _clean_aliases(values: list[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        v = v.strip()
        if v and v.lower() not in (s.lower() for s in seen):
            seen.append(v)
    return seen


class Person(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=40)
    color: str = "#4c6ef5"
    aliases: list[str] = Field(default_factory=list)  # „Mama“, „Kinder“ – darf bei mehreren Personen stehen

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not _COLOR.match(v):
            raise ValueError("Farbe als #rrggbb angeben")
        return v.lower()

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        return _clean_aliases(v)

    @model_validator(mode="after")
    def _id(self) -> Person:
        self.name = self.name.strip()
        if not self.id:
            self.id = slug(self.name)
        return self


class EventTag(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list)  # Hinweise für das Modell, z. B. Sport: Fußball, Training

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        return _clean_aliases(v)

    @model_validator(mode="after")
    def _id(self) -> EventTag:
        self.name = self.name.strip()
        if not self.id:
            self.id = slug(self.name)
        return self


class Settings(BaseModel):
    calendar_id: str = "primary"
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL
    extraction_model: str = DEFAULT_EXTRACTION_MODEL
    photo_model: str = DEFAULT_PHOTO_MODEL  # Fotos von Kalenderseiten, Terminzetteln, Briefen
    language: str = "de"
    timezone: str = "Europe/Berlin"
    default_duration_min: int = Field(default=60, ge=5, le=24 * 60)
    persons: list[Person] = Field(default_factory=list)
    event_tags: list[EventTag] = Field(default_factory=list)
    # Wetter-Icon in der Kopfzeile; leerer Ort blendet es aus. Bokel im Kreis Pinneberg (es gibt mehrere Bokel)
    weather_place: str = Field(default="Bokel", max_length=60)
    weather_lat: float = Field(default=53.86667, ge=-90, le=90)
    weather_lon: float = Field(default=9.73333, ge=-180, le=180)

    @field_validator("calendar_id", "transcription_model", "extraction_model", "photo_model")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("darf nicht leer sein")
        return v

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("de", "en"):
            raise ValueError("Sprache: de oder en")
        return v

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unbekannte Zeitzone: {v}") from exc
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> Settings:
        for items in (self.persons, self.event_tags):
            ids = [i.id for i in items]
            if len(ids) != len(set(ids)):
                raise ValueError("Namen müssen eindeutig sein")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def default_settings() -> Settings:
    """Startwerte für eine neue Installation – in den Einstellungen anpassen."""
    return Settings(
        persons=[
            Person(name="Mama", color="#e8590c", aliases=["Mami", "Mutti", "Eltern"]),
            Person(name="Papa", color="#1c7ed6", aliases=["Papi", "Vati", "Eltern"]),
            Person(name="Lena", color="#d6336c", aliases=["Kinder", "die Kinder"]),
            Person(name="Max", color="#2f9e44", aliases=["Kinder", "die Kinder"]),
        ],
        event_tags=[
            EventTag(name="Schule", aliases=["Elternabend", "Klassenfahrt"]),
            EventTag(name="Arzt", aliases=["Zahnarzt", "Kinderarzt", "Impfung"]),
            EventTag(name="Sport", aliases=["Fußball", "Schwimmen", "Training", "Turnen"]),
            EventTag(name="Geburtstag"),
            EventTag(name="Arbeit"),
            EventTag(name="Freizeit", aliases=["Ausflug", "Kino", "Besuch"]),
        ],
    )


def load_settings(store: DocStore) -> Settings:
    raw = store.get(SETTINGS_PATH)
    if not raw:
        return default_settings()
    return Settings.model_validate({**default_settings().model_dump(), **raw})


def save_settings(store: DocStore, settings: Settings) -> Settings:
    store.set(SETTINGS_PATH, settings.model_dump())
    return settings
