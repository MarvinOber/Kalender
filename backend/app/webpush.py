"""Web Push ohne SDK: VAPID (RFC 8292), verschlüsselter Inhalt (RFC 8291, ``aes128gcm``), Versand per httpx.

Der Browser liefert beim Abonnieren eine Adresse (``endpoint``) seines Push-Dienstes und zwei Schlüssel. Chrome auf
Android stellt über Firebase Cloud Messaging zu – der Server spricht trotzdem nur den offenen Standard und braucht
kein Firebase-Projekt: ``POST endpoint`` mit verschlüsseltem Inhalt und einem signierten VAPID-Token.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
MAX_TTL = 28 * 24 * 3600  # FCM hält Nachrichten höchstens 4 Wochen


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def receiver_key(p256dh: str) -> ec.EllipticCurvePublicKey:
    """Öffentlicher Schlüssel des Browsers; ``ValueError`` bei allem, was kein P-256-Punkt ist."""
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(p256dh))
    except (ValueError, TypeError) as exc:
        raise ValueError("p256dh ist kein gültiger Schlüssel") from exc


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Inhalt für ein Abo verschlüsseln (RFC 8291). ``salt`` und ``sender_key`` nur in Tests vorgeben."""
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _point(sender_key.public_key())
    salt = salt or os.urandom(16)
    shared = sender_key.exchange(ec.ECDH(), receiver_key(p256dh))
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    # ein einziger Datensatz: Inhalt, Trennbyte 0x02 („letzter Datensatz“), kein Auffüllen
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


def generate_private_key() -> str:
    """Neuer VAPID-Schlüssel als base64url der 32 Byte (dasselbe Format erzeugt ``scripts/deploy.ps1``)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64url(key.private_numbers().private_value.to_bytes(32, "big"))


@dataclass(frozen=True)
class Vapid:
    """Server-Schlüssel: Der Browser bindet das Abo an den öffentlichen Teil, jeder Versand trägt eine Signatur."""

    private_key: ec.EllipticCurvePrivateKey
    subject: str  # Kontakt für den Push-Dienst (https: oder mailto:)

    @classmethod
    def from_private(cls, private_b64: str, subject: str) -> Vapid:
        raw = b64url_decode(private_b64)
        if len(raw) != 32:
            raise ValueError("VAPID-Schlüssel: 32 Byte als base64url erwartet")
        return cls(ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1()), subject)

    @property
    def public_key(self) -> str:
        """``applicationServerKey`` für ``pushManager.subscribe`` im Browser."""
        return b64url(_point(self.private_key.public_key()))

    def authorization(self, endpoint: str, now: float | None = None) -> str:
        parts = urlsplit(endpoint)
        claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
                  "sub": self.subject}

        def segment(data: dict[str, Any]) -> str:
            return b64url(json.dumps(data, separators=(",", ":")).encode())

        signing_input = f"{segment({'typ': 'JWT', 'alg': 'ES256'})}.{segment(claims)}"
        r, s = decode_dss_signature(self.private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        token = f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        return f"vapid t={token}, k={self.public_key}"


class PushGone(Exception):
    """Das Abo gibt es nicht mehr (404/410) – z. B. Benachrichtigungen abgeschaltet oder Browserdaten gelöscht."""


class PushFailed(Exception):
    """Vorübergehender Fehler des Push-Dienstes; der nächste Lauf versucht es erneut."""


@dataclass(frozen=True)
class Target:
    endpoint: str
    p256dh: str
    auth: str


class PushSender(Protocol):
    public_key: str

    def send(self, target: Target, message: dict[str, Any], ttl: int) -> None: ...


class WebPushSender:
    def __init__(self, vapid: Vapid, client: httpx.Client | None = None) -> None:
        self._vapid = vapid
        self._client = client or httpx.Client(timeout=15)
        self.public_key = vapid.public_key

    def send(self, target: Target, message: dict[str, Any], ttl: int) -> None:
        body = encrypt(json.dumps(message, ensure_ascii=False).encode(), target.p256dh, target.auth)
        headers = {
            "Authorization": self._vapid.authorization(target.endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(max(0, min(ttl, MAX_TTL))),
            # „high“: Android stellt sofort zu, auch im Ruhemodus (Doze) – Erinnerungen sollen pünktlich kommen
            "Urgency": "high",
        }
        try:
            resp = self._client.post(target.endpoint, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise PushFailed(f"Push-Dienst nicht erreichbar ({type(exc).__name__})") from exc
        if resp.status_code in (404, 410):
            raise PushGone()
        if resp.status_code >= 400:
            raise PushFailed(f"Push-Dienst meldet {resp.status_code}: {resp.text[:200]}")
