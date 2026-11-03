import { addDays, daysBetween, minutesOf } from "./dates";
import type { CalEvent } from "./types";

export interface Segment {
  event: CalEvent;
  day: number; // 0 = Montag der angezeigten Woche
  start: number; // Minuten seit Mitternacht
  end: number;
  col: number; // Spalte bei Überschneidungen
  cols: number;
  continuesBefore: boolean;
  continuesAfter: boolean;
}

export interface AllDayBar {
  event: CalEvent;
  startCol: number;
  span: number;
  row: number;
}

const MIN_DURATION = 20; // sehr kurze Termine bleiben lesbar

/** Zeittermine je Wochentag zerschneiden (über Mitternacht) und Überschneidungen in Spalten legen. */
export function timedSegments(events: CalEvent[], monday: string): Segment[][] {
  const days: Segment[][] = Array.from({ length: 7 }, () => []);
  for (const event of events) {
    if (event.all_day) continue;
    const startDay = daysBetween(monday, event.start);
    const endDay = daysBetween(monday, event.end);
    const endMin = minutesOf(event.end);
    for (let d = Math.max(0, startDay); d <= Math.min(6, endDay); d++) {
      const start = d === startDay ? minutesOf(event.start) : 0;
      const end = d === endDay ? endMin : 24 * 60;
      if (d === endDay && endMin === 0 && endDay > startDay) continue; // endet genau um Mitternacht
      days[d].push({
        event,
        day: d,
        start,
        end: Math.max(end, start + MIN_DURATION),
        col: 0,
        cols: 1,
        continuesBefore: d > startDay,
        continuesAfter: d < endDay && !(d === endDay - 1 && endMin === 0),
      });
    }
  }
  return days.map(layoutColumns);
}

function layoutColumns(segments: Segment[]): Segment[] {
  const sorted = [...segments].sort((a, b) => a.start - b.start || b.end - a.end);
  let cluster: Segment[] = [];
  let clusterEnd = -1;
  const flush = () => {
    const columns: number[] = []; // Ende des letzten Termins je Spalte
    for (const s of cluster) {
      let col = columns.findIndex((end) => end <= s.start);
      if (col < 0) {
        col = columns.length;
        columns.push(0);
      }
      columns[col] = s.end;
      s.col = col;
    }
    for (const s of cluster) s.cols = columns.length;
    cluster = [];
  };
  for (const s of sorted) {
    if (s.start >= clusterEnd && cluster.length) flush();
    cluster.push(s);
    clusterEnd = Math.max(clusterEnd, s.end);
  }
  if (cluster.length) flush();
  return sorted;
}

/** Ganztägige Termine als Balken über die Woche, ohne Überlappung in Zeilen verteilt. */
export function allDayBars(events: CalEvent[], monday: string): AllDayBar[] {
  const rows: number[][] = [];
  const bars: AllDayBar[] = [];
  const sunday = addDays(monday, 6);
  const sorted = events
    .filter((e) => e.all_day)
    .sort((a, b) => a.start.localeCompare(b.start) || daysBetween(b.start, b.end) - daysBetween(a.start, a.end));
  for (const event of sorted) {
    const lastDay = addDays(event.end, -1);
    if (event.start > sunday || lastDay < monday) continue;
    const startCol = Math.max(0, daysBetween(monday, event.start));
    const endCol = Math.min(6, daysBetween(monday, lastDay));
    let row = rows.findIndex((cols) => cols.every((c) => c < startCol || c > endCol));
    if (row < 0) {
      row = rows.length;
      rows.push([]);
    }
    for (let c = startCol; c <= endCol; c++) rows[row].push(c);
    bars.push({ event, startCol, span: endCol - startCol + 1, row });
  }
  return bars;
}

/** Sichtbarer Stundenbereich: mindestens 7–21 Uhr, erweitert um frühere oder spätere Termine. */
export function visibleHours(days: Segment[][], from = 7, to = 21): [number, number] {
  let first = from;
  let last = to;
  for (const s of days.flat()) {
    first = Math.min(first, Math.floor(s.start / 60));
    last = Math.max(last, Math.ceil(s.end / 60));
  }
  return [Math.max(0, first), Math.min(24, last)];
}
