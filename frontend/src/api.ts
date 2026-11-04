import { t } from "./i18n";
import type { CalEvent, Draft, EditableEvent, EditScope, Me, ModelInfo, ParseResult, Settings, Weather } from "./types";

/** Fehler der API mit Code (z. B. „reauth“, „model_unavailable“) und verständlicher Meldung. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

/**
 * Meldung, wenn die Antwort kein JSON des Backends ist – meist von Cloud Run selbst (504 nach 120 s, 502/503 beim
 * Neustart). Das Backend bricht Modellaufrufe vorher mit eigener Meldung ab; das hier ist das Netz darunter.
 */
export function httpErrorMessage(status: number): string {
  if (status === 504 || status === 408) return t("Der Server hat nicht rechtzeitig geantwortet. Bitte noch einmal versuchen.");
  if (status === 502 || status === 503) return t("Der Server ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen.");
  if (status === 413) return t("Die Datei ist zu groß.");
  return `${t("Unerwarteter Fehler")} (${status}). ${t("Bitte noch einmal versuchen.")}`;
}

async function request<T>(method: string, path: string, body?: BodyInit | object): Promise<T> {
  const headers: Record<string, string> = { "X-Kalender": "1" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let resp: Response;
  try {
    resp = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "offline", t("Keine Verbindung zum Server. Bitte Netzwerk prüfen."));
  }
  if (!resp.ok) {
    let code = "error";
    let message = httpErrorMessage(resp.status);
    try {
      const data = await resp.json();
      code = data.code || code;
      message = data.message || message;
    } catch {
      /* keine JSON-Antwort */
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as T;
}

export const api = {
  me: () => request<Me>("GET", "/api/me"),
  settings: () => request<Settings>("GET", "/api/settings"),
  saveSettings: (s: Settings) => request<Settings>("PUT", "/api/settings", s),
  weather: () => request<Weather>("GET", "/api/weather"),
  models: () => request<{ models: ModelInfo[] }>("GET", "/api/models"),
  calendars: () =>
    request<{ calendars: { id: string; summary: string; primary: boolean }[] }>("GET", "/api/calendars"),
  events: (start: string, days = 7) =>
    request<{ events: CalEvent[]; fetched_at: string }>(
      "GET",
      `/api/events?start=${encodeURIComponent(start)}&days=${days}`,
    ),
  voice: (wav: Blob) => {
    const form = new FormData();
    form.append("audio", wav, "aufnahme.wav");
    return request<ParseResult>("POST", "/api/voice", form);
  },
  photo: (image: Blob) => {
    const form = new FormData();
    form.append("image", image, "foto.jpg"); // das Format erkennt der Server am Inhalt
    return request<ParseResult>("POST", "/api/photo", form);
  },
  parse: (text: string) => request<ParseResult>("POST", "/api/parse", { text }),
  create: (events: Draft[]) => request<{ created: CalEvent[] }>("POST", "/api/events", { events }),
  event: (id: string, scope: EditScope) =>
    request<EditableEvent>("GET", `/api/events/${encodeURIComponent(id)}?scope=${scope}`),
  update: (id: string, draft: Draft, recurrenceUnchanged: boolean) =>
    request<{ event: CalEvent }>("PUT", `/api/events/${encodeURIComponent(id)}`, {
      draft,
      recurrence_unchanged: recurrenceUnchanged,
    }),
  remove: (id: string, scope: EditScope) =>
    request<{ ok: boolean }>("DELETE", `/api/events/${encodeURIComponent(id)}?scope=${scope}`),
  logout: () => request<{ ok: boolean }>("POST", "/auth/logout"),
};
