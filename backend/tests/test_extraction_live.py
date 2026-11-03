"""Dieselben Beispielsätze gegen das echte Modell (kostet ein paar Cent).

    $env:OPENROUTER_API_KEY = "sk-or-v1-…"; $env:KALENDER_LIVE_TESTS = "1"
    .venv\\Scripts\\python -m pytest -m live -v

Optional ``KALENDER_LIVE_MODEL`` für ein anderes Erkennungsmodell.
"""

from __future__ import annotations

import os

import pytest

from app.extraction import extract_events
from app.openrouter import OpenRouter

from .conftest import NOW

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (os.environ.get("OPENROUTER_API_KEY") and os.environ.get("KALENDER_LIVE_TESTS") == "1"),
                       reason="nur mit OPENROUTER_API_KEY und KALENDER_LIVE_TESTS=1"),
]

LIVE = [
    ("Am Freitag um 16 Uhr hat Lena Fussball und Samstag ist Omas Geburtstag", [
        {"start_date": "2026-11-06", "start_time": "16:00:00", "all_day": False, "persons": ["lena"],
         "tags": ["sport"]},
        {"start_date": "2026-11-07", "all_day": True, "persons": [], "tags": ["geburtstag"]},
    ]),
    ("Übermorgen um drei hat Mama einen Zahnarzttermin", [
        {"start_date": "2026-11-05", "start_time": "15:00:00", "persons": ["mama"], "tags": ["arzt"]},
    ]),
    ("Nächsten Dienstag ist Elternabend", [
        {"start_date": "2026-11-10", "start_time": None, "tags": ["schule"]},
    ]),
    ("Die Kinder haben jeden Donnerstag um 17 Uhr Schwimmen", [
        {"start_date": "2026-11-05", "start_time": "17:00:00", "persons": ["lena", "max"], "tags": ["sport"]},
    ]),
]


@pytest.mark.parametrize(("sentence", "expected"), LIVE)
def test_live(sentence, expected, settings):
    if model := os.environ.get("KALENDER_LIVE_MODEL"):
        settings.extraction_model = model
    llm = OpenRouter(os.environ["OPENROUTER_API_KEY"])
    drafts = [d.model_dump(mode="json") for d in extract_events(llm, sentence, settings, NOW)]
    assert len(drafts) == len(expected), drafts
    for got, want in zip(drafts, expected, strict=True):
        assert {k: (sorted(got[k]) if isinstance(got[k], list) else got[k]) for k in want} == \
            {k: (sorted(v) if isinstance(v, list) else v) for k, v in want.items()}, got
    if "Elternabend" in sentence:
        assert "start_time" in drafts[0]["uncertain"]
    if "jeden Donnerstag" in sentence:
        assert drafts[0]["recurrence"]["freq"] == "weekly"
