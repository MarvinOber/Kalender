import type { CalEvent } from "./types";

/** Mehrfachauswahl: innerhalb einer Gruppe genügt ein Treffer, beide Gruppen zusammen müssen passen. */
export interface Filter {
  persons: string[];
  tags: string[];
}

const KEY = "familienkalender.filter";
export const EMPTY_FILTER: Filter = { persons: [], tags: [] };

export function matches(event: CalEvent, filter: Filter): boolean {
  if (filter.persons.length && !event.persons.some((p) => filter.persons.includes(p))) return false;
  if (filter.tags.length && !event.tags.some((t) => filter.tags.includes(t))) return false;
  return true;
}

export function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

/** Der Filter bleibt im Gerät gespeichert – das Wand-Tablet zeigt nach einem Neustart dieselbe Auswahl. */
export function loadFilter(): Filter {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (raw && Array.isArray(raw.persons) && Array.isArray(raw.tags)) return { persons: raw.persons, tags: raw.tags };
  } catch {
    /* gesperrter Speicher oder kaputter Eintrag */
  }
  return EMPTY_FILTER;
}

export function saveFilter(filter: Filter): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(filter));
  } catch {
    /* privater Modus: Filter gilt dann nur bis zum Neuladen */
  }
}

/** Gespeicherte Kennungen verwerfen, die es nach einer Änderung der Einstellungen nicht mehr gibt. */
export function pruneFilter(filter: Filter, personIds: string[], tagIds: string[]): Filter {
  return {
    persons: filter.persons.filter((p) => personIds.includes(p)),
    tags: filter.tags.filter((t) => tagIds.includes(t)),
  };
}
