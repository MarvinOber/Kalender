import { useState } from "react";
import { api } from "../api";
import { addDays, formatDay, hhmm } from "../dates";
import { locale, t } from "../i18n";
import type { CalEvent, EditScope, Settings } from "../types";
import { eventStyle, personNames, tagNames } from "./eventStyle";

interface Props {
  event: CalEvent;
  settings: Settings;
  onClose: () => void;
  onEdit: (scope: EditScope) => void;
  onDeleted: () => void;
  onError: (err: unknown) => void;
}

/** Rückfrage unten im Blatt: bei Serien „nur dieser oder alle“, sonst eine einfache Bestätigung. */
type Ask = null | "edit" | "delete";

export function EventDetails({ event, settings, onClose, onEdit, onDeleted, onError }: Props) {
  const [ask, setAsk] = useState<Ask>(null);
  const [deleting, setDeleting] = useState(false);
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

  const remove = async (scope: EditScope) => {
    setDeleting(true);
    try {
      await api.remove(event.id, scope);
      onDeleted();
    } catch (err) {
      onError(err);
      setDeleting(false);
    }
  };
  const run = (scope: EditScope) => (ask === "edit" ? onEdit(scope) : remove(scope));

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

        {ask === null && (
          <div className="actions">
            <button className="btn danger" onClick={() => setAsk("delete")}>
              🗑 {t("Löschen")}
            </button>
            <span className="spacer" />
            {event.link && (
              <a className="btn" href={event.link} target="_blank" rel="noreferrer">
                Google Kalender
              </a>
            )}
            <button className="btn" onClick={() => (event.recurring ? setAsk("edit") : onEdit("instance"))}>
              ✎ {t("Bearbeiten")}
            </button>
            <button className="btn primary" onClick={onClose}>
              {t("Schließen")}
            </button>
          </div>
        )}

        {ask !== null && event.recurring && (
          <div className="actions ask">
            <strong>{ask === "edit" ? t("Welche Termine bearbeiten?") : t("Welche Termine löschen?")}</strong>
            <span className="spacer" />
            <button className="btn" onClick={() => setAsk(null)}>
              {t("Zurück")}
            </button>
            <button className={`btn ${ask === "delete" ? "danger" : ""}`} disabled={deleting} onClick={() => run("instance")}>
              {t("Nur diesen Termin")}
            </button>
            <button className={`btn ${ask === "delete" ? "danger" : ""}`} disabled={deleting} onClick={() => run("series")}>
              {t("Ganze Serie")}
            </button>
          </div>
        )}

        {ask === "delete" && !event.recurring && (
          <div className="actions ask">
            <strong>{t("Termin wirklich löschen?")}</strong>
            <span className="spacer" />
            <button className="btn" onClick={() => setAsk(null)}>
              {t("Abbrechen")}
            </button>
            <button className="btn danger" disabled={deleting} onClick={() => remove("instance")}>
              {deleting ? "…" : t("Löschen")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
