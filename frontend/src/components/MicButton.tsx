import { useEffect, useRef } from "react";
import { t } from "../i18n";

export type MicState = "idle" | "starting" | "recording" | "processing";

interface Props {
  state: MicState;
  level: number;
  seconds: number;
  onStart: () => void;
  onStop: () => void;
  onType: () => void;
}

const HOLD_MS = 400; // länger gedrückt = Sprechtaste, kürzer = Antippen startet und stoppt

/** Großer Knopf unten in der Mitte: gedrückt halten (loslassen beendet) oder antippen (erneut tippen beendet). */
export function MicButton({ state, level, seconds, onStart, onStop, onType }: Props) {
  const mode = useRef<"none" | "pending" | "hold" | "tap">("none");
  const downAt = useRef(0);
  const stopWhenReady = useRef(false);

  useEffect(() => {
    if (state === "recording" && stopWhenReady.current) {
      stopWhenReady.current = false;
      onStop();
    }
    if (state === "idle") mode.current = "none";
  }, [state, onStop]);

  const down = (e: React.PointerEvent) => {
    e.preventDefault();
    if (state === "idle") {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      downAt.current = Date.now();
      mode.current = "pending";
      onStart();
    } else if (state === "recording" && mode.current === "tap") {
      onStop();
    }
  };

  const up = () => {
    if (mode.current !== "pending") return;
    if (Date.now() - downAt.current >= HOLD_MS) {
      mode.current = "hold";
      if (state === "recording") onStop();
      else stopWhenReady.current = true; // Mikrofon startet noch
    } else {
      mode.current = "tap";
    }
  };

  const key = (e: React.KeyboardEvent) => {
    if (e.key !== " " && e.key !== "Enter") return;
    e.preventDefault();
    if (state === "idle") {
      mode.current = "tap";
      onStart();
    } else if (state === "recording") onStop();
  };

  const recording = state === "recording" || state === "starting";
  const label =
    state === "processing"
      ? t("Verstehe …")
      : recording
        ? `${t("Ich höre zu …")} ${fmt(seconds)} · ${mode.current === "tap" ? t("Tippen zum Beenden") : t("Loslassen zum Beenden")}`
        : t("Gedrückt halten oder tippen und sprechen");

  return (
    <div className={`mic-wrap ${state}`}>
      <div className="mic-label" aria-live="polite">
        {label}
      </div>
      <button
        className="mic"
        aria-label={label}
        aria-pressed={recording}
        disabled={state === "processing"}
        onPointerDown={down}
        onPointerUp={up}
        onPointerCancel={up}
        onKeyDown={key}
        onContextMenu={(e) => e.preventDefault()}
        style={{ "--level": recording ? level.toFixed(2) : "0" } as React.CSSProperties}
      >
        {state === "processing" ? <span className="spinner" /> : <MicIcon />}
      </button>
      {state === "idle" && (
        <button className="icon type-btn" aria-label={t("Text eingeben")} title={t("Text eingeben")} onClick={onType}>
          ⌨
        </button>
      )}
    </div>
  );
}

function fmt(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="44" height="44" aria-hidden>
      <rect x="8.5" y="2.5" width="7" height="12" rx="3.5" fill="currentColor" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3.5M8.5 21.5h7" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}
