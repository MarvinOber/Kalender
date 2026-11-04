"""Termin-Erkennung: Beispielsätze → Modellantwort → erwartetes JSON der Entwürfe.

Die Modellantworten sind so formuliert, wie ein Modell mit dem Schema antwortet (inkl. typischer Ausreißer:
Namen statt Kennungen, Code-Zaun, fremde Personen). Geprüft wird, was daraus im Bestätigungsdialog ankommt.
Die echten Modelle prüft ``test_extraction_live.py``.
"""

from __future__ import annotations

import pytest

from app.extraction import (
    PAST_HINT,
    PHOTO_REQUEST,
    build_messages,
    build_photo_messages,
    build_schema,
    extract_events,
    extract_events_from_photo,
)

from .conftest import NOW, PHOTO, ScriptedLlm


def ev(**kw):
    base = {"title": "", "all_day": False, "start_date": None, "start_time": None, "end_date": None,
            "end_time": None, "location": "", "description": "", "persons": [], "tags": [], "recurrence": None,
            "uncertain": [], "hint": ""}
    return {**base, **kw}


CASES = [
    pytest.param(
        "Am Freitag um 16 Uhr hat Lena Fussball und Samstag ist Omas Geburtstag",
        {"events": [
            ev(title="Fußball", start_date="2026-11-06", start_time="16:00", persons=["lena"], tags=["sport"]),
            ev(title="Omas Geburtstag", all_day=True, start_date="2026-11-07", tags=["geburtstag"]),
        ]},
        [
            {"title": "Fußball", "all_day": False, "start_date": "2026-11-06", "start_time": "16:00:00",
             "persons": ["lena"], "tags": ["sport"], "uncertain": []},
            {"title": "Omas Geburtstag", "all_day": True, "start_date": "2026-11-07", "start_time": None,
             "persons": [], "tags": ["geburtstag"], "uncertain": []},
        ],
        id="abnahme-zwei-termine",
    ),
    pytest.param(
        "Übermorgen um drei Zahnarzt mit Mama in der Lindenstraße",
        {"events": [ev(title="Zahnarzt", start_date="2026-11-05", start_time="15:00", location="Lindenstraße",
                       persons=["mama"], tags=["arzt"])]},
        [{"title": "Zahnarzt", "start_date": "2026-11-05", "start_time": "15:00:00", "location": "Lindenstraße",
          "persons": ["mama"], "tags": ["arzt"], "uncertain": []}],
        id="uebermorgen-um-drei",
    ),
    pytest.param(
        "Nächsten Dienstag ist Elternabend",
        {"events": [ev(title="Elternabend", start_date="2026-11-10", tags=["schule"], uncertain=["start_time"],
                       hint="Uhrzeit fehlt")]},
        [{"title": "Elternabend", "all_day": False, "start_date": "2026-11-10", "start_time": None,
          "uncertain": ["start_time"], "hint": "Uhrzeit fehlt"}],
        id="fehlende-uhrzeit-wird-markiert",
    ),
    pytest.param(
        "Arzttermin für Papa",
        # Modell vergisst die Markierung – normalize ergänzt sie, statt zu raten
        {"events": [ev(title="Arzttermin", persons=["papa"], tags=["arzt"])]},
        [{"title": "Arzttermin", "start_date": None, "start_time": None,
          "uncertain": ["start_date", "start_time"]}],
        id="fehlendes-datum-wird-markiert",
    ),
    pytest.param(
        "Die Kinder haben ab Donnerstag jede Woche um 17 Uhr Schwimmen bis Weihnachten",
        {"events": [ev(title="Schwimmen", start_date="2026-11-05", start_time="17:00", persons=["lena", "max"],
                       tags=["sport"], recurrence={"freq": "weekly", "interval": 1, "by_day": ["TH"],
                                                   "until": "2026-12-24", "count": None})]},
        [{"title": "Schwimmen", "persons": ["lena", "max"],
          "recurrence": {"freq": "weekly", "interval": 1, "by_day": ["TH"], "until": "2026-12-24", "count": None}}],
        id="die-kinder-und-wiederholung",
    ),
    pytest.param(
        "Morgen von 9 bis halb 11 hat Mutti Training",
        # Modell liefert Namen bzw. Zusätze statt Kennungen und dazu eine erfundene Person
        {"events": [ev(title="Training", start_date="2026-11-04", start_time="09:00", end_time="10:30",
                       persons=["Mutti", "Oma"], tags=["Sport"])]},
        [{"title": "Training", "start_time": "09:00:00", "end_time": "10:30:00", "persons": ["mama"],
          "tags": ["sport"]}],
        id="namen-statt-kennungen",
    ),
    pytest.param(
        "Herbstferien vom 19. bis 23. Oktober nächstes Jahr",
        "```json\n" + '{"events": [{"title": "Herbstferien", "all_day": true, "start_date": "2027-10-19", '
        '"start_time": null, "end_date": "2027-10-23", "end_time": null, "location": "", "description": "", '
        '"persons": ["lena", "max"], "tags": [], "recurrence": null, "uncertain": [], "hint": ""}]}' + "\n```",
        [{"title": "Herbstferien", "all_day": True, "start_date": "2027-10-19", "end_date": "2027-10-23"}],
        id="mehrtaegig-mit-codezaun",
    ),
    pytest.param(
        "Wie wird das Wetter morgen?",
        {"events": []},
        [],
        id="kein-termin",
    ),
]


