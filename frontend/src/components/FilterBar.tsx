import { EMPTY_FILTER, type Filter, toggle } from "../filter";
import { t } from "../i18n";
import type { Settings } from "../types";
import { colorVar } from "./eventStyle";

interface Props {
  settings: Settings;
  filter: Filter;
  onChange: (f: Filter) => void;
}

export function FilterBar({ settings, filter, onChange }: Props) {
  const active = filter.persons.length + filter.tags.length > 0;
  return (
    <nav className="filterbar" aria-label="Filter">
      <button className={`chip ${active ? "" : "on"}`} onClick={() => onChange(EMPTY_FILTER)}>
        {t("Alle")}
      </button>
      <span className="sep" aria-hidden />
      {settings.persons.map((p) => (
        <button
          key={p.id}
          className={`chip person ${filter.persons.includes(p.id) ? "on" : ""}`}
          style={colorVar(p.color)}
          aria-pressed={filter.persons.includes(p.id)}
          onClick={() => onChange({ ...filter, persons: toggle(filter.persons, p.id) })}
        >
          <i className="dot" />
          {p.name}
        </button>
      ))}
      <span className="sep" aria-hidden />
      {settings.event_tags.map((tag) => (
        <button
          key={tag.id}
          className={`chip tag ${filter.tags.includes(tag.id) ? "on" : ""}`}
          aria-pressed={filter.tags.includes(tag.id)}
          onClick={() => onChange({ ...filter, tags: toggle(filter.tags, tag.id) })}
        >
          #{tag.name}
        </button>
      ))}
    </nav>
  );
}
