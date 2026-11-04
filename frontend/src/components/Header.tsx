import { addDays, formatDay, isoWeek, rangeLabel, shortRangeLabel } from "../dates";
import { locale, t } from "../i18n";
import type { Weather } from "../types";
import { type Range, type View, VIEW_LABELS, VIEWS } from "../view";
import { weatherSymbol } from "../weather";
import { ViewMenu } from "./ViewMenu";

interface Props {
  view: View;
  range: Range;
  month: string; // YYYY-MM, Titel der Monatsansicht
  isCurrent: boolean;
  today: string;
  time: string;
  weather: Weather | null;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  onView: (v: View) => void;
  onSettings: () => void;
}

export function Header(props: Props) {
  const { view, range, month, isCurrent, today, time, weather, onPrev, onNext, onToday, onView, onSettings } = props;
  const isMonth = view === "month";
  const isList = view === "list";
  const prevLabel = isMonth ? "Vormonat" : isList ? "Früher" : "Vorwoche";
  const nextLabel = isMonth ? "Nächster Monat" : isList ? "Später" : "Nächste Woche";
  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  const last = addDays(range.start, range.days - 1);
  // Auf dem Handy (styles.css, „Handy“) steht der Kopf in einer Zeile: Monate kurz, „Heute“ als Kalenderblatt mit
  // dem heutigen Tag, die Ansicht als Aufklappmenü; Pfeile nur ohne Touch (dort blättert Wischen)
  return (
    <header className="header">
      <div className="nav">
        <button className="icon big arrow prev" aria-label={t(prevLabel)} title={t(prevLabel)} onClick={onPrev}>
          ‹
        </button>
        <button className={`btn today-btn ${isCurrent ? "" : "primary"}`} aria-label={t("Heute")} title={t("Heute")} onClick={onToday}>
          <span className="today-text">{t("Heute")}</span>
          <span className="today-day" aria-hidden>
            {Number(today.slice(8, 10))}
          </span>
        </button>
        <button className="icon big arrow next" aria-label={t(nextLabel)} title={t(nextLabel)} onClick={onNext}>
          ›
        </button>
        <div className="views" role="group" aria-label={t("Ansicht")}>
          {VIEWS.map((v) => (
            <button key={v} className={`chip ${view === v ? "on" : ""}`} aria-pressed={view === v} onClick={() => onView(v)}>
              {t(VIEW_LABELS[v])}
            </button>
          ))}
        </div>
        <ViewMenu view={view} onView={onView} />
      </div>
      <div className="title">
        <span className="week-no">
          {isList ? (
            t(isCurrent ? "Nächste 31 Tage" : "31 Tage")
          ) : (
            <>
              {t("KW")} {isoWeek(range.start)}
              {isMonth && `–${isoWeek(addDays(range.start, range.days - 7))}`}
            </>
          )}
        </span>
        {isMonth ? (
          <span className="range">{formatDay(`${month}-01`, locale(), { month: "long", year: "numeric" })}</span>
        ) : (
          <>
            <span className="range long">{rangeLabel(range.start, last, locale())}</span>
            <span className="range short">{shortRangeLabel(range.start, last, locale(), today.slice(0, 4))}</span>
          </>
        )}
      </div>
      <div className="tools">
        {weather?.place && weather.code !== undefined && <WeatherBadge weather={weather} />}
        <span className="clock">{time}</span>
        <button className="icon fullscreen-btn" aria-label={t("Vollbild")} title={t("Vollbild")} onClick={fullscreen}>
          ⛶
        </button>
        <button className="icon settings-btn" aria-label={t("Einstellungen")} title={t("Einstellungen")} onClick={onSettings}>
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
