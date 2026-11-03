from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

# Tests laufen immer lokal, ohne Anmeldung und ohne echte KI – unabhängig von einer backend/.env
os.environ.update(KALENDER_BACKEND="local", KALENDER_AUTH="none", KALENDER_FAKE_LLM="1")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.docstore import MemoryDocStore  # noqa: E402
from app.settings import default_settings  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")
# Dienstag, 3. November 2026, 14:00 – fester „Jetzt“-Zeitpunkt aller Tests
NOW = datetime(2026, 11, 3, 14, 0, tzinfo=BERLIN)


class ScriptedLlm:
    """Attrappe für OpenRouter: liefert je Eingabesatz eine vorbereitete Modellantwort und merkt sich die Aufrufe."""

    def __init__(self, answers: dict[str, Any] | None = None, transcript: str = "") -> None:
        self.answers = answers or {}
        self.transcript = transcript
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, model: str, audio: bytes, audio_format: str, language: str) -> str:
        self.calls.append({"kind": "transcribe", "model": model, "format": audio_format, "bytes": len(audio)})
        return self.transcript

    def complete_json(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> str:
        text = messages[-1]["content"]
        self.calls.append({"kind": "json", "model": model, "messages": messages, "schema": schema})
        answer = self.answers.get(text, {"events": []})
        return answer if isinstance(answer, str) else json.dumps(answer)


@pytest.fixture
def settings():
    return default_settings()


@pytest.fixture
def store():
    return MemoryDocStore()


@pytest.fixture
def client(store):
    main.app.dependency_overrides[main.store_dep] = lambda: store
    main.app.dependency_overrides[main.now_dep] = lambda: NOW
    with TestClient(main.app, headers={"X-Kalender": "1"}) as c:
        yield c
    main.app.dependency_overrides.clear()
