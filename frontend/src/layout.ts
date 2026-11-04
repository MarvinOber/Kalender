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

export interface DayItem {
  event: CalEvent;
  allDay: boolean;
  continuesBefore: boolean;
  continuesAfter: boolean;
}

/** Monat und Terminliste: Termine je Tag ab `start`, mehrtägige an jedem Tag; ganztägige zuerst, dann nach Uhrzeit. */
export function dayItems(events: CalEvent[], start: string, days: number): DayItem[][] {
  const result: { item: DayItem; sort: string }[][] = Array.from({ length: days }, () => []);
  for (const event of events) {
    const startDay = daysBetween(start, event.start);
    let endDay: number;
    if (event.all_day) endDay = daysBetween(start, addDays(event.end, -1));
    else {
      endDay = daysBetween(start, event.end);
      if (endDay > startDay && minutesOf(event.end) === 0) endDay--; // endet genau um Mitternacht
    }
    for (let d = Math.max(0, startDay); d <= Math.min(days - 1, endDay); d++) {
      const continuesBefore = d > startDay;
      const sort = event.all_day ? `0${event.start}` : `1${continuesBefore ? "00:00" : event.start.slice(11, 16)}`;
      const item = { event, allDay: event.all_day, continuesBefore, continuesAfter: d < endDay };
      result[d].push({ item, sort });
    }
  }
  return result.map((list) => list.sort((a, b) => a.sort.localeCompare(b.sort)).map((x) => x.item));
}

export interface MonthBar {
  event: CalEvent;
  allDay: boolean;
  startCol: number; // 0 = Montag der Woche
  span: number;
  lane: number; // Zeile unter der Tageszahl
  continuesBefore: boolean; // beginnt vor dieser Woche
  continuesAfter: boolean; // endet nach dieser Woche
}

export interface MonthWeek {
  bars: MonthBar[]; // mehrtägige Termine als ein Balken
  singles: DayItem[][]; // je Wochentag die eintägigen Termine
}

/** Monatsübersicht: je Woche mehrtägige Termine als Balken (ohne Überlappung in Bahnen), eintägige je Tag. */
export function monthWeeks(events: CalEvent[], start: string, weeks: number): MonthWeek[] {
  const days = dayItems(events, start, weeks * 7);
  return Array.from({ length: weeks }, (_, w) => {
    const week = days.slice(w * 7, w * 7 + 7);
    const bars = new Map<string, MonthBar>();
    const singles = week.map((list, col) =>
      list.filter((item) => {
        if (!item.continuesBefore && !item.continuesAfter) return true;
        const bar = bars.get(item.event.id);
        if (bar) {
          bar.span = col - bar.startCol + 1;
          bar.continuesAfter = item.continuesAfter && col === 6;
        } else {
          bars.set(item.event.id, {
            event: item.event,
            allDay: item.allDay,
            startCol: col,
            span: 1,
            lane: 0,
            continuesBefore: item.continuesBefore,
            continuesAfter: item.continuesAfter && col === 6,
          });
        }
        return false;
      }),
    );
    const sorted = [...bars.values()].sort(
      (a, b) =>
        a.startCol - b.startCol ||
        b.span - a.span ||
        Number(b.allDay) - Number(a.allDay) ||
        a.event.start.localeCompare(b.event.start),
    );
    const lanes: number[] = []; // letzte belegte Spalte je Bahn
    for (const bar of sorted) {
      let lane = lanes.findIndex((end) => end < bar.startCol);
      if (lane < 0) lane = lanes.push(-1) - 1;
      lanes[lane] = bar.startCol + bar.span - 1;
      bar.lane = lane;
    }
    return { bars: sorted, singles };
  });
}

export interface FittedWeek {
  bars: MonthBar[]; // sichtbare Balken
  cells: { reserved: number; shown: DayItem[]; more: number }[]; // reserved = Bahnen für Balken
}

/** Was in eine Woche passt: `slots` Zeilen je Tag, `slotsWithMore` wenn noch „+n weitere“ hineinmuss. */
export function fitWeek(week: MonthWeek, slots: number, slotsWithMore: number): FittedWeek {
  const covers = (bar: MonthBar, col: number) => col >= bar.startCol && col < bar.startCol + bar.span;
  const cap = Array.from({ length: 7 }, (_, col) => {
    const lanes = Math.max(0, ...week.bars.filter((b) => covers(b, col)).map((b) => b.lane + 1));
    return lanes + week.singles[col].length <= slots ? slots : slotsWithMore;
  });
  let visible = week.bars;
  for (;;) {
    visible = week.bars.filter((b) => cap.slice(b.startCol, b.startCol + b.span).every((c) => b.lane < c));
    // Ein ausgeblendeter Balken braucht an jedem seiner Tage die Zeile „+n weitere“
    let changed = false;
    for (const b of week.bars) {
      if (visible.includes(b)) continue;
      for (let col = b.startCol; col < b.startCol + b.span; col++) {
        if (cap[col] !== slotsWithMore) {
          cap[col] = slotsWithMore;
          changed = true;
        }
      }
    }
    if (!changed) break;
  }
  const cells = week.singles.map((singles, col) => {
    const here = week.bars.filter((b) => covers(b, col));
    const reserved = Math.max(0, ...visible.filter((b) => covers(b, col)).map((b) => b.lane + 1));
    const shown = singles.slice(0, Math.max(0, cap[col] - reserved));
    const hiddenBars = here.filter((b) => !visible.includes(b)).length;
    return { reserved, shown, more: hiddenBars + singles.length - shown.length };
  });
  return { bars: visible, cells };
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
