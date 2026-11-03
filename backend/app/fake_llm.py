"""Betrieb ohne KI-Kosten (``KALENDER_FAKE_LLM=1``): eine feste Beispielaufnahme mit passender Antwort.

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
