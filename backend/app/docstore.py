"""Dokumentenspeicher: Firestore in der Cloud, eine JSON-Datei lokal und in Tests.

Beide Umsetzungen verstehen dieselben Pfade (``config/settings``, ``users/<email>``, ``push_subscriptions/<id>``).
Mehr als Lesen, Schreiben und Löschen ganzer Dokumente und das Auflisten einer Sammlung braucht der Kalender
nicht – die Termine selbst liegen in Google Calendar.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol


class DocStore(Protocol):
    def get(self, path: str) -> dict[str, Any] | None: ...
    def set(self, path: str, data: dict[str, Any]) -> None: ...
    def delete(self, path: str) -> None: ...
    def list_docs(self, collection: str) -> list[dict[str, Any]]: ...


class MemoryDocStore:
    """Für Tests: alles im Speicher."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._docs.get(path)
            return json.loads(json.dumps(doc)) if doc is not None else None

    def set(self, path: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._docs[path] = json.loads(json.dumps(data))
            self._persist()

    def delete(self, path: str) -> None:
        with self._lock:
            self._docs.pop(path, None)
            self._persist()

    def list_docs(self, collection: str) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(json.dumps(doc)) for path, doc in self._docs.items()
                    if path.partition("/")[0] == collection]

    def _persist(self) -> None:
        pass


class JsonDocStore(MemoryDocStore):
    """Lokaler Betrieb: eine JSON-Datei unter ``backend/data``."""

    def __init__(self, file: Path) -> None:
        super().__init__()
        self._file = file
        try:
            self._docs = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._docs = {}

    def _persist(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._docs, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._file)


class FirestoreDocStore:
    def __init__(self, project: str, database: str) -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project or None, database=database)

    @staticmethod
    def _key(path: str) -> str:
        # Firestore erlaubt „/“ nur als Trenner zwischen Sammlung und Dokument.
        collection, _, doc_id = path.partition("/")
        return f"{collection}/{doc_id.replace('/', '_')}"

    def get(self, path: str) -> dict[str, Any] | None:
        snap = self._db.document(self._key(path)).get()
        return snap.to_dict() if snap.exists else None

    def set(self, path: str, data: dict[str, Any]) -> None:
        self._db.document(self._key(path)).set(data)

    def delete(self, path: str) -> None:
        self._db.document(self._key(path)).delete()

    def list_docs(self, collection: str) -> list[dict[str, Any]]:
        return [snap.to_dict() for snap in self._db.collection(collection).stream()]


@lru_cache(maxsize=1)
def get_store() -> DocStore:
    from .server_config import get_config

    cfg = get_config()
    if cfg.cloud:
        return FirestoreDocStore(cfg.project, cfg.firestore_database)
    return JsonDocStore(cfg.data_dir / "store.json")
