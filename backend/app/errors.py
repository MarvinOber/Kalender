"""Fehler mit Code und verständlicher Meldung – die Oberfläche zeigt ``message`` und reagiert auf ``code``."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ReauthRequired(AppError):
    def __init__(self, message: str = "Die Google-Anmeldung ist abgelaufen. Bitte neu anmelden.") -> None:
        super().__init__(401, "reauth", message)


class ModelUnavailable(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(502, "model_unavailable", message)


class ModelTimeout(AppError):
    """Das Modell hat die Frist überschritten – eigene Meldung statt des nackten 504 von Cloud Run."""

    def __init__(self, message: str) -> None:
        super().__init__(504, "model_timeout", message)


class CalendarError(AppError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(status, "calendar_error", message)
