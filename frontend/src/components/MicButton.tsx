import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { cameraAvailable, type PhotoSource } from "../photo";
import { useDismiss } from "./useDismiss";

export type MicState = "idle" | "starting" | "recording" | "processing";

interface Props {
  state: MicState;
  level: number;
  seconds: number;
  onStart: () => void;
  onStop: () => void;
  onType: () => void;
  /** Muss den Datei-Input noch im Klick öffnen, sonst blockiert der Browser */
  onPhoto: (source: PhotoSource) => void;
  /** Text während der Verarbeitung, Standard „Verstehe …“ */
  busyLabel?: string;
}

const HOLD_MS = 400; // länger gedrückt = Sprechtaste, kürzer = Antippen startet und stoppt

/**
 * Runder Knopf, schwebt unten in der Mitte über dem Kalender: gedrückt halten (loslassen beendet) oder antippen
 * (erneut tippen beendet). Links daneben der Foto-Knopf (auf Handy und Tablet mit Auswahl Kamera oder Galerie),
 * rechts der Knopf zum Tippen.
 */
export function MicButton({ state, level, seconds, onStart, onStop, onType, onPhoto, busyLabel }: Props) {
  const mode = useRef<"none" | "pending" | "hold" | "tap">("none");
  const downAt = useRef(0);
  const stopWhenReady = useRef(false);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const photoBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (state === "recording" && stopWhenReady.current) {
      stopWhenReady.current = false;
      onStop();
    }
    if (state === "idle") mode.current = "none";
    else setMenu(false);
  }, [state, onStop]);

  // Auswahl schließt bei Tippen daneben oder Escape; der Foto-Knopf selbst schaltet sie per Klick um
  useDismiss(menu, () => setMenu(false), [menuRef, photoBtn], photoBtn);

  const photo = () => {
    if (cameraAvailable()) setMenu((m) => !m);
    else onPhoto("gallery");
  };
  const pick = (source: PhotoSource) => {
    setMenu(false);
    onPhoto(source);
  };

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
      ? busyLabel ?? t("Verstehe …")
      : recording
        ? `${t("Ich höre zu …")} ${fmt(seconds)} · ${mode.current === "tap" ? t("Tippen zum Beenden") : t("Loslassen zum Beenden")}`
        : t("Gedrückt halten oder tippen und sprechen");

  return (
    <div className={`mic-wrap ${state}`}>
      {/* Im Ruhezustand kein Hinweistext, damit das Overlay möglichst wenig vom Kalender verdeckt */}
      <div className="mic-label" aria-live="polite" hidden={state === "idle"}>
        {label}
      </div>
      <button
        className="mic"
        aria-label={label}
        title={label}
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
        <>
          <button
            ref={photoBtn}
            className="icon side-btn photo-btn"
            aria-label={t("Foto")}
            title={t("Foto")}
            aria-haspopup={cameraAvailable() ? "menu" : undefined}
            aria-expanded={cameraAvailable() ? menu : undefined}
            onClick={photo}
          >
            <CameraIcon />
          </button>
          {menu && (
            <div className="menu photo-menu" role="menu" ref={menuRef}>
              <button role="menuitem" onClick={() => pick("camera")}>
                <span aria-hidden>📷</span> {t("Foto aufnehmen")}
              </button>
              <button role="menuitem" onClick={() => pick("gallery")}>
                <span aria-hidden>🖼️</span> {t("Aus der Galerie")}
              </button>
            </div>
          )}
          <button className="icon side-btn type-btn" aria-label={t("Text eingeben")} title={t("Text eingeben")} onClick={onType}>
            ⌨
          </button>
        </>
      )}
    </div>
  );
}

function fmt(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function CameraIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
      <path
        d="M4 7.5h3l1.6-2.5h6.8L17 7.5h3a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8.5a1 1 0 0 1 1-1z"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="none"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="13" r="3.4" stroke="currentColor" strokeWidth="1.8" fill="none" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden>
      <rect x="8.5" y="2.5" width="7" height="12" rx="3.5" fill="currentColor" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3.5M8.5 21.5h7" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}
