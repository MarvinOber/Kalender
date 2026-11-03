import { addDays, formatDay, hhmm } from "../dates";
import { locale, t } from "../i18n";
import { allDayBars, timedSegments, visibleHours } from "../layout";
import type { CalEvent, Settings } from "../types";
import { eventStyle, personNames } from "./eventStyle";

interface Props {
  events: CalEvent[];
  monday: string;
  today: string;
  nowMinutes: number;
  settings: Settings;
  onSelect: (e: CalEvent) => void;
}

/** Querformat: sieben Spalten Mo–So, ganztägige Termine oben, Zeitraster ohne Scrollen. */
export function WeekView({ events, monday, today, nowMinutes, settings, onSelect }: Props) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const segments = timedSegments(events, monday);
  const bars = allDayBars(events, monday);
  const [first, last] = visibleHours(segments);
  const span = (last - first) * 60;
  const rows = Math.max(1, ...bars.map((b) => b.row + 1));
  const pct = (min: number) => `${((min - first * 60) / span) * 100}%`;
  const hours = Array.from({ length: last - first }, (_, i) => first + i);

  return (
    <div className="week">
      <div className="week-head">
        <div className="gutter" />
        {days.map((d) => (
          <div key={d} className={`day-head ${d === today ? "today" : ""} ${d < today ? "past" : ""}`}>
            <span className="wd">{formatDay(d, locale(), { weekday: "short" })}</span>
            <span className="dn">{formatDay(d, locale(), { day: "numeric" })}</span>
          </div>
        ))}
      </div>

      <div className="allday" style={{ gridTemplateRows: `repeat(${rows}, auto)` }}>
        <div className="gutter label" style={{ gridRow: `1 / span ${rows}` }}>
          {t("Ganztägig")}
        </div>
        {days.map((d, i) => (
          <div key={d} className={`allday-cell ${d === today ? "today" : ""}`} style={{ gridColumn: i + 2, gridRow: `1 / span ${rows}` }} />
        ))}
        {bars.map((b) => (
          <button
            key={`${b.event.id}-${b.startCol}`}
            className="ev allday-ev"
            style={{ ...eventStyle(b.event, settings), gridColumn: `${b.startCol + 2} / span ${b.span}`, gridRow: b.row + 1 }}
            onClick={() => onSelect(b.event)}
          >
            <span className="ev-title">{b.event.title}</span>
          </button>
        ))}
      </div>

      <div className="grid">
        <div className="gutter hours">
          {hours.map((h) => (
            <div key={h} className="hour" style={{ top: pct(h * 60) }}>
              {String(h).padStart(2, "0")}
            </div>
          ))}
        </div>
        {days.map((d, i) => (
          <div key={d} className={`col ${d === today ? "today" : ""} ${d < today ? "past" : ""}`}>
            {hours.map((h) => (
              <div key={h} className="line" style={{ top: pct(h * 60) }} />
            ))}
            {segments[i].map((s) => {
              const height = ((s.end - s.start) / span) * 100;
              return (
                <button
                  key={`${s.event.id}-${i}`}
                  className={`ev timed ${s.continuesBefore ? "cont-before" : ""}`}
                  style={{
                    ...eventStyle(s.event, settings),
                    top: pct(s.start),
                    height: `${height}%`,
                    left: `calc(${(s.col / s.cols) * 100}% + 2px)`,
                    width: `calc(${100 / s.cols}% - 4px)`,
                  }}
                  onClick={() => onSelect(s.event)}
                >
                  <span className="ev-body">
                    <span className="ev-time">{s.continuesBefore ? "…" : hhmm(s.event.start)}</span>
                    <span className="ev-title">{s.event.title}</span>
                    {s.event.persons.length > 0 && <span className="ev-who">{personNames(s.event.persons, settings)}</span>}
                  </span>
                </button>
              );
            })}
            {d === today && nowMinutes >= first * 60 && nowMinutes <= last * 60 && (
              <div className="now" style={{ top: pct(nowMinutes) }} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
