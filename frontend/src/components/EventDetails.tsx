import { addDays, formatDay, hhmm } from "../dates";
import { locale, t } from "../i18n";
import type { CalEvent, Settings } from "../types";
import { eventStyle, personNames, tagNames } from "./eventStyle";

export function EventDetails({ event, settings, onClose }: { event: CalEvent; settings: Settings; onClose: () => void }) {
  const day = (iso: string) => formatDay(iso, locale(), { weekday: "long", day: "numeric", month: "long" });
  let when: string;
  if (event.all_day) {
    const last = addDays(event.end, -1);
    when = last > event.start ? `${day(event.start)} – ${day(last)}` : `${day(event.start)}, ${t("ganztägig")}`;
  } else if (event.start.slice(0, 10) === event.end.slice(0, 10)) {
    when = `${day(event.start)}, ${hhmm(event.start)}–${hhmm(event.end)}`;
  } else {
    when = `${day(event.start)} ${hhmm(event.start)} – ${day(event.end)} ${hhmm(event.end)}`;
  }
  const who = personNames(event.persons, settings);
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet details" style={eventStyle(event, settings)} onClick={(e) => e.stopPropagation()}>
        <h2>{event.title}</h2>
        <p className="when">
          {when}
          {event.recurring && " · ↻"}
        </p>
        {event.location && <p>📍 {event.location}</p>}
        {who && <p>👤 {who}</p>}
        {event.tags.length > 0 && (
          <p className="tags">
            {tagNames(event.tags, settings).map((n) => (
              <span key={n} className="chip tag on">
                #{n}
              </span>
            ))}
          </p>
        )}
        {event.description && <p className="desc">{event.description}</p>}
        <div className="actions">
          {event.link && (
            <a className="btn" href={event.link} target="_blank" rel="noreferrer">
              Google Kalender
            </a>
          )}
          <button className="btn primary" onClick={onClose}>
            {t("Schließen")}
          </button>
        </div>
      </div>
    </div>
  );
}
