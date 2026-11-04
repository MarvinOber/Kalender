"""Betrieb ohne KI-Kosten (``KALENDER_FAKE_LLM=1``): feste Beispielaufnahme und festes Beispielfoto mit Antwort.

Die Antwort sieht aus wie die eines echten Modells – so läuft der ganze Weg einschließlich ``normalize``.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

DEMO_SENTENCE = "Am Freitag um 16 Uhr hat Lena Fussball und Samstag ist Omas Geburtstag"


def _next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)


class FakeLlm:
    def transcribe(self, model: str, audio: bytes, audio_format: str, language: str) -> str:
        return DEMO_SENTENCE if len(audio) > 2000 else ""

    def complete_json(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> str:
        system = messages[0]["content"]
        today = date.fromisoformat(re.search(r"Jetzt ist \w+, (\d{4}-\d{2}-\d{2})", system).group(1))
        if isinstance(messages[-1]["content"], list):  # Foto: jedes Bild gilt als derselbe Terminzettel
            return json.dumps(_photo_answer(today), ensure_ascii=False)
        text = messages[-1]["content"].lower()
        events = []
        if "fussball" in text or "fußball" in text:
            events.append({
                "title": "Fußball", "all_day": False,
                "start_date": _next_weekday(today, 4).isoformat(), "start_time": "16:00",
                "end_date": None, "end_time": None, "location": "", "description": "",
                "persons": ["lena"], "tags": ["sport"], "recurrence": None, "uncertain": [], "hint": ""})
        if "geburtstag" in text:
            events.append({
                "title": "Omas Geburtstag", "all_day": True,
                "start_date": _next_weekday(today, 5).isoformat(), "start_time": None,
                "end_date": None, "end_time": None, "location": "", "description": "",
                "persons": [], "tags": ["geburtstag"], "recurrence": None, "uncertain": [], "hint": ""})
        return json.dumps({"events": events}, ensure_ascii=False)


def _photo_answer(today: date) -> dict[str, Any]:
    """Demo-Foto: Terminzettel vom Zahnarzt und ein Elternbrief."""
    dentist, evening = _next_weekday(today, 3), _next_weekday(today, 1) + timedelta(days=7)
    return {
        "text": (f"Zahnarztpraxis Dr. Weiß – Max – {dentist:%d.%m.} 15:30 Kontrolle\n"
                 f"Elternabend Klasse 3b – {evening:%d.%m.} 19:30"),
        "events": [
            {"title": "Kontrolle Zahnarzt", "all_day": False,
             "start_date": dentist.isoformat(), "start_time": "15:30", "end_date": None, "end_time": None,
             "location": "Zahnarztpraxis Dr. Weiß, Hauptstraße 5", "description": "Versichertenkarte mitbringen",
             "persons": ["max"], "tags": ["arzt"], "recurrence": None, "uncertain": [], "hint": ""},
            {"title": "Elternabend Klasse 3b", "all_day": False,
             "start_date": evening.isoformat(), "start_time": "19:30", "end_date": None, "end_time": None,
             "location": "", "description": "", "persons": [], "tags": ["schule"], "recurrence": None,
             "uncertain": [], "hint": ""},
        ],
    }
