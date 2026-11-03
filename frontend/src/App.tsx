import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { EditDialog } from "./components/EditDialog";
import { EventDetails } from "./components/EventDetails";
import { FilterBar } from "./components/FilterBar";
import { Header } from "./components/Header";
import { LoginScreen } from "./components/LoginScreen";
import { MicButton, type MicState } from "./components/MicButton";
import { SettingsPanel } from "./components/SettingsPanel";
import { AgendaView } from "./components/AgendaView";
import { WeekView } from "./components/WeekView";
import { addDays, mondayOf, nowIn } from "./dates";
import { type Filter, loadFilter, matches, pruneFilter, saveFilter } from "./filter";
import { setLanguage, t } from "./i18n";
import { MAX_SECONDS, MicError, Recorder } from "./recorder";
import type { CalEvent, EditScope, Me, ParseResult, Settings } from "./types";

const REFRESH_MS = 5 * 60_000; // Änderungen von anderen Geräten
const IDLE_BACK_TO_TODAY_MS = 3 * 60_000; // Wandbetrieb: nach einer Weile zurück zur aktuellen Woche

interface Toast {
  text: string;
  kind: "info" | "error";
  action?: { label: string; run: () => void };
}

export function App() {
  const [auth, setAuth] = useState<"loading" | "login" | "ok">("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [now, setNow] = useState(() => nowIn("Europe/Berlin"));
  const [monday, setMonday] = useState(() => mondayOf(nowIn("Europe/Berlin").date));
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [fetchedAt, setFetchedAt] = useState("");
  const [stale, setStale] = useState(false);
  const [filter, setFilter] = useState<Filter>(loadFilter);
  const [portrait, setPortrait] = useState(() => window.matchMedia("(orientation: portrait)").matches);
  const [mic, setMic] = useState<MicState>("idle");
  const [level, setLevel] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [result, setResultState] = useState<ParseResult | null>(null);
  const [resultKey, setResultKey] = useState(0);
  const [details, setDetails] = useState<CalEvent | null>(null);
  const [editing, setEditing] = useState<{ id: string; scope: EditScope } | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reauth, setReauth] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const recorder = useRef<Recorder | null>(null);
  const idleTimer = useRef<number>();

  // Jedes neue Ergebnis baut den Dialog frisch auf (eigene Bearbeitungen gelten nur für dieses Ergebnis)
  const setResult = useCallback((r: ParseResult | null) => {
    setResultKey((k) => k + 1);
    setResultState(r);
  }, []);

  const tz = settings?.timezone || "Europe/Berlin";
  const today = now.date;

  const showError = useCallback((err: unknown) => {
    if (err instanceof ApiError) {
      if (err.code === "login") return setAuth("login");
      if (err.code === "reauth") return setReauth(true);
      setToast({ text: err.message, kind: "error" });
    } else if (err instanceof MicError) {
      setToast({ text: err.message, kind: "error" });
    } else {
      setToast({ text: String((err as Error)?.message || err), kind: "error" });
    }
  }, []);

  // ---------- Laden ----------
  useEffect(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        setAuth("ok");
      })
      .catch((err) => (err instanceof ApiError && err.status === 401 && err.code === "login" ? setAuth("login") : showError(err)));
  }, [showError]);

  const loadSettings = useCallback(async () => {
    const s = await api.settings();
    setSettings(s);
    setLanguage(s.language);
    setFilter((f) => pruneFilter(f, s.persons.map((p) => p.id), s.event_tags.map((x) => x.id)));
    return s;
  }, []);

  const loadEvents = useCallback(async () => {
    try {
      const data = await api.events(monday);
      setEvents(data.events);
      setFetchedAt(data.fetched_at.slice(11, 16));
      setStale(false);
      setReauth(false);
    } catch (err) {
      setStale(true);
      showError(err);
    }
  }, [monday, showError]);

  useEffect(() => {
    if (auth === "ok") loadSettings().catch(showError);
  }, [auth, loadSettings, showError]);

  useEffect(() => {
    if (auth === "ok" && settings) loadEvents();
  }, [auth, settings?.calendar_id, settings?.timezone, loadEvents]); // eslint-disable-line react-hooks/exhaustive-deps

  // Regelmäßig neu laden – und sofort, wenn das Gerät wieder aufwacht
  useEffect(() => {
    if (auth !== "ok") return;
    const refresh = () => {
      loadSettings().catch(() => undefined);
      loadEvents();
    };
    const id = window.setInterval(refresh, REFRESH_MS);
    const onVisible = () => document.visibilityState === "visible" && refresh();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [auth, loadEvents, loadSettings]);

  // Uhr und Wochenwechsel um Mitternacht
  useEffect(() => {
    const tick = () =>
      setNow((prev) => {
        const next = nowIn(tz);
        if (next.date !== prev.date) setMonday((m) => (m === mondayOf(prev.date) ? mondayOf(next.date) : m));
        return next;
      });
    tick();
    const id = window.setInterval(tick, 20_000);
    return () => window.clearInterval(id);
  }, [tz]);

  useEffect(() => {
    const mq = window.matchMedia("(orientation: portrait)");
    const onChange = () => setPortrait(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => saveFilter(filter), [filter]);

  // Bildschirm an der Wand wach halten (wo der Browser es kann)
  useEffect(() => {
    let lock: { release: () => Promise<void> } | null = null;
    const acquire = async () => {
      try {
        lock = await (navigator as any).wakeLock?.request("screen");
      } catch {
        lock = null;
      }
    };
    const onVisible = () => document.visibilityState === "visible" && acquire();
    acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      lock?.release().catch(() => undefined);
    };
  }, []);

  // Nach einer Weile ohne Bedienung zurück zur aktuellen Woche
  const touch = useCallback(() => {
    window.clearTimeout(idleTimer.current);
    idleTimer.current = window.setTimeout(() => setMonday(mondayOf(nowIn(tz).date)), IDLE_BACK_TO_TODAY_MS);
  }, [tz]);

  useEffect(() => {
    if (auth !== "ok") return;
    if (monday === mondayOf(today)) return;
    window.addEventListener("pointerdown", touch);
    touch();
    return () => {
      window.removeEventListener("pointerdown", touch);
      window.clearTimeout(idleTimer.current);
    };
  }, [auth, monday, today, touch]);

  // ---------- Spracheingabe ----------
  useEffect(() => {
    if (mic !== "recording") return;
    setSeconds(0);
    const started = Date.now();
    const id = window.setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      setSeconds(s);
      if (s >= MAX_SECONDS) stopRecording();
    }, 250);
    return () => window.clearInterval(id);
  }, [mic]); // eslint-disable-line react-hooks/exhaustive-deps

  const startRecording = useCallback(async () => {
    if (mic !== "idle") return;
    setResult(null);
    const rec = new Recorder();
    recorder.current = rec;
    setMic("starting");
    try {
      await rec.start(setLevel);
      setMic("recording");
    } catch (err) {
      recorder.current = null;
      setMic("idle");
      if (err instanceof MicError) {
        setToast({
          text: err.message,
          kind: "error",
          action: { label: t("Text eingeben"), run: () => setResult({ transcript: "", events: [], message: "" }) },
        });
      } else showError(err);
    }
  }, [mic, showError, setResult]);

  const stopRecording = useCallback(async () => {
    const rec = recorder.current;
    if (!rec) return;
    recorder.current = null;
    setMic("processing");
    setLevel(0);
    try {
      const wav = await rec.stop();
      setResult(await api.voice(wav));
    } catch (err) {
      showError(err);
    } finally {
      setMic("idle");
    }
  }, [showError, setResult]);

  const reparse = useCallback(
    async (text: string) => {
      setMic("processing");
      try {
        setResult(await api.parse(text));
      } catch (err) {
        showError(err);
      } finally {
        setMic("idle");
      }
    },
    [showError, setResult],
  );

  const created = useCallback(
    (list: CalEvent[]) => {
      setResult(null);
      const first = list.map((e) => e.start.slice(0, 10)).sort()[0];
      const text = list.length === 1 ? `„${list[0].title}“ angelegt` : `${list.length} Termine angelegt`;
      const targetWeek = first ? mondayOf(first) : monday;
      setToast({
        text,
        kind: "info",
        action: targetWeek !== monday ? { label: "Anzeigen", run: () => setMonday(targetWeek) } : undefined,
      });
      loadEvents();
    },
    [loadEvents, monday, setResult],
  );

  // ---------- Anzeige ----------
  const visible = useMemo(() => events.filter((e) => matches(e, filter)), [events, filter]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), toast.kind === "error" ? 9000 : 5000);
    return () => window.clearTimeout(id);
  }, [toast]);

  if (auth === "loading") return <div className="splash">Familienkalender …</div>;
  if (auth === "login") return <LoginScreen />;
  if (!settings) return <div className="splash">Familienkalender …</div>;

  return (
    <div className={`app ${portrait ? "portrait" : "landscape"}`}>
      <Header
        monday={monday}
        today={today}
        time={now.time}
        onPrev={() => setMonday(addDays(monday, -7))}
        onNext={() => setMonday(addDays(monday, 7))}
        onToday={() => setMonday(mondayOf(today))}
        onSettings={() => setSettingsOpen(true)}
      />
      <FilterBar settings={settings} filter={filter} onChange={setFilter} />
      {reauth && (
        <div className="banner">
          {t("Die Google-Anmeldung ist abgelaufen.")}
          <a className="btn primary" href="/auth/login">
            {t("Erneut anmelden")}
          </a>
        </div>
      )}
      <main
        className="calendar"
        onPointerDown={swipeStart}
        onPointerUp={(e) => swipeEnd(e, (dir) => setMonday(addDays(monday, dir * 7)))}
      >
        {portrait ? (
          <AgendaView events={visible} monday={monday} today={today} nowMinutes={now.minutes} settings={settings} onSelect={setDetails} />
        ) : (
          <WeekView events={visible} monday={monday} today={today} nowMinutes={now.minutes} settings={settings} onSelect={setDetails} />
        )}
      </main>
      <footer className="footer">
        <span className={stale ? "stale" : ""}>
          {fetchedAt && `${t("Stand")} ${fetchedAt}`}
          {stale && " · offline"}
          {me?.fake_llm && " · Demo-KI"}
        </span>
      </footer>
      <MicButton
        state={mic}
        level={level}
        seconds={seconds}
        onStart={startRecording}
        onStop={stopRecording}
        onType={() => setResult({ transcript: "", events: [], message: "" })}
      />
      {result && (
        <ConfirmDialog
          key={resultKey}
          result={result}
          settings={settings}
          busy={mic === "processing"}
          onCancel={() => setResult(null)}
          onRetry={() => {
            setResult(null);
            startRecording();
          }}
          onReparse={reparse}
          onCreated={created}
          onError={showError}
        />
      )}
      {details && !editing && (
        <EventDetails
          event={details}
          settings={settings}
          onClose={() => setDetails(null)}
          onEdit={(scope) => setEditing({ id: details.id, scope })}
          onDeleted={() => {
            setDetails(null);
            setToast({ text: `„${details.title}“ ${t("Gelöscht").toLowerCase()}`, kind: "info" });
            loadEvents();
          }}
          onError={showError}
        />
      )}
      {editing && (
        <EditDialog
          eventId={editing.id}
          scope={editing.scope}
          settings={settings}
          onClose={() => setEditing(null)}
          onSaved={(event) => {
            setEditing(null);
            setDetails(null);
            const week = mondayOf(event.start.slice(0, 10));
            setToast({
              text: t("Gespeichert"),
              kind: "info",
              action: week !== monday ? { label: "Anzeigen", run: () => setMonday(week) } : undefined,
            });
            loadEvents();
          }}
          onError={showError}
        />
      )}
      {settingsOpen && (
        <SettingsPanel
          settings={settings}
          me={me}
          onClose={() => setSettingsOpen(false)}
          onSaved={(s) => {
            setSettings(s);
            setLanguage(s.language);
            setSettingsOpen(false);
            setToast({ text: t("Gespeichert"), kind: "info" });
          }}
          onError={showError}
        />
      )}
      {toast && (
        <div className={`toast ${toast.kind}`} role="status">
          <span>{toast.text}</span>
          {toast.action && (
            <button
              className="btn"
              onClick={() => {
                toast.action!.run();
                setToast(null);
              }}
            >
              {toast.action.label}
            </button>
          )}
          <button className="icon" aria-label={t("Schließen")} onClick={() => setToast(null)}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}

// Wischen über den Kalender blättert die Woche
let swipe: { x: number; y: number; t: number } | null = null;

function swipeStart(e: ReactPointerEvent) {
  swipe = { x: e.clientX, y: e.clientY, t: Date.now() };
}

function swipeEnd(e: ReactPointerEvent, go: (dir: number) => void) {
  if (!swipe) return;
  const dx = e.clientX - swipe.x;
  const dy = e.clientY - swipe.y;
  const fast = Date.now() - swipe.t < 600;
  swipe = null;
  if (fast && Math.abs(dx) > 80 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
}
