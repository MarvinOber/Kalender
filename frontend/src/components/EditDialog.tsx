import { useEffect, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { CalEvent, Draft, EditableEvent, EditScope, Settings } from "../types";
import { DraftCard, missing, normalizeTimes } from "./ConfirmDialog";

interface Props {
  eventId: string;
  scope: EditScope;
  settings: Settings;
  onClose: () => void;
  onSaved: (event: CalEvent) => void;
  onError: (err: unknown) => void;
}

/** Bestehenden Termin bearbeiten – dieselbe Karte wie im Bestätigungsdialog. Erst „Speichern“ schreibt in Google. */
export function EditDialog({ eventId, scope, settings, onClose, onSaved, onError }: Props) {
  const [loaded, setLoaded] = useState<EditableEvent | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [tried, setTried] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .event(eventId, scope)
      .then((data) => {
        if (!alive) return;
        setLoaded(data);
        setDraft(normalizeTimes(data.draft));
      })
      .catch((err) => {
        if (!alive) return;
        onError(err);
        onClose();
      });
    return () => {
      alive = false;
    };
  }, [eventId, scope]); // eslint-disable-line react-hooks/exhaustive-deps

  const invalid = draft ? Object.keys(missing(draft)).length > 0 : true;
  const recurrence = loaded?.recurrence_editable ? "edit" : loaded?.series ? "locked" : "none";

  const save = async () => {
    setTried(true);
    if (!loaded || !draft || invalid) return;
    setSaving(true);
    try {
      // Unveränderte Wiederholung nicht mitschicken: Google behält dann auch gestrichene Einzeltermine
      const unchanged =
        !loaded.recurrence_editable || JSON.stringify(draft.recurrence) === JSON.stringify(loaded.draft.recurrence);
      const { event } = await api.update(loaded.id, draft, unchanged);
      onSaved(event);
    } catch (err) {
      onError(err);
    } finally {
      setSaving(false);
    }
  };

  const title = scope === "series" ? t("Serie bearbeiten") : t("Termin bearbeiten");
  return (
    <div className="overlay">
      <div className="sheet confirm" role="dialog" aria-modal="true" aria-label={title}>
        <header className="sheet-head">
          <h2>{title}</h2>
          <button className="icon" aria-label={t("Abbrechen")} onClick={onClose}>
            ×
          </button>
        </header>
        <div className="sheet-body">
          {draft ? (
            <DraftCard
              draft={draft}
              settings={settings}
              showErrors={tried}
              recurrence={recurrence}
              onChange={(patch) => setDraft((d) => (d ? { ...d, ...patch } : d))}
            />
          ) : (
            <p className="small">{t("Lade …")}</p>
          )}
        </div>
        <footer className="sheet-foot">
          <button className="btn" onClick={onClose}>
            {t("Abbrechen")}
          </button>
          <button className="btn primary" disabled={!draft || saving || (tried && invalid)} onClick={save}>
            {saving ? "…" : t("Speichern")}
          </button>
        </footer>
      </div>
    </div>
  );
}
