/**
 * Datumsrechnung auf „YYYY-MM-DD“-Zeichenketten. Die API liefert Wanduhrzeiten der Familien-Zeitzone,
 * deshalb rechnet die Oberfläche nie mit der Zeitzone des Geräts – nur „jetzt“ wird umgerechnet.
 */

const DAY_MS = 86_400_000;

function utc(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00Z`);
}

export function addDays(iso: string, days: number): string {
  return new Date(utc(iso).getTime() + days * DAY_MS).toISOString().slice(0, 10);
}

/** 0 = Montag … 6 = Sonntag */
export function weekdayIndex(iso: string): number {
  return (utc(iso).getUTCDay() + 6) % 7;
}

export function mondayOf(iso: string): string {
  return addDays(iso, -weekdayIndex(iso));
}

export function daysBetween(a: string, b: string): number {
  return Math.round((utc(b).getTime() - utc(a).getTime()) / DAY_MS);
}

export function isoWeek(iso: string): number {
  // Die Woche gehört zu dem Jahr, in dem ihr Donnerstag liegt; KW 1 enthält den 4. Januar.
  const thursday = utc(addDays(iso, 3 - weekdayIndex(iso)));
  const jan4 = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
  const week1Thursday = jan4.getTime() + (3 - ((jan4.getUTCDay() + 6) % 7)) * DAY_MS;
  return 1 + Math.round((thursday.getTime() - week1Thursday) / (7 * DAY_MS));
}

/** Jetzt in der Familien-Zeitzone: Datum und Minuten seit Mitternacht. */
export function nowIn(tz: string, now = new Date()): { date: string; minutes: number; time: string } {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: tz,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(now)
      .map((p) => [p.type, p.value]),
  );
  const hour = Number(parts.hour) % 24;
  const minute = Number(parts.minute);
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    minutes: hour * 60 + minute,
    time: `${String(hour).padStart(2, "0")}:${parts.minute}`,
  };
}

export function minutesOf(dateTime: string): number {
  const [h, m] = dateTime.slice(11, 16).split(":").map(Number);
  return h * 60 + m;
}

export function hhmm(dateTime: string): string {
  return dateTime.slice(11, 16);
}

export function formatDay(iso: string, locale: string, opts: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(locale, { timeZone: "UTC", ...opts }).format(utc(iso));
}

export function weekLabel(monday: string, locale: string): string {
  const sunday = addDays(monday, 6);
  const sameMonth = monday.slice(0, 7) === sunday.slice(0, 7);
  const from = formatDay(monday, locale, sameMonth ? { day: "numeric" } : { day: "numeric", month: "long" });
  const to = formatDay(sunday, locale, { day: "numeric", month: "long", year: "numeric" });
  return `${from} – ${to}`;
}
