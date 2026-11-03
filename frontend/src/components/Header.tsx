import { addDays, formatDay, isoWeek, weekLabel } from "../dates";
import { locale, t } from "../i18n";
import type { Weather } from "../types";
import { type Range, type View, VIEW_LABELS, VIEWS } from "../view";
import { weatherSymbol } from "../weather";

interface Props {
  view: View;
  range: Range;
  month: string; // YYYY-MM, Titel der Monatsansicht
  isCurrent: boolean;
  time: string;
  weather: Weather | null;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  onView: (v: View) => void;
  onSettings: () => void;
}

export function Header(props: Props) {
  const { view, range, month, isCurrent, time, weather, onPrev, onNext, onToday, onView, onSettings } = props;
  const isMonth = view === "month";
  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  return (
    <header className="header">
      <div className="nav">
        <button className="icon big" aria-label={t(isMonth ? "Vormonat" : "Vorwoche")} onClick={onPrev}>
          ‹
        </button>
        <button className={`btn ${isCurrent ? "" : "primary"}`} onClick={onToday}>
          {t("Heute")}
        </button>
        <button className="icon big" aria-label={t(isMonth ? "Nächster Monat" : "Nächste Woche")} onClick={onNext}>
          ›
        </button>
        <div className="views" role="group" aria-label={t("Ansicht")}>
          {VIEWS.map((v) => (
            <button key={v} className={`chip ${view === v ? "on" : ""}`} aria-pressed={view === v} onClick={() => onView(v)}>
              {t(VIEW_LABELS[v])}
            </button>
          ))}
        </div>
      </div>
      <div className="title">
        <span className="week-no">
          {t("KW")} {isoWeek(range.start)}
          {isMonth && `–${isoWeek(addDays(range.start, range.days - 7))}`}
        </span>
        <span className="range">
          {isMonth ? formatDay(`${month}-01`, locale(), { month: "long", year: "numeric" }) : weekLabel(range.start, locale())}
        </span>
      </div>
      <div className="tools">
        {weather?.place && weather.code !== undefined && <WeatherBadge weather={weather} />}
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

function WeatherBadge({ weather }: { weather: Weather }) {
  const { icon, label } = weatherSymbol(weather.code!, weather.is_day ?? true);
  const text = `${weather.place}: ${t(label)}, ${weather.temperature} °C`;
  return (
    <span className="weather" title={text} aria-label={text}>
      <span aria-hidden="true">{icon}</span>
      <span aria-hidden="true">{weather.temperature}°</span>
    </span>
  );
}
