import { addDays, isoWeek, weekLabel } from "../dates";
import { locale, t } from "../i18n";

interface Props {
  monday: string;
  today: string;
  time: string;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  onSettings: () => void;
}

export function Header({ monday, today, time, onPrev, onNext, onToday, onSettings }: Props) {
  const isCurrent = today >= monday && today <= addDays(monday, 6);
  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  return (
    <header className="header">
      <div className="nav">
        <button className="icon big" aria-label={t("Vorwoche")} onClick={onPrev}>
          ‹
        </button>
        <button className={`btn ${isCurrent ? "" : "primary"}`} onClick={onToday}>
          {t("Heute")}
        </button>
        <button className="icon big" aria-label={t("Nächste Woche")} onClick={onNext}>
          ›
        </button>
      </div>
      <div className="title">
        <span className="week-no">
          {t("KW")} {isoWeek(monday)}
        </span>
        <span className="range">{weekLabel(monday, locale())}</span>
      </div>
      <div className="tools">
        <span className="clock">{time}</span>
        <button className="icon" aria-label={t("Vollbild")} title={t("Vollbild")} onClick={fullscreen}>
          ⛶
        </button>
        <button className="icon" aria-label={t("Einstellungen")} title={t("Einstellungen")} onClick={onSettings}>
          ⚙
        </button>
      </div>
    </header>
  );
}