@pytest.mark.parametrize(("sentence", "model_answer", "expected"), CASES)
def test_beispielsaetze(sentence, model_answer, expected, settings):
    llm = ScriptedLlm({sentence: model_answer})
    drafts = [d.model_dump(mode="json") for d in extract_events(llm, sentence, settings, NOW)]
    assert len(drafts) == len(expected)
    for got, want in zip(drafts, expected, strict=True):
        assert {k: got[k] for k in want} == want


def test_leerer_text_ruft_kein_modell(settings):
    llm = ScriptedLlm()
    assert extract_events(llm, "   ", settings, NOW) == []
    assert llm.calls == []


def test_ganztaegig_mit_uhrzeit_wird_zeittermin(settings):
    llm = ScriptedLlm({"x": {"events": [ev(title="Kino", all_day=True, start_date="2026-11-04",
                                          start_time="20:00")]}})
    [draft] = extract_events(llm, "x", settings, NOW)
    assert draft.all_day is False and draft.start_time.hour == 20


def test_kaputte_antwort_ergibt_keine_termine(settings):
    llm = ScriptedLlm({"x": "Das kann ich leider nicht."})
    assert extract_events(llm, "x", settings, NOW) == []


def test_prompt_enthaelt_datum_tabelle_und_listen(settings):
    system = build_messages("…", settings, NOW)[0]["content"]
    assert "Dienstag, 2026-11-03, 14:00 Uhr" in system
    assert "Donnerstag 2026-11-05 (übermorgen)" in system
    assert "Freitag 2026-11-06" in system and "Samstag 2026-11-07" in system
    assert "Dienstag 2026-11-10" in system
    assert 'id "lena": Lena (auch: Kinder, die Kinder)' in system
    assert 'id "sport": Sport (z. B. Fußball' in system


def test_prompt_rechnet_in_familien_zeitzone(settings):
    # 23:30 UTC am 3.11. ist in Berlin schon der 4.11.
    from datetime import UTC, datetime
    system = build_messages("…", settings, datetime(2026, 11, 3, 23, 30, tzinfo=UTC))[0]["content"]
    assert "Mittwoch, 2026-11-04, 00:30 Uhr" in system


def test_schema_erlaubt_nur_eigene_tags(settings):
    item = build_schema(settings)["properties"]["events"]["items"]["properties"]
    assert item["persons"]["items"]["enum"] == ["mama", "papa", "lena", "max"]
    assert item["tags"]["items"]["enum"] == ["schule", "arzt", "sport", "geburtstag", "arbeit", "freizeit"]
    settings.persons = []
    assert build_schema(settings)["properties"]["events"]["items"]["properties"]["persons"]["maxItems"] == 0


# ---------- Fotos ----------

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def test_foto_prompt_mit_bild_und_abschrift(settings):
    messages = build_photo_messages(JPEG, "image/jpeg", settings, NOW)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Dienstag, 2026-11-03, 14:00 Uhr" in system and "Donnerstag 2026-11-05 (übermorgen)" in system
    assert "Terminzettel" in system and "vor heute liegen, weglassen" in system
    assert 'id "max": Max' in system
    assert user[0] == {"type": "text", "text": PHOTO_REQUEST}
    assert user[1]["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/")
    schema = build_schema(settings, with_text=True)
    assert list(schema["properties"]) == ["text", "events"] and schema["required"] == ["text", "events"]


def test_foto_terminzettel(settings):
    answer = {"text": "Do 05.11. 15:30 Kontrolle, Max\nDo 19.11. 09:00 Zahnreinigung, Max", "events": [
        ev(title="Kontrolle Zahnarzt", start_date="2026-11-05", start_time="15:30", persons=["Max"], tags=["arzt"],
           location="Praxis Dr. Weiß", description="Versichertenkarte mitbringen"),
        ev(title="Zahnreinigung", start_date="2026-11-19", start_time="09:00", persons=["max"], tags=["arzt"]),
    ]}
    llm = ScriptedLlm({PHOTO: answer})
    settings.photo_model = "google/gemini-3.5-flash"
    text, drafts = extract_events_from_photo(llm, JPEG, "image/jpeg", settings, NOW)
    assert text.startswith("Do 05.11. 15:30 Kontrolle")
    assert [(d.title, d.start_date.isoformat(), d.persons, d.uncertain) for d in drafts] == [
        ("Kontrolle Zahnarzt", "2026-11-05", ["max"], []), ("Zahnreinigung", "2026-11-19", ["max"], [])]
    assert drafts[0].description == "Versichertenkarte mitbringen"
    assert llm.calls[0]["model"] == "google/gemini-3.5-flash"


def test_foto_vergangener_termin_wird_markiert(settings):
    # z. B. Kalenderblatt ohne Jahr, das Modell nimmt das falsche Jahr
    answer = {"text": "12.10. Laternenumzug", "events": [ev(title="Laternenumzug", start_date="2026-10-12",
                                                                start_time="17:00")]}
    _, [draft] = extract_events_from_photo(ScriptedLlm({PHOTO: answer}), JPEG, "image/jpeg", settings, NOW)
    assert draft.uncertain == ["start_date"] and draft.hint == PAST_HINT


def test_foto_ohne_abschrift_und_kaputte_antwort(settings):
    assert extract_events_from_photo(ScriptedLlm({PHOTO: "Kein Kalender zu sehen."}), JPEG, "image/jpeg",
                                     settings, NOW) == ("", [])
