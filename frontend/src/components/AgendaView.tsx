import { Fragment } from "react";
import { addDays, formatDay, hhmm } from "../dates";
import { locale, t } from "../i18n";
import { allDayBars, timedSegments } from "../layout";
import type { CalEvent, Settings } from "../types";
import { eventStyle, personNames, tagNames } from "./eventStyle";

interface Props {
  events: CalEvent[];
  monday: string;
  today: string;
  nowMinutes: number;
  settings: Settings;
  onSelect: (e: CalEvent) => void;
}

/** Ansicht „Termine“: die Termine der Woche als Liste, ein Abschnitt je Tag mit Terminen – gut lesbar auch im Hochformat. */
export function AgendaView({ events, monday, today, nowMinutes, settings, onSelect }: Props) {
  const segments = timedSegments(events, monday);
  const bars = allDayBars(events, monday);
  const days = Array.from({ length: 7 }, (_, i) => ({
    i,
    d: addDays(monday, i),
    allDay: bars.filter((b) => b.startCol <= i && b.startCol + b.span > i).map((b) => b.event),
    timed: [...segments[i]].sort((a, b) => a.start - b.start),
  })).filter(({ allDay, timed }) => allDay.length > 0 || timed.length > 0);
  return (
    <div className="agenda">
      {days.length === 0 && <div className="empty">{t("Keine Termine")}</div>}
      {days.map(({ i, d, allDay, timed }) => {
        const nowIndex = d === today ? timed.findIndex((s) => s.start > nowMinutes) : -2;
        return (
          <section key={d} className={`agenda-day ${d === today ? "today" : ""} ${d < today ? "past" : ""}`}>
            <h2>
              <span className="wd">{formatDay(d, locale(), { weekday: "long" })}</span>
              <span className="dn">{formatDay(d, locale(), { day: "numeric", month: "long" })}</span>
            </h2>
            <div className="agenda-items">
              {allDay.map((e) => (
                <button key={e.id} className="ev agenda-ev allday-ev" style={eventStyle(e, settings)} onClick={() => onSelect(e)}>
                  <span className="ev-time">{t("ganztägig")}</span>
                  <span className="ev-title">{e.title}</span>
                  <Meta event={e} settings={settings} />
                </button>
              ))}
              {timed.map((s, idx) => (
                <Fragment key={`${s.event.id}-${i}`}>
                  {idx === nowIndex && <div className="now-row" />}
                  <button className="ev agenda-ev" style={eventStyle(s.event, settings)} onClick={() => onSelect(s.event)}>
                    <span className="ev-time">
                      {s.continuesBefore ? "…" : hhmm(s.event.start)}–{s.continuesAfter ? "…" : hhmm(s.event.end)}
                    </span>
                    <span className="ev-title">{s.event.title}</span>
                    <Meta event={s.event} settings={settings} />
                  </button>
                </Fragment>
              ))}
              {d === today && nowIndex === -1 && timed.length > 0 && <div className="now-row" />}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function Meta({ event, settings }: { event: CalEvent; settings: Settings }) {
  const who = personNames(event.persons, settings);
  const tags = tagNames(event.tags, settings);
  if (!who && !tags.length && !event.location) return null;
  return (
    <span className="ev-meta">
      {who && <span>{who}</span>}
      {tags.map((n) => (
        <span key={n} className="tagname">
          #{n}
        </span>
      ))}
      {event.location && <span>📍 {event.location}</span>}
    </span>
  );
}
