import { Fragment } from "react";
import { addDays, formatDay, hhmm, minutesOf } from "../dates";
import { locale, t } from "../i18n";
import { dayItems } from "../layout";
import type { CalEvent, Settings } from "../types";
import { eventStyle, personNames, tagNames } from "./eventStyle";

interface Props {
  events: CalEvent[];
  start: string;
  days: number;
  today: string;
  nowMinutes: number;
  settings: Settings;
  onSelect: (e: CalEvent) => void;
}

/** Ansicht „Termine“: alle Termine der nächsten Tage als Liste, ein Abschnitt je Tag mit Terminen. */
export function AgendaView({ events, start, days, today, nowMinutes, settings, onSelect }: Props) {
  // Mehrtägige ganztägige Termine (Ferien) nur einmal am ersten sichtbaren Tag, mit „bis …“
  const list = dayItems(events, start, days)
    .map((items, i) => ({ d: addDays(start, i), items: items.filter((x) => !(x.allDay && x.continuesBefore && i > 0)) }))
    .filter(({ items }) => items.length > 0);
  return (
    <div className="agenda">
      {list.length === 0 && <div className="empty">{t("Keine Termine")}</div>}
      {list.map(({ d, items }) => {
        const nowIndex =
          d === today ? items.findIndex((x) => !x.allDay && !x.continuesBefore && minutesOf(x.event.start) > nowMinutes) : -2;
        const hasTimed = items.some((x) => !x.allDay);
        return (
          <section key={d} className={`agenda-day ${d === today ? "today" : ""} ${d < today ? "past" : ""}`}>
            <h2>
              <span className="wd">{formatDay(d, locale(), { weekday: "long" })}</span>
              <span className="dn">{formatDay(d, locale(), { day: "numeric", month: "long" })}</span>
            </h2>
            <div className="agenda-items">
              {items.map(({ event, allDay, continuesBefore, continuesAfter }, idx) => (
                <Fragment key={event.id}>
                  {idx === nowIndex && <div className="now-row" />}
                  <button
                    className={`ev agenda-ev ${allDay ? "allday-ev" : ""}`}
                    style={eventStyle(event, settings)}
                    onClick={() => onSelect(event)}
                  >
                    <span className="ev-time">
                      {allDay
                        ? continuesAfter
                          ? `${t("bis")} ${formatDay(addDays(event.end, -1), locale(), { day: "numeric", month: "long" })}`
                          : t("ganztägig")
                        : `${continuesBefore ? "…" : hhmm(event.start)}–${continuesAfter ? "…" : hhmm(event.end)}`}
                    </span>
                    <span className="ev-title">{event.title}</span>
                    <Meta event={event} settings={settings} />
                  </button>
                </Fragment>
              ))}
              {d === today && nowIndex === -1 && hasTimed && <div className="now-row" />}
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
