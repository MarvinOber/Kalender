import { useRef, useState } from "react";
import { t } from "../i18n";
import { type View, VIEW_LABELS, VIEWS } from "../view";
import { useDismiss } from "./useDismiss";

interface Props {
  view: View;
  onView: (v: View) => void;
}

/** Handy: Knopf mit der gewählten Ansicht, klappt Termine/Woche/Monat auf (statt der drei Chips im Kopf). */
export function ViewMenu({ view, onView }: Props) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useDismiss(open, () => setOpen(false), [button, menu], button);

  const label = t(VIEW_LABELS[view]);
  return (
    <div className="view-menu-wrap">
      <button
        ref={button}
        className="btn view-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${t("Ansicht")}: ${label}`}
        onClick={() => setOpen((o) => !o)}
      >
        {label}
        <Chevron />
      </button>
      {open && (
        <div className="menu view-menu" role="menu" ref={menu}>
          {VIEWS.map((v) => (
            <button
              key={v}
              role="menuitemradio"
              aria-checked={view === v}
              className={view === v ? "on" : ""}
              onClick={() => {
                setOpen(false);
                onView(v);
              }}
            >
              <span className="check" aria-hidden>
                {view === v ? "✓" : ""}
              </span>
              {t(VIEW_LABELS[v])}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Chevron() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
      <path d="M6 9.5l6 6 6-6" stroke="currentColor" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
