"""Web Push: Verschlüsselung (Gegenprobe mit ``http_ece``), VAPID-Signatur, Versand gegen eine Attrappe."""

from __future__ import annotations

import json
import os
import struct

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app.webpush import (
    PushFailed,
    PushGone,
    Target,
    Vapid,
    WebPushSender,
    b64url,
    b64url_decode,
    encrypt,
    generate_private_key,
)


def browser_keys() -> tuple[ec.EllipticCurvePrivateKey, str, bytes]:
    """Schlüssel, wie sie ein Browser beim Abonnieren erzeugt: ``p256dh`` (öffentlich) und ``auth``."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
    return private, b64url(public), os.urandom(16)


def browser_target(endpoint: str = "https://fcm.googleapis.com/fcm/send/abc:def",
                   ) -> tuple[Target, tuple[ec.EllipticCurvePrivateKey, bytes]]:
    """Abo-Ziel und die geheimen Teile des Browsers (zum Entschlüsseln in der Probe)."""
    private, p256dh, auth = browser_keys()
    return Target(endpoint, p256dh, b64url(auth)), (private, auth)


def test_browser_entschluesselt_den_inhalt():
    private, p256dh, auth = browser_keys()
    payload = json.dumps({"title": "Fußball", "body": "Morgen, 16:00 Uhr · Lena"}, ensure_ascii=False).encode()
    body = encrypt(payload, p256dh, b64url(auth))
    # Kopf nach RFC 8188: Salz (16), Datensatzgröße (4), Länge der Schlüssel-ID (1), Schlüssel des Servers (65)
    assert struct.unpack("!I", body[16:20])[0] == 4096 and body[20] == 65 and body[21] == 0x04
    assert http_ece.decrypt(body, private_key=private, auth_secret=auth, version="aes128gcm") == payload
    # jedes Mal neues Salz und neuer Absenderschlüssel
    assert encrypt(payload, p256dh, b64url(auth))[:86] != body[:86]


def test_verschluesselung_gleicht_der_referenz_bytegenau():
    _, p256dh, auth = browser_keys()
    sender = ec.generate_private_key(ec.SECP256R1())
    salt = os.urandom(16)
    ours = encrypt(b"Hallo", p256dh, b64url(auth), salt=salt, sender_key=sender)
    ref = http_ece.encrypt(b"Hallo", salt=salt, private_key=sender, dh=b64url_decode(p256dh), auth_secret=auth,
                           version="aes128gcm")
    assert ours == ref


def test_vapid_token_ist_gueltig_signiert():
    vapid = Vapid.from_private(generate_private_key(), "https://kalender.example")
    header = vapid.authorization("https://fcm.googleapis.com/fcm/send/abc", now=1_800_000_000)
    t_part, k_part = header.removeprefix("vapid ").split(", ")
    token, key = t_part.removeprefix("t="), k_part.removeprefix("k=")
    assert key == vapid.public_key and len(b64url_decode(key)) == 65
    head, claims, signature = token.split(".")
    assert json.loads(b64url_decode(head)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(b64url_decode(claims)) == {
        "aud": "https://fcm.googleapis.com", "exp": 1_800_000_000 + 12 * 3600, "sub": "https://kalender.example"}
    raw = b64url_decode(signature)
    assert len(raw) == 64
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(key))
    public.verify(encode_dss_signature(int.from_bytes(raw[:32]), int.from_bytes(raw[32:])),
                  f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_schluessel_im_format_des_deploy_skripts():
    # deploy.ps1 legt die 32 Byte des privaten Schlüssels als base64url ab (wie generate_private_key)
    raw = (12345678901234567890).to_bytes(32, "big")
    vapid = Vapid.from_private(b64url(raw), "mailto:x@localhost")
    assert vapid.private_key.private_numbers().private_value == 12345678901234567890
    with pytest.raises(ValueError):
        Vapid.from_private(b64url(b"zu kurz"), "mailto:x@localhost")


class PushService:
    """Attrappe eines Push-Dienstes (FCM) für ``httpx.MockTransport``."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, text="" if self.status < 400 else "kaputt")


def sender_with(service: PushService) -> WebPushSender:
    vapid = Vapid.from_private(generate_private_key(), "https://kalender.example")
    return WebPushSender(vapid, httpx.Client(transport=httpx.MockTransport(service)))


def test_versand_schickt_verschluesselt_mit_vapid():
    service = PushService()
    target, (private, auth) = browser_target()
    sender_with(service).send(target, {"title": "Fußball"}, ttl=3600)
    req = service.requests[0]
    assert str(req.url) == target.endpoint and req.method == "POST"
    assert req.headers["content-encoding"] == "aes128gcm"
    assert req.headers["ttl"] == "3600" and req.headers["urgency"] == "high"
    assert req.headers["authorization"].startswith("vapid t=")
    plain = http_ece.decrypt(req.content, private_key=private, auth_secret=auth, version="aes128gcm")
    assert json.loads(plain) == {"title": "Fußball"}


def test_ttl_hoechstens_vier_wochen():
    service = PushService()
    target, _ = browser_target()
    sender_with(service).send(target, {}, ttl=90 * 24 * 3600)
    assert service.requests[0].headers["ttl"] == str(28 * 24 * 3600)


@pytest.mark.parametrize("status", [404, 410])
def test_abo_weg(status):
    target, _ = browser_target()
    with pytest.raises(PushGone):
        sender_with(PushService(status)).send(target, {}, ttl=60)


def test_push_dienst_gestoert():
    target, _ = browser_target()
    with pytest.raises(PushFailed, match="500"):
        sender_with(PushService(500)).send(target, {}, ttl=60)

    def offline(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("weg")

    vapid = Vapid.from_private(generate_private_key(), "https://kalender.example")
    with pytest.raises(PushFailed, match="nicht erreichbar"):
        WebPushSender(vapid, httpx.Client(transport=httpx.MockTransport(offline))).send(target, {}, ttl=60)
