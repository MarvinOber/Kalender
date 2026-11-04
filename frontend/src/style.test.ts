/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import css from "./styles.css?raw";
import { setLanguage, t } from "./i18n";
import { DEFAULT_STYLE, STYLE_HINTS, STYLE_LABELS, STYLES, parseStyle } from "./style";

// setLanguage setzt <html lang>; im Test gibt es kein DOM
(globalThis as { document?: unknown }).document ??= { documentElement: {} };

// Variablen, die jede Vorschaukachel braucht – fehlt eine, erbt die Kachel sie vom Stil der Seite
const VARS = [
  "--bg",
  "--panel",
  "--text",
  "--muted",
  "--line",
  "--line-strong",
  "--accent",
  "--accent-text",
  "--today",
  "--now",
  "--past",
  "--shadow",
  "--radius",
  "--font",
  "--ev-radius",
  "--ev-tint",
  "--ev-bar",
  "--today-mark",
  "--on-mark",
];

/** Erster Regelblock, dessen Selektor `[data-style="…"]` enthält (ohne Nachfahren-Selektor). */
function block(style: string): string {
  const re = new RegExp(`(^|\\n)[^\\n{]*\\[data-style="${style}"\\][^\\n{ ]*\\s*\\{([^}]*)\\}`);
  return re.exec(css)?.[2] ?? "";
}

describe("Stile", () => {
  it("unbekannte oder fehlende Werte ergeben Klassisch", () => {
    expect(parseStyle(null)).toBe(DEFAULT_STYLE);
    expect(parseStyle("")).toBe(DEFAULT_STYLE);
    expect(parseStyle("neon")).toBe(DEFAULT_STYLE);
    expect(parseStyle("bunt")).toBe("bunt");
    expect(DEFAULT_STYLE).toBe("klassisch");
  });

  it("jeder Stil hat Namen, Hinweis und englische Übersetzung", () => {
    setLanguage("en");
    try {
      for (const st of STYLES) {
        expect(STYLE_LABELS[st]).toBeTruthy();
        expect(STYLE_HINTS[st]).toBeTruthy();
        if (STYLE_LABELS[st] !== "Modern") expect(t(STYLE_LABELS[st])).not.toBe(STYLE_LABELS[st]);
        expect(t(STYLE_HINTS[st])).not.toBe(STYLE_HINTS[st]);
      }
    } finally {
      setLanguage("de");
    }
  });

  it.each(STYLES)("styles.css setzt für „%s“ alle Variablen", (st) => {
    const body = block(st);
    expect(body, `Block [data-style="${st}"] fehlt`).not.toBe("");
    for (const v of VARS) expect(body, `${st}: ${v}`).toMatch(new RegExp(`\\s${v}:`));
  });
});
