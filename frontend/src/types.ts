export interface Person {
  id: string;
  name: string;
  color: string;
  aliases: string[];
}

export interface EventTag {
  id: string;
  name: string;
  aliases: string[];
}

export interface Settings {
  calendar_id: string;
  transcription_model: string;
  extraction_model: string;
  photo_model: string; // Fotos von Kalenderseiten, Terminzetteln, Briefen
  language: "de" | "en";
  timezone: string;
  default_duration_min: number;
  persons: Person[];
  event_tags: EventTag[];
  weather_place: string; // leer = kein Wetter-Icon
  weather_lat: number;
  weather_lon: number;
}

/** Aktuelles Wetter am Ort aus den Einstellungen; ohne Ort nur `place: ""`. */
export interface Weather {
  place: string;
  temperature?: number;
  code?: number;
  is_day?: boolean;
}

/** Termin der Wochenansicht – Zeiten als Wanduhrzeit der Familien-Zeitzone. */
export interface CalEvent {
  id: string;
  title: string;
  all_day: boolean;
  start: string; // „YYYY-MM-DD“ bzw. „YYYY-MM-DDTHH:MM“
  end: string; // ganztägig: Folgetag des letzten Tages
  location: string;
  description: string;
  persons: string[];
  tags: string[];
  recurring: boolean;
  link: string;
}

export type Weekday = "MO" | "TU" | "WE" | "TH" | "FR" | "SA" | "SU";

export interface Recurrence {
  freq: "daily" | "weekly" | "monthly" | "yearly";
  interval: number;
  by_day: Weekday[];
  until: string | null;
  count: number | null;
}

/** Erkannter Termin im Bestätigungsdialog (Format der API). */
export interface Draft {
  title: string;
  all_day: boolean;
  start_date: string | null;
  start_time: string | null;
  end_date: string | null;
  end_time: string | null;
  location: string;
  description: string;
  persons: string[];
  tags: string[];
  recurrence: Recurrence | null;
  uncertain: string[];
  hint: string;
}

/** „instance“ = nur dieser Termin (bei Serien: dieses Vorkommen), „series“ = die ganze Serie. */
export type EditScope = "instance" | "series";

/** Termin im Bearbeiten-Dialog; `id` ist bei der ganzen Serie die Kennung der Serie. */
export interface EditableEvent {
  id: string;
  draft: Draft;
  recurrence_editable: boolean;
  series: boolean;
}

export interface ParseResult {
  transcript: string;
  events: Draft[];
  message: string;
}

export interface Me {
  email: string;
  name: string;
  auth_mode: "google" | "none";
  fake_llm: boolean;
}

export interface ModelInfo {
  id: string;
  name: string;
  audio: boolean;
  image: boolean;
  structured: boolean;
  prompt_price: string | null;
}
