"""OpenRouter-Anbindung (Attrappe über ``httpx.MockTransport``): Gesamtfrist je Anfrage, auch wenn OpenRouter die
Verbindung mit Leerzeichen wachhält, und verständliche Fehlermeldungen."""

from __future__ import annotations

import json

import httpx
import pytest

from app.errors import ModelTimeout, ModelUnavailable
from app.openrouter import OpenRouter

ANSWER = json.dumps({"choices": [{"message": {"content": '{"events": []}'}}]}).encode()
MESSAGES = [{"role": "user", "content": "Morgen um 8 Arzt"}]


class Clock:
    """Uhr zum Vorstellen – die Tests warten nie wirklich."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def router(handler, clock: Clock, budget: float = 90) -> OpenRouter:
    return OpenRouter("sk-test", client=httpx.Client(transport=httpx.MockTransport(handler)), budget=budget,
                      clock=clock)


def test_leerzeichen_zum_wachhalten_stoeren_nicht():
    clock = Clock()

    def body():
        for _ in range(3):
            clock.t += 20
            yield b"\n"
        yield ANSWER

    llm = router(lambda _: httpx.Response(200, content=body()), clock)
    assert llm.complete_json("m/x", MESSAGES, {"type": "object"}) == '{"events": []}'


def test_gesamtfrist_trotz_leerzeichen():
    # So hing ein Foto über 10 Minuten: OpenRouter schickt weiter Leerzeichen, das Lese-Timeout greift nie.
    clock = Clock()
    sent: list[int] = []

    def body():
        while True:
            clock.t += 15
            sent.append(1)
            yield b" "

    llm = router(lambda _: httpx.Response(200, content=body()), clock)
    with pytest.raises(ModelTimeout) as err:
        llm.complete_json("xiaomi/mimo-v2.6-pro", MESSAGES, {})
    assert err.value.status == 504 and err.value.code == "model_timeout"
    assert err.value.message.startswith("Das Modell xiaomi/mimo-v2.6-pro hat nicht rechtzeitig geantwortet")
    assert "90 Sekunden" in err.value.message and "schnelleres Modell" in err.value.message
    assert len(sent) == 7  # beim ersten Stück nach Fristende abgebrochen (7 × 15 s > 90 s), nicht weitergelesen


def test_frist_gilt_fuer_die_ganze_anfrage():
    # Sprache: Transkription und Erkennung teilen sich die Frist, der zweite Aufruf bekommt nur den Rest.
    clock = Clock()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        clock.t += 60
        return httpx.Response(200, content=ANSWER)

    llm = router(handler, clock)
    llm.transcribe("m/audio", b"RIFF", "wav", "de")
    assert seen[0].extensions["timeout"]["read"] == 90
    with pytest.raises(ModelTimeout):  # 2. Aufruf: 30 s Rest, das Modell braucht 60 s
        llm.complete_json("m/x", MESSAGES, {})
    assert seen[1].extensions["timeout"]["read"] == 30
    with pytest.raises(ModelTimeout):  # Frist ist um: gar nicht erst senden
        llm.complete_json("m/x", MESSAGES, {})
    assert len(seen) == 2


def test_zeitueberschreitung_von_httpx():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("zu langsam", request=request)

    with pytest.raises(ModelTimeout):
        router(handler, Clock()).complete_json("m/x", MESSAGES, {})


@pytest.mark.parametrize(("status", "body", "expected"), [
    (429, {"error": {"message": "rate limited"}}, "Das Modell m/x ist gerade ausgelastet. Bitte gleich noch einmal."),
    (400, {"error": {"message": "image too large"}},
     "Das Modell m/x kann diese Anfrage nicht verarbeiten. image too large"),
    (402, {}, "Das Guthaben bei OpenRouter ist aufgebraucht."),
    (504, None, "Das Modell m/x hat nicht rechtzeitig geantwortet. Bitte noch einmal versuchen oder in den "
                "Einstellungen ein schnelleres Modell wählen."),
    (500, None, "Das Modell m/x ist nicht erreichbar (Fehler 500)."),
])
def test_fehlermeldungen(status, body, expected):
    content = json.dumps(body).encode() if body is not None else b"<html>Gateway</html>"
    llm = router(lambda _: httpx.Response(status, content=content), Clock())
    with pytest.raises(ModelUnavailable) as err:
        llm.complete_json("m/x", MESSAGES, {})
    assert err.value.message == expected


def test_kaputte_antwort():
    llm = router(lambda _: httpx.Response(200, content=b"   \n<html>"), Clock())
    with pytest.raises(ModelUnavailable, match="Unerwartete Antwort von m/x"):
        llm.complete_json("m/x", MESSAGES, {})
