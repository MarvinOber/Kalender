import { useState } from "react";
import { api } from "../api";
import { toggle } from "../filter";
import { t } from "../i18n";
import type { CalEvent, Draft, ParseResult, Recurrence, Settings, Weekday } from "../types";
import { colorVar } from "./eventStyle";

interface Props {
  result: ParseResult;
  /** Adresse des Fotos (Object-URL), wenn die Termine von einem Foto stammen */
  photo?: string | null;
  settings: Settings;
  busy: boolean;
  onCancel: () => void;
  onRetry: () => void;
  onReparse: (text: string) => void;
  onCreated: (events: CalEvent[]) => void;
  onError: (err: unknown) => void;
}

const WEEKDAYS: [Weekday, string][] = [
  ["MO", "Mo"], ["TU", "Di"], ["WE", "Mi"], ["TH", "Do"], ["FR", "Fr"], ["SA", "Sa"], ["SU", "So"],
];

const EMPTY_DRAFT: Draft = {
  title: "", all_day: false, start_date: null, start_time: null, end_date: null, end_time: null,
  location: "", description: "", persons: [], tags: [], recurrence: null, uncertain: [], hint: "",
};

/** Was fehlt, damit der Termin angelegt werden kann (Feldname → Meldung). */
export function missing(d: Draft): Record<string, string> {
  const m: Record<string, string> = {};
  if (!d.title.trim()) m.title = t("Pflichtfeld");
  if (!d.start_date) m.start_date = t("Pflichtfeld");
  if (!d.all_day && !d.start_time) m.start_time = t("Pflichtfeld");
  if (d.end_date && d.start_date && d.end_date < d.start_date) m.end_date = t("Bitte prüfen");
  return m;
}

/**
 * Bestätigungsdialog: Transkript (bzw. Foto mit Abschrift) und je Termin eine bearbeitbare Karte.
 * Erst „Anlegen“ schreibt in Google.
 */
