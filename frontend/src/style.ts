/** Aussehen des Kalenders. Gewählt und gespeichert je Gerät – wie die Ansicht –, damit das Wand-Tablet anders
 *  aussehen darf als ein Handy. Die Farben stehen in styles.css unter `[data-style="…"]`. */
export type Style = "klassisch" | "modern" | "minimal" | "bunt" | "papier" | "nacht";

export const STYLES: Style[] = ["klassisch", "modern", "minimal", "bunt", "papier", "nacht"];
export const DEFAULT_STYLE: Style = "klassisch";

export const STYLE_LABELS: Record<Style, string> = {
  klassisch: "Klassisch",
  modern: "Modern",
  minimal: "Minimalistisch",
  bunt: "Kunterbunt",
  papier: "Papier",
  nacht: "Nacht",
};

export const STYLE_HINTS: Record<Style, string> = {
  klassisch: "Hell und ruhig",
  modern: "Kühl, klare Karten",
  minimal: "Schwarz-weiß, viel Luft",
  bunt: "Jeder Tag eine Farbe",
  papier: "Wie ein Wandkalender",
  nacht: "Dunkel, blendet nicht",
};

const KEY = "familienkalender.style";

/** Unbekannte oder fehlende Werte ergeben den Standard. */
export function parseStyle(raw: string | null | undefined): Style {
  return raw && (STYLES as string[]).includes(raw) ? (raw as Style) : DEFAULT_STYLE;
}

export function loadStyle(): Style {
  try {
    return parseStyle(localStorage.getItem(KEY));
  } catch {
    return DEFAULT_STYLE; // gesperrter Speicher
  }
}

export function saveStyle(style: Style): void {
  try {
    localStorage.setItem(KEY, style);
  } catch {
    /* privater Modus: Stil gilt dann nur bis zum Neuladen */
  }
}

/** Setzt den Stil an <html> und färbt die Browserleiste passend zum Hintergrund. */
export function applyStyle(style: Style): void {
  const root = document.documentElement;
  root.dataset.style = style;
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (bg) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
}
