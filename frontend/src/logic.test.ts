import { describe, expect, it, vi } from "vitest";
import { httpErrorMessage } from "./api";
import { addDays, addMonths, isoWeek, mondayOf, nowIn, rangeLabel } from "./dates";
import { matches, pruneFilter } from "./filter";
import { allDayBars, dayItems, timedSegments, visibleHours } from "./layout";
import { cameraAvailable, fitWithin } from "./photo";
import type { CalEvent } from "./types";
import { inRange, rangeOf, samePeriod, step } from "./view";
import { weatherSymbol } from "./weather";

const ev = (p: Partial<CalEvent>): CalEvent => ({
  id: p.id ?? Math.random().toString(36),
  title: "T",
  all_day: false,
  start: "2026-11-06T16:00",
  end: "2026-11-06T17:00",
  location: "",
  description: "",
  persons: [],
  tags: [],
  recurring: false,
  link: "",
  ...p,
});

describe("Datum", () => {
  it("rechnet Wochen", () => {
    expect(mondayOf("2026-11-03")).toBe("2026-11-02");
    expect(mondayOf("2026-11-08")).toBe("2026-11-02");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(isoWeek("2026-11-02")).toBe(45);
    expect(isoWeek("2027-01-01")).toBe(53);
    expect(isoWeek("2026-01-01")).toBe(1);
  });

  it("beschriftet Zeiträume", () => {
    expect(rangeLabel("2026-11-02", "2026-11-08", "de-DE")).toBe("2 – 8. November 2026");
    expect(rangeLabel("2026-11-03", "2026-12-03", "de-DE")).toBe("3. November – 3. Dezember 2026");
    expect(rangeLabel("2026-12-28", "2027-01-03", "de-DE")).toBe("28. Dezember 2026 – 3. Januar 2027");
  });

  it("nimmt die Familien-Zeitzone für jetzt", () => {
    const n = nowIn("Europe/Berlin", new Date("2026-11-03T23:30:00Z"));
    expect(n).toEqual({ date: "2026-11-04", minutes: 30, time: "00:30" });
  });
});

describe("Filter", () => {
  const lena = ev({ persons: ["lena"], tags: ["sport"] });
  const oma = ev({ all_day: true, start: "2026-11-07", end: "2026-11-08", tags: ["geburtstag"] });
  const papa = ev({ persons: ["papa"], tags: ["arzt"] });

  it("Lena zeigt nur Lenas Termine", () => {
    expect([lena, oma, papa].filter((e) => matches(e, { persons: ["lena"], tags: [] }))).toEqual([lena]);
  });

  it("Mehrfachauswahl: innerhalb der Gruppe oder, zwischen Gruppen und", () => {
    const f = { persons: ["lena", "papa"], tags: [] };
    expect([lena, oma, papa].filter((e) => matches(e, f))).toEqual([lena, papa]);
    expect([lena, oma, papa].filter((e) => matches(e, { persons: ["lena", "papa"], tags: ["arzt"] }))).toEqual([papa]);
    expect([lena, oma, papa].filter((e) => matches(e, { persons: [], tags: [] }))).toHaveLength(3);
  });

  it("verwirft gelöschte Kennungen", () => {
    expect(pruneFilter({ persons: ["lena", "weg"], tags: ["x"] }, ["lena"], [])).toEqual({ persons: ["lena"], tags: [] });
  });
});

describe("Layout", () => {
  it("legt Überschneidungen nebeneinander", () => {
    const days = timedSegments(
      [
        ev({ id: "a", start: "2026-11-06T16:00", end: "2026-11-06T17:00" }),
        ev({ id: "b", start: "2026-11-06T16:30", end: "2026-11-06T18:00" }),
        ev({ id: "c", start: "2026-11-06T18:00", end: "2026-11-06T19:00" }),
      ],
      "2026-11-02",
    );
    const fri = days[4];
    expect(fri.map((s) => [s.event.id, s.col, s.cols])).toEqual([
      ["a", 0, 2],
      ["b", 1, 2],
      ["c", 0, 1],
    ]);
  });

  it("schneidet Termine über Mitternacht", () => {
    const days = timedSegments([ev({ start: "2026-11-07T22:00", end: "2026-11-08T01:00" })], "2026-11-02");
    expect(days[5][0]).toMatchObject({ start: 1320, end: 1440, continuesAfter: true });
    expect(days[6][0]).toMatchObject({ start: 0, end: 60, continuesBefore: true });
    expect(visibleHours(days)).toEqual([0, 24]);
  });

  it("verteilt ganztägige Termine auf Zeilen", () => {
    const bars = allDayBars(
      [
        ev({ id: "ferien", all_day: true, start: "2026-10-31", end: "2026-11-05" }),
        ev({ id: "oma", all_day: true, start: "2026-11-07", end: "2026-11-08" }),
        ev({ id: "x", all_day: true, start: "2026-11-03", end: "2026-11-04" }),
      ],
      "2026-11-02",
    );
    expect(bars.map((b) => [b.event.id, b.startCol, b.span, b.row])).toEqual([
      ["ferien", 0, 3, 0],
      ["x", 1, 1, 1],
      ["oma", 5, 1, 0],
    ]);
  });
});

describe("Wetter", () => {
  it("ordnet WMO-Codes Symbolen zu, nachts mit Mond", () => {
    expect(weatherSymbol(0, true)).toEqual({ icon: "☀️", label: "Klar" });
    expect(weatherSymbol(0, false).icon).toBe("🌙");
    expect(weatherSymbol(3, true).label).toBe("Bedeckt");
    expect(weatherSymbol(63, true).label).toBe("Regen");
    expect(weatherSymbol(67, true).label).toBe("Gefrierender Regen");
    expect(weatherSymbol(81, true).label).toBe("Regenschauer");
    expect(weatherSymbol(75, true).label).toBe("Schnee");
    expect(weatherSymbol(96, true).label).toBe("Gewitter");
    expect(weatherSymbol(42, true).label).toBe("Wetter");
  });
});

