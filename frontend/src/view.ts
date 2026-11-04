import { addDays, addMonths, daysBetween, firstOfMonth, mondayOf } from "./dates";

/** Terminliste der nächsten Tage, Wochenraster oder Monatsübersicht. */
export type View = "list" | "week" | "month";

export const VIEWS: View[] = ["list", "week", "month"];
export const VIEW_LABELS: Record<View, string> = { list: "Termine", week: "Woche", month: "Monat" };
export const LIST_DAYS = 31;

const KEY = "familienkalender.view";

/** Angezeigte Tage ab `start`. */
export interface Range {
  start: string;
  days: number;
}

/**
 * Liste: 31 Tage ab dem Anker (meist heute); Woche ab Montag;
 * Monat in vollen Wochen vom Montag vor dem Ersten bis zum Sonntag nach dem Letzten.
 */
export function rangeOf(view: View, anchor: string): Range {
  if (view === "list") return { start: anchor, days: LIST_DAYS };
  if (view === "week") return { start: mondayOf(anchor), days: 7 };
  const first = firstOfMonth(anchor);
  const start = mondayOf(first);
  const last = addDays(addMonths(first, 1), -1);
  return { start, days: daysBetween(start, mondayOf(last)) + 7 };
}

export function inRange(range: Range, iso: string): boolean {
  const day = iso.slice(0, 10);
  return day >= range.start && day < addDays(range.start, range.days);
}

/** Gleicher Zeitraum – für „Heute“, den Tageswechsel und die Rückkehr nach Leerlauf. Die Liste beginnt dann am selben Tag. */
export function samePeriod(view: View, a: string, b: string): boolean {
  if (view === "list") return a === b;
  return view === "month" ? a.slice(0, 7) === b.slice(0, 7) : mondayOf(a) === mondayOf(b);
}

/** 31 Tage, eine Woche bzw. einen Monat vor oder zurück. */
export function step(view: View, anchor: string, dir: number): string {
  if (view === "list") return addDays(anchor, dir * LIST_DAYS);
  return view === "month" ? addMonths(anchor, dir) : addDays(mondayOf(anchor), dir * 7);
}

/** Die Ansicht bleibt im Gerät gespeichert; ohne Eintrag gilt die Woche. */
export function loadView(): View {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw && (VIEWS as string[]).includes(raw)) return raw as View;
  } catch {
    /* gesperrter Speicher */
  }
  return "week";
}

export function saveView(view: View): void {
  try {
    localStorage.setItem(KEY, view);
  } catch {
    /* privater Modus: Ansicht gilt dann nur bis zum Neuladen */
  }
}

/** Schlüssel eines Zeitraums – damit erkennt die App, ob die angezeigten Termine zum aktuellen Zeitraum gehören. */
export function rangeKey(range: Range): string {
  return `${range.start}/${range.days}`;
}

/**
 * Ladezustand des angezeigten Zeitraums:
 * „loading“ – seine Termine sind noch nicht da (erster Start, gerade geblättert), es wird noch geladen;
 * „refreshing“ – sie sind da und werden im Hintergrund aktualisiert;
 * „missing“ – sie sind nicht da und der letzte Versuch ist fehlgeschlagen; „idle“ – alles aktuell.
 */
export type LoadState = "idle" | "loading" | "refreshing" | "missing";

export function loadState(current: string, loaded: string, pending: boolean, failed: boolean): LoadState {
  if (loaded === current) return pending ? "refreshing" : "idle";
  // Vor der ersten Anfrage (und zwischen Blättern und Anfrage) zählt das schon als Laden – kein „Keine Termine“-Blitzen
  return pending || !failed ? "loading" : "missing";
}
