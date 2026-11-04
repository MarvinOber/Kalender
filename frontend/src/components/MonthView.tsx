import { useEffect, useRef, useState } from "react";
import { addDays, formatDay, hhmm } from "../dates";
import { locale, t } from "../i18n";
import { fitWeek, monthWeeks } from "../layout";
import type { CalEvent, Settings } from "../types";
import type { Range } from "../view";
import { eventStyle } from "./eventStyle";

interface Props {
  events: CalEvent[];
  range: Range;
  month: string; // YYYY-MM
  today: string;
  settings: Settings;
  onSelect: (e: CalEvent) => void;
  onDay: (day: string) => void;
}

// Höhen aus styles.css (.month-day, .month-ev, .month-more, je + Abstand), in rem
const DAY_HEAD_REM = 1.55;
const ITEM_REM = 1.4;
const MORE_REM = 1.1;
const GAP_REM = 0.1; // gap in .month-cell

/** Monatsübersicht: volle Wochen Mo–So, mehrtägige Termine als durchgehender Balken,
 *  je Tag so viele Termine wie hineinpassen, der Rest als „+n weitere“. */
export function MonthView({ events, range, month, today, settings, onSelect, onDay }: Props) {
  const weeks = range.days / 7;
  const grid = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState(4); // Platz für Termine je Tag, in rem

  useEffect(() => {
    const el = grid.current;
    if (!el) return;
    const measure = () => {
      const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      setRoom(el.clientHeight / weeks / rem - DAY_HEAD_REM);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [weeks]);

  const slots = Math.floor(room / ITEM_REM + 0.01);
  const slotsWithMore = Math.max(0, Math.floor((room - MORE_REM) / ITEM_REM + 0.01));
  const fitted = monthWeeks(events, range.start, weeks).map((week) => fitWeek(week, slots, slotsWithMore));
  const rows = { gridTemplateRows: `repeat(${weeks}, minmax(0, 1fr))` };

  return (
    <div className="month">
      <div className="month-head">
        {Array.from({ length: 7 }, (_, i) => (
          <div key={i} className="wd">
            {formatDay(addDays(range.start, i), locale(), { weekday: "short" })}
          </div>
        ))}
      </div>
      <div className="month-body">
        <div className="month-grid" ref={grid} style={rows}>
          {fitted.flatMap(({ cells }, w) =>
            cells.map(({ reserved, shown, more }, col) => {
              const d = addDays(range.start, w * 7 + col);
              const label = formatDay(d, locale(), d.endsWith("-01") ? { day: "numeric", month: "short" } : { day: "numeric" });
              return (
                <div
                  key={d}
                  className={`month-cell ${d === today ? "today" : ""} ${d < today ? "past" : ""} ${d.slice(0, 7) !== month ? "other" : ""}`}
                >
                  <button
                    className="month-day"
                    aria-label={formatDay(d, locale(), { weekday: "long", day: "numeric", month: "long" })}
                    onClick={() => onDay(d)}
                  >
                    <span className="dn">{label}</span>
                  </button>
                  {reserved > 0 && <div className="month-lanes" style={{ height: `${reserved * ITEM_REM - GAP_REM}rem` }} />}
                  {shown.map(({ event, allDay }) => (
                    <button
                      key={event.id}
                      className={`ev month-ev ${allDay ? "full" : ""}`}
                      style={eventStyle(event, settings)}
                      onClick={() => onSelect(event)}
                    >
                      {!allDay && <span className="ev-time">{hhmm(event.start)}</span>}
                      <span className="ev-title">{event.title}</span>
                    </button>
                  ))}
                  {more > 0 && (
                    <button className="month-more" onClick={() => onDay(d)}>
                      +{more} {t("weitere")}
                    </button>
                  )}
                </div>
              );
            }),
          )}
        </div>
        <div className="month-bars" style={rows}>
          {fitted.flatMap(({ bars }, w) =>
            bars.map(({ event, allDay, startCol, span, lane, continuesBefore, continuesAfter }) => (
              <button
                key={`${w}-${event.id}`}
                className={`ev month-ev month-bar ${allDay ? "full" : ""} ${continuesBefore ? "cont-left" : ""} ${continuesAfter ? "cont-right" : ""}`}
                style={{
                  ...eventStyle(event, settings),
                  gridRow: w + 1,
                  gridColumn: `${startCol + 1} / span ${span}`,
                  marginTop: `${DAY_HEAD_REM + lane * ITEM_REM}rem`,
                }}
                onClick={() => onSelect(event)}
              >
                {!allDay && !continuesBefore && <span className="ev-time">{hhmm(event.start)}</span>}
                <span className="ev-title">{event.title}</span>
              </button>
            )),
          )}
        </div>
      </div>
    </div>
  );
}
