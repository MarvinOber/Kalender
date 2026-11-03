import type { CSSProperties } from "react";
import type { CalEvent, Settings } from "../types";

export const NEUTRAL = "#868e96";

export function colorVar(color: string): CSSProperties {
  return { "--c": color } as CSSProperties;
}

/** Farben der zugeordneten Personen; ohne Person neutral grau. */
export function eventColors(event: { persons: string[] }, settings: Settings): string[] {
  const colors = event.persons
    .map((id) => settings.persons.find((p) => p.id === id)?.color)
    .filter((c): c is string => !!c);
  return colors.length ? colors : [NEUTRAL];
}

/** Hintergrund: erste Farbe, bei mehreren Personen Streifen links. */
export function eventStyle(event: CalEvent, settings: Settings): CSSProperties {
  const colors = eventColors(event, settings);
  const stripes = colors.map((c, i) => `${c} ${(i / colors.length) * 100}% ${((i + 1) / colors.length) * 100}%`);
  return { "--c": colors[0], "--stripes": `linear-gradient(180deg, ${stripes.join(", ")})` } as CSSProperties;
}

export function personNames(ids: string[], settings: Settings): string {
  return ids
    .map((id) => settings.persons.find((p) => p.id === id)?.name)
    .filter(Boolean)
    .join(", ");
}

export function tagNames(ids: string[], settings: Settings): string[] {
  return ids.map((id) => settings.event_tags.find((x) => x.id === id)?.name).filter((n): n is string => !!n);
}
