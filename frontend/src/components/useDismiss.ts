import { type RefObject, useEffect, useRef } from "react";

/**
 * Aufklappmenü schließen bei Tippen daneben oder Escape. Tippen auf eines der Elemente in `inside` (Menü und der
 * auslösende Knopf, der selbst per Klick umschaltet) zählt nicht als daneben; Escape gibt den Fokus an `focusBack`.
 */
export function useDismiss(
  open: boolean,
  close: () => void,
  inside: RefObject<HTMLElement>[],
  focusBack?: RefObject<HTMLElement>,
): void {
  const latest = useRef({ close, inside, focusBack });
  latest.current = { close, inside, focusBack };

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!latest.current.inside.some((r) => r.current?.contains(target))) latest.current.close();
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      latest.current.close();
      latest.current.focusBack?.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
}