export function ConfirmDialog({ result, photo, settings, busy, onCancel, onRetry, onReparse, onCreated, onError }: Props) {
  const [drafts, setDrafts] = useState<Draft[]>(() => result.events.map(normalizeTimes));
  const [text, setText] = useState(result.transcript);
  const [saving, setSaving] = useState(false);
  const [tried, setTried] = useState(false);
  const [zoom, setZoom] = useState(false);
  const textChanged = text.trim() !== result.transcript.trim();

  const update = (i: number, patch: Partial<Draft>) =>
    setDrafts((list) =>
      list.map((d, j) =>
        j === i ? { ...d, ...patch, uncertain: d.uncertain.filter((f) => !(f in patch)) } : d,
      ),
    );

  const invalid = drafts.some((d) => Object.keys(missing(d)).length > 0);

  const create = async () => {
    setTried(true);
    if (invalid || !drafts.length) return;
    setSaving(true);
    try {
      const { created } = await api.create(drafts);
      onCreated(created);
    } catch (err) {
      onError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="overlay">
      <div className="sheet confirm" role="dialog" aria-modal="true" aria-label={t("Erkannte Termine")}>
        <header className="sheet-head">
          <h2>{t("Erkannte Termine")}</h2>
          <button className="icon" aria-label={t("Abbrechen")} onClick={onCancel}>
            ×
          </button>
        </header>

        <div className="sheet-body">
          {photo && (
            <button
              type="button"
              className={`photo-preview ${zoom ? "zoom" : ""}`}
              aria-label={zoom ? t("Foto verkleinern") : t("Foto vergrößern")}
              aria-pressed={zoom}
              onClick={() => setZoom((z) => !z)}
            >
              <img src={photo} alt={t("Foto")} />
            </button>
          )}
          <label className="transcript">
            <span>{photo ? t("Vom Foto gelesen") : result.transcript ? t("Gesagt") : t("Text eingeben")}</span>
            <textarea
              value={text}
              rows={photo ? 3 : 2}
              placeholder="z. B. Am Freitag um 16 Uhr hat Lena Fußball"
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          {(textChanged || !result.transcript) && text.trim() && (
            <button className="btn" disabled={busy} onClick={() => onReparse(text)}>
              {busy ? t("Verstehe …") : result.transcript ? t("Neu erkennen") : t("Erkennen")}
            </button>
          )}
          {result.message && <p className="notice">{result.message}</p>}

          {drafts.map((d, i) => (
            <DraftCard
              key={i}
              draft={d}
              settings={settings}
              showErrors={tried}
              onChange={(patch) => update(i, patch)}
              onRemove={() => setDrafts((list) => list.filter((_, j) => j !== i))}
            />
          ))}
          <button className="btn ghost add" onClick={() => setDrafts((list) => [...list, { ...EMPTY_DRAFT }])}>
            + {t("Termin hinzufügen")}
          </button>
        </div>

        <footer className="sheet-foot">
          <button className="btn" onClick={onCancel}>
            {t("Abbrechen")}
          </button>
          <button className="btn" onClick={onRetry}>
            {photo ? `📷 ${t("Neues Foto")}` : `🎤 ${t("Neu einsprechen")}`}
          </button>
          <button className="btn primary" disabled={saving || !drafts.length || (tried && invalid)} onClick={create}>
            {saving ? "…" : `${t("Anlegen")}${drafts.length > 1 ? ` (${drafts.length})` : ""}`}
          </button>
        </footer>
      </div>
    </div>
  );
}

export function normalizeTimes(d: Draft): Draft {
  return { ...d, start_time: d.start_time?.slice(0, 5) ?? null, end_time: d.end_time?.slice(0, 5) ?? null };
}

interface CardProps {
  draft: Draft;
  settings: Settings;
  showErrors: boolean;
  onChange: (patch: Partial<Draft>) => void;
  onRemove?: () => void;
  /** „locked“: Serie mit Regel, die sich hier nicht abbilden lässt; „none“: einzelner Termin einer Serie. */
  recurrence?: "edit" | "locked" | "none";
}

export function DraftCard({ draft: d, settings, showErrors, onChange, onRemove, recurrence = "edit" }: CardProps) {
  const errors = showErrors ? missing(d) : {};
  const cls = (field: string) => `field ${d.uncertain.includes(field) ? "unsure" : ""} ${errors[field] ? "error" : ""}`;
  const rec = d.recurrence;
  const setRec = (patch: Partial<Recurrence> | null) =>
    onChange({
      recurrence: patch === null ? null : { ...(rec ?? { freq: "weekly", interval: 1, by_day: [], until: null, count: null }), ...patch },
    });

  return (
    <article className="draft">
      <div className="draft-top">
        <label className={`${cls("title")} grow`}>
          <span>{t("Titel")}</span>
          <input value={d.title} onChange={(e) => onChange({ title: e.target.value })} />
          {errors.title && <em>{errors.title}</em>}
        </label>
        {onRemove && (
          <button className="icon danger" aria-label={t("Termin entfernen")} title={t("Termin entfernen")} onClick={onRemove}>
            🗑
          </button>
        )}
      </div>
      {d.hint && <p className="hint">⚠ {d.hint}</p>}

      <div className="row">
        <label className="switch">
          <input
            type="checkbox"
            checked={d.all_day}
            onChange={(e) => onChange({ all_day: e.target.checked, ...(e.target.checked ? { start_time: null, end_time: null } : {}) })}
          />
          <span>{t("Ganztägig")}</span>
        </label>
      </div>

      <div className="row">
        <label className={cls("start_date")}>
          <span>{t("Datum")}</span>
          <input type="date" value={d.start_date ?? ""} onChange={(e) => onChange({ start_date: e.target.value || null })} />
          {errors.start_date && <em>{errors.start_date}</em>}
        </label>
        {!d.all_day && (
          <>
            <label className={cls("start_time")}>
              <span>{t("Von")}</span>
              <input type="time" value={d.start_time ?? ""} onChange={(e) => onChange({ start_time: e.target.value || null })} />
              {errors.start_time && <em>{errors.start_time}</em>}
            </label>
            <label className={cls("end_time")}>
              <span>{t("Bis")}</span>
              <input
                type="time"
                value={d.end_time ?? ""}
                placeholder={`+${settings.default_duration_min} min`}
                onChange={(e) => onChange({ end_time: e.target.value || null })}
              />
            </label>
          </>
        )}
        <label className={cls("end_date")}>
          <span>
            {t("Bis")} ({t("Datum")})
          </span>
          <input type="date" value={d.end_date ?? ""} min={d.start_date ?? undefined} onChange={(e) => onChange({ end_date: e.target.value || null })} />
          {errors.end_date && <em>{errors.end_date}</em>}
        </label>
      </div>

      <div className="row">
        <label className={`${cls("location")} grow`}>
          <span>{t("Ort")}</span>
          <input value={d.location} onChange={(e) => onChange({ location: e.target.value })} />
        </label>
      </div>
      <label className="field">
        <span>{t("Beschreibung")}</span>
        <textarea rows={2} value={d.description} onChange={(e) => onChange({ description: e.target.value })} />
      </label>

      <div className={`${cls("persons")} chips`}>
        <span>{t("Personen")}</span>
        <div>
          {settings.persons.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`chip person ${d.persons.includes(p.id) ? "on" : ""}`}
              style={colorVar(p.color)}
              aria-pressed={d.persons.includes(p.id)}
              onClick={() => onChange({ persons: toggle(d.persons, p.id) })}
            >
              <i className="dot" />
              {p.name}
            </button>
          ))}
        </div>
      </div>
      <div className={`${cls("tags")} chips`}>
        <span>{t("Ereignisse")}</span>
        <div>
          {settings.event_tags.map((tag) => (
            <button
              key={tag.id}
              type="button"
              className={`chip tag ${d.tags.includes(tag.id) ? "on" : ""}`}
              aria-pressed={d.tags.includes(tag.id)}
              onClick={() => onChange({ tags: toggle(d.tags, tag.id) })}
            >
              #{tag.name}
            </button>
          ))}
        </div>
      </div>

      {recurrence === "locked" && (
        <div className="recurrence">
          <span>{t("Wiederholung")}</span>
          <p className="small">{t("Diese Wiederholung lässt sich nur in Google Kalender ändern; sie bleibt unverändert.")}</p>
        </div>
      )}
      {recurrence === "edit" && (
        <div className={`${cls("recurrence")} recurrence`}>
          <span>{t("Wiederholung")}</span>
          <div className="row">
            <select
              value={rec?.freq ?? ""}
              onChange={(e) => setRec(e.target.value ? { freq: e.target.value as Recurrence["freq"] } : null)}
            >
              <option value="">{t("keine")}</option>
              <option value="daily">{t("täglich")}</option>
              <option value="weekly">{t("wöchentlich")}</option>
              <option value="monthly">{t("monatlich")}</option>
              <option value="yearly">{t("jährlich")}</option>
            </select>
            {rec && (
              <>
                <label className="inline">
                  {t("alle")}
                  <input
                    type="number"
                    min={1}
                    max={99}
                    value={rec.interval}
                    onChange={(e) => setRec({ interval: Math.max(1, Number(e.target.value) || 1) })}
                  />
                </label>
                <label className="inline">
                  {t("bis")}
                  <input type="date" value={rec.until ?? ""} onChange={(e) => setRec({ until: e.target.value || null, count: null })} />
                </label>
              </>
            )}
          </div>
          {rec?.freq === "weekly" && (
            <div className="weekdays">
              {WEEKDAYS.map(([code, label]) => (
                <button
                  key={code}
                  type="button"
                  className={`chip ${rec.by_day.includes(code) ? "on" : ""}`}
                  onClick={() => setRec({ by_day: toggle(rec.by_day, code) as Weekday[] })}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
