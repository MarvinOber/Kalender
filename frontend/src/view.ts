import { addDays, addMonths, daysBetween, firstOfMonth, mondayOf } from "./dates";

/** Termine als Tagesliste, Wochenraster oder Monatsübersicht. */
export type View = "list" | "week" | "month";

export const VIEWS: View[] = ["list", "week", "month"];
export const VIEW_LABELS: Record<View, string> = { list: "Termine", week: "Woche", month: "Monat" };

const KEY = "familienkalender.view";

/** Angezeigte Tage ab `start` (Montag). */
export interface Range {
  start: string;
  days: number;
}

/** Woche ab Montag; Monat in vollen Wochen vom Montag vor dem Ersten bis zum Sonntag nach dem Letzten. */
export function rangeOf(view: View, anchor: string): Range {
  if (view !== "month") return { start: mondayOf(anchor), days: 7 };
  const first = firstOfMonth(anchor);
  const start = mondayOf(first);
  const last = addDays(addMonths(first, 1), -1);
  return { start, days: daysBetween(start, mondayOf(last)) + 7 };
}

export function inRange(range: Range, iso: string): boolean {
  const day = iso.slice(0, 10);
  return day >= range.start && day < addDays(range.start, range.days);
}

/** Gleiche Woche bzw. gleicher Monat – für „Heute“, den Tageswechsel und die Rückkehr nach Leerlauf. */
export function samePeriod(view: View, a: string, b: string): boolean {
  return view === "month" ? a.slice(0, 7) === b.slice(0, 7) : mondayOf(a) === mondayOf(b);
}

/** Eine Woche bzw. einen Monat vor oder zurück. */
export function step(view: View, anchor: string, dir: number): string {
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