describe("Ansicht", () => {
  it("Woche ab Montag, Monat in vollen Wochen", () => {
    expect(rangeOf("week", "2026-11-05")).toEqual({ start: "2026-11-02", days: 7 });
    expect(rangeOf("list", "2026-11-05")).toEqual({ start: "2026-11-05", days: 31 });
    // November 2026: Sonntag, 1. bis Montag, 30. – sechs Wochen
    expect(rangeOf("month", "2026-11-17")).toEqual({ start: "2026-10-26", days: 42 });
    // Februar 2027: Montag, 1. bis Sonntag, 28. – genau vier Wochen
    expect(rangeOf("month", "2027-02-10")).toEqual({ start: "2027-02-01", days: 28 });
  });

  it("blättert Woche und Monat", () => {
    expect(step("week", "2026-11-05", 1)).toBe("2026-11-09");
    expect(step("list", "2026-11-05", 1)).toBe("2026-12-06");
    expect(step("month", "2026-11-17", 1)).toBe("2026-12-01");
    expect(step("month", "2026-01-31", -1)).toBe("2025-12-01");
    expect(addMonths("2026-12-15", 2)).toBe("2027-02-01");
  });

  it("erkennt den aktuellen Zeitraum", () => {
    expect(samePeriod("week", "2026-11-02", "2026-11-08")).toBe(true);
    expect(samePeriod("week", "2026-11-08", "2026-11-09")).toBe(false);
    expect(samePeriod("month", "2026-11-01", "2026-11-30")).toBe(true);
    expect(samePeriod("list", "2026-11-03", "2026-11-03")).toBe(true);
    expect(samePeriod("list", "2026-11-03", "2026-11-04")).toBe(false);
    expect(inRange(rangeOf("month", "2026-11-01"), "2026-12-06T10:00")).toBe(true);
    expect(inRange(rangeOf("month", "2026-11-01"), "2026-12-07")).toBe(false);
  });

  it("verteilt Termine auf die Tage des Monats", () => {
    const days = dayItems(
      [
        ev({ id: "abend", start: "2026-11-03T18:00", end: "2026-11-03T19:00" }),
        ev({ id: "frueh", start: "2026-11-03T08:00", end: "2026-11-03T09:00" }),
        ev({ id: "ferien", all_day: true, start: "2026-11-02", end: "2026-11-05" }),
        ev({ id: "nacht", start: "2026-11-04T22:00", end: "2026-11-05T00:00" }),
        ev({ id: "vorher", start: "2026-10-20T10:00", end: "2026-10-20T11:00" }),
      ],
      "2026-10-26",
      42,
    );
    const ids = (d: number) => days[d].map((x) => x.event.id);
    expect(ids(7)).toEqual(["ferien"]);
    expect(ids(8)).toEqual(["ferien", "frueh", "abend"]);
    expect(ids(9)).toEqual(["ferien", "nacht"]);
    expect(ids(10)).toEqual([]);
    expect(days.flat().some((x) => x.event.id === "vorher")).toBe(false);
    expect(days[9].find((x) => x.event.id === "nacht")?.continuesAfter).toBe(false);
    expect(days[8][0]).toMatchObject({ continuesBefore: true, continuesAfter: true });
  });
});

describe("Foto", () => {
  it("verkleinert auf höchstens 2048 px an der längsten Seite", () => {
    expect(fitWithin(4032, 3024)).toEqual({ width: 2048, height: 1536 }); // Handy quer
    expect(fitWithin(3024, 4032)).toEqual({ width: 1536, height: 2048 }); // Handy hoch
    expect(fitWithin(8000, 100)).toEqual({ width: 2048, height: 26 });
  });
  it("lässt kleine Bilder unverändert", () => {
    expect(fitWithin(1200, 900)).toEqual({ width: 1200, height: 900 });
    expect(fitWithin(2048, 2048)).toEqual({ width: 2048, height: 2048 });
  });
  it("bietet die Kamera nur auf Touch-Geräten an", () => {
    expect(cameraAvailable()).toBe(false); // ohne Browser
    const media = (coarse: boolean) => (q: string) => ({ matches: coarse && q === "(pointer: coarse)" });
    vi.stubGlobal("window", { matchMedia: media(true) });
    expect(cameraAvailable()).toBe(true); // Handy, Tablet
    vi.stubGlobal("window", { matchMedia: media(false) });
    expect(cameraAvailable()).toBe(false); // Maus: Desktop-Browser ignorieren „capture“
    vi.stubGlobal("window", {});
    expect(cameraAvailable()).toBe(false); // alter Browser ohne matchMedia
    vi.unstubAllGlobals();
  });
});

describe("Fehlermeldungen ohne JSON", () => {
  it("erklärt Zeitüberschreitung und Ausfall statt „Fehler 504“", () => {
    expect(httpErrorMessage(504)).toBe("Der Server hat nicht rechtzeitig geantwortet. Bitte noch einmal versuchen.");
    expect(httpErrorMessage(503)).toBe("Der Server ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen.");
    expect(httpErrorMessage(502)).toBe(httpErrorMessage(503));
    expect(httpErrorMessage(500)).toBe("Unerwarteter Fehler (500). Bitte noch einmal versuchen.");
  });
});
