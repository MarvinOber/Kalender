import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import type { EventTag, Me, ModelInfo, Person, Settings } from "../types";

interface Props {
  settings: Settings;
  me: Me | null;
  onClose: () => void;
  onSaved: (s: Settings) => void;
  onError: (err: unknown) => void;
}

const PALETTE = ["#e8590c", "#1c7ed6", "#d6336c", "#2f9e44", "#7048e8", "#f08c00", "#0c8599", "#5c940d"];

const aliasText = (list: string[]) => list.join(", ");
const aliasList = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

/** Einstellungen für alle Geräte der Familie – gespeichert auf dem Server, wirksam ab der nächsten Anfrage. */
export function SettingsPanel({ settings, me, onClose, onSaved, onError }: Props) {
  const [s, setS] = useState<Settings>(() => structuredClone(settings));
  const [aliases, setAliases] = useState<Record<string, string>>({});
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [calendars, setCalendars] = useState<{ id: string; summary: string; primary: boolean }[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.models().then((r) => setModels(r.models)).catch(() => setModels([]));
    api.calendars().then((r) => setCalendars(r.calendars)).catch(() => undefined);
  }, []);

  const audioModels = useMemo(() => (models ?? []).filter((m) => m.audio), [models]);
  const structuredModels = useMemo(() => (models ?? []).filter((m) => m.structured), [models]);
  const timezones = useMemo(() => {
    try {
      return (Intl as any).supportedValuesOf("timeZone") as string[];
    } catch {
      return ["Europe/Berlin", "Europe/Vienna", "Europe/Zurich"];
    }
  }, []);

  // Zusätze als freier Text bearbeiten, erst beim Speichern in Listen zerlegen
  const aliasKey = (kind: "p" | "t", i: number) => `${kind}${i}`;
  const aliasValue = (kind: "p" | "t", i: number, list: string[]) => aliases[aliasKey(kind, i)] ?? aliasText(list);

  const setPerson = (i: number, patch: Partial<Person>) =>
    setS((x) => ({ ...x, persons: x.persons.map((p, j) => (j === i ? { ...p, ...patch } : p)) }));
  const setTag = (i: number, patch: Partial<EventTag>) =>
    setS((x) => ({ ...x, event_tags: x.event_tags.map((p, j) => (j === i ? { ...p, ...patch } : p)) }));

  // Offene Texte übernehmen – vor dem Speichern und bevor sich durch Entfernen die Reihenfolge ändert
  const flushed = (): Settings => ({
    ...s,
    persons: s.persons.map((p, i) => ({ ...p, aliases: aliasList(aliasValue("p", i, p.aliases)) })),
    event_tags: s.event_tags.map((x, i) => ({ ...x, aliases: aliasList(aliasValue("t", i, x.aliases)) })),
  });

  const remove = (kind: "persons" | "event_tags", i: number) => {
    const next = flushed();
    setAliases({});
    setS(kind === "persons" ? { ...next, persons: next.persons.filter((_, j) => j !== i) } : { ...next, event_tags: next.event_tags.filter((_, j) => j !== i) });
  };

  const save = async () => {
    const body = flushed();
    setSaving(true);
    try {
      onSaved(await api.saveSettings(body));
    } catch (err) {
      onError(err);
    } finally {
      setSaving(false);
    }
  };

  const logout = async () => {
    await api.logout().catch(() => undefined);
    window.location.href = "/";
  };

  return (
    <div className="overlay">
      <div className="sheet settings" role="dialog" aria-modal="true" aria-label={t("Einstellungen")}>
        <header className="sheet-head">
          <h2>{t("Einstellungen")}</h2>
          <button className="icon" aria-label={t("Schließen")} onClick={onClose}>
            ×
          </button>
        </header>
        <div className="sheet-body">
          <section>
            <h3>{t("Kalender")}</h3>
            <label className="field">
              <span>{t("Kalender-ID")}</span>
              <input list="calendars" value={s.calendar_id} onChange={(e) => setS({ ...s, calendar_id: e.target.value })} />
              <datalist id="calendars">
                {calendars.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.summary}
                    {c.primary ? " (Hauptkalender)" : ""}
                  </option>
                ))}
              </datalist>
            </label>
            {calendars.length > 0 && (
              <div className="chips">
                <div>
                  {calendars.map((c) => (
                    <button key={c.id} type="button" className={`chip ${s.calendar_id === c.id ? "on" : ""}`} onClick={() => setS({ ...s, calendar_id: c.id })}>
                      {c.summary}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section>
            <h3>{t("KI-Modelle")}</h3>
            <label className="field">
              <span>{t("Transkription (Audio)")}</span>
              <input list="audio-models" value={s.transcription_model} onChange={(e) => setS({ ...s, transcription_model: e.target.value })} />
              <ModelList id="audio-models" models={audioModels} />
            </label>
            <label className="field">
              <span>{t("Termin-Erkennung")}</span>
              <input list="structured-models" value={s.extraction_model} onChange={(e) => setS({ ...s, extraction_model: e.target.value })} />
              <ModelList id="structured-models" models={structuredModels} />
            </label>
            <p className="small">
              {models === null
                ? "Modellliste wird geladen …"
                : models.length
                  ? `OpenRouter-Modell-ID. Vorschläge: ${audioModels.length} Modelle mit Audio-Eingabe bzw. ${structuredModels.length} mit JSON-Schema.`
                  : "Modellliste nicht erreichbar – Modell-ID von openrouter.ai/models eintragen."}
              {models?.length && s.transcription_model && !audioModels.some((m) => m.id === s.transcription_model)
                ? " ⚠ Das Transkriptionsmodell nimmt laut Liste kein Audio an."
                : ""}
            </p>
          </section>

          <section>
            <h3>{t("Personen")}</h3>
            {s.persons.map((p, i) => (
              <div key={p.id || i} className="row item">
                <input type="color" aria-label={t("Farbe")} value={p.color} onChange={(e) => setPerson(i, { color: e.target.value })} />
                <input className="name" aria-label={t("Name")} value={p.name} onChange={(e) => setPerson(i, { name: e.target.value })} />
                <input
                  className="grow"
                  placeholder={`${t("Auch genannt")}: Mama, Mami`}
                  aria-label={t("Auch genannt")}
                  value={aliasValue("p", i, p.aliases)}
                  onChange={(e) => setAliases({ ...aliases, [aliasKey("p", i)]: e.target.value })}
                />
                <button className="icon danger" aria-label="Entfernen" onClick={() => remove("persons", i)}>
                  🗑
                </button>
              </div>
            ))}
            <button
              className="btn ghost"
              onClick={() => setS({ ...s, persons: [...s.persons, { id: "", name: "", color: PALETTE[s.persons.length % PALETTE.length], aliases: [] }] })}
            >
              + {t("Person hinzufügen")}
            </button>
            <p className="small">Gleiche Zusätze bei mehreren Personen („Kinder“) ordnen allen zu.</p>
          </section>

          <section>
            <h3>{t("Ereignisse")}</h3>
            {s.event_tags.map((x, i) => (
              <div key={x.id || i} className="row item">
                <input className="name" aria-label={t("Name")} value={x.name} onChange={(e) => setTag(i, { name: e.target.value })} />
                <input
                  className="grow"
                  placeholder={`${t("Hinweise für das Modell")}: Fußball, Training`}
                  aria-label={t("Hinweise für das Modell")}
                  value={aliasValue("t", i, x.aliases)}
                  onChange={(e) => setAliases({ ...aliases, [aliasKey("t", i)]: e.target.value })}
                />
                <button className="icon danger" aria-label="Entfernen" onClick={() => remove("event_tags", i)}>
                  🗑
                </button>
              </div>
            ))}
            <button className="btn ghost" onClick={() => setS({ ...s, event_tags: [...s.event_tags, { id: "", name: "", aliases: [] }] })}>
              + {t("Tag hinzufügen")}
            </button>
          </section>

          <section>
            <h3>{t("Allgemein")}</h3>
            <div className="row">
              <label className="field">
                <span>{t("Sprache")}</span>
                <select value={s.language} onChange={(e) => setS({ ...s, language: e.target.value as Settings["language"] })}>
                  <option value="de">Deutsch</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label className="field grow">
                <span>{t("Zeitzone")}</span>
                <input list="timezones" value={s.timezone} onChange={(e) => setS({ ...s, timezone: e.target.value })} />
                <datalist id="timezones">
                  {timezones.map((z) => (
                    <option key={z} value={z} />
                  ))}
                </datalist>
              </label>
              <label className="field">
                <span>{t("Standarddauer (Minuten)")}</span>
                <input
                  type="number"
                  min={5}
                  max={1440}
                  step={5}
                  value={s.default_duration_min}
                  onChange={(e) => setS({ ...s, default_duration_min: Number(e.target.value) || 60 })}
                />
              </label>
            </div>
          </section>

          <section>
            <h3>{t("Wetter")}</h3>
            <div className="row">
              <label className="field grow">
                <span>{t("Ort")}</span>
                <input value={s.weather_place} placeholder="Bokel" onChange={(e) => setS({ ...s, weather_place: e.target.value })} />
              </label>
              <label className="field">
                <span>{t("Breite")}</span>
                <input type="number" step="any" min={-90} max={90} value={s.weather_lat} onChange={(e) => setS({ ...s, weather_lat: Number(e.target.value) })} />
              </label>
              <label className="field">
                <span>{t("Länge")}</span>
                <input type="number" step="any" min={-180} max={180} value={s.weather_lon} onChange={(e) => setS({ ...s, weather_lon: Number(e.target.value) })} />
              </label>
            </div>
            <p className="small">Koordinaten des Ortes, z. B. aus Google Maps. Ohne Ort wird kein Wetter angezeigt.</p>
          </section>

          {me && (
            <section className="account">
              <span>
                {me.auth_mode === "none" ? "Lokaler Betrieb ohne Anmeldung" : `Angemeldet als ${me.email}`}
              </span>
              {me.auth_mode !== "none" && (
                <button className="btn" onClick={logout}>
                  {t("Abmelden")}
                </button>
              )}
            </section>
          )}
        </div>
        <footer className="sheet-foot">
          <button className="btn" onClick={onClose}>
            {t("Abbrechen")}
          </button>
          <button className="btn primary" disabled={saving} onClick={save}>
            {saving ? "…" : t("Speichern")}
          </button>
        </footer>
      </div>
    </div>
  );
}

function ModelList({ id, models }: { id: string; models: ModelInfo[] }) {
  return (
    <datalist id={id}>
      {models.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name}
        </option>
      ))}
    </datalist>
  );
}
