/** Der deutsche Text ist der Schlüssel; fehlt eine Übersetzung, erscheint Deutsch. */

const EN: Record<string, string> = {
  "Heute": "Today",
  "Vorwoche": "Previous week",
  "Nächste Woche": "Next week",
  "KW": "Week",
  "Ganztägig": "All day",
  "ganztägig": "all day",
  "Alle": "All",
  "Personen": "People",
  "Ereignisse": "Events",
  "Einstellungen": "Settings",
  "Vollbild": "Full screen",
  "Stand": "Updated",
  "Keine Termine": "No events",
  "Gedrückt halten oder tippen und sprechen": "Hold or tap, then speak",
  "Ich höre zu …": "Listening …",
  "Loslassen zum Beenden": "Release to finish",
  "Tippen zum Beenden": "Tap to finish",
  "Verstehe …": "Understanding …",
  "Erkannte Termine": "Recognised events",
  "Gesagt": "You said",
  "Neu erkennen": "Recognise again",
  "Anlegen": "Create",
  "Abbrechen": "Cancel",
  "Neu einsprechen": "Record again",
  "Termin entfernen": "Remove event",
  "Titel": "Title",
  "Datum": "Date",
  "Von": "From",
  "Bis": "Until",
  "bis": "until",
  "Ort": "Location",
  "Beschreibung": "Description",
  "Wiederholung": "Repeat",
  "keine": "none",
  "täglich": "daily",
  "wöchentlich": "weekly",
  "monatlich": "monthly",
  "jährlich": "yearly",
  "alle": "every",
  "Bitte prüfen": "Please check",
  "Pflichtfeld": "Required",
  "Termin hinzufügen": "Add event",
  "Text eingeben": "Type text",
  "Erkennen": "Recognise",
  "Speichern": "Save",
  "Schließen": "Close",
  "Abmelden": "Sign out",
  "Mit Google anmelden": "Sign in with Google",
  "Kalender": "Calendar",
  "Kalender-ID": "Calendar ID",
  "KI-Modelle": "AI models",
  "Transkription (Audio)": "Transcription (audio)",
  "Termin-Erkennung": "Event recognition",
  "Name": "Name",
  "Farbe": "Colour",
  "Auch genannt": "Also called",
  "Hinweise für das Modell": "Hints for the model",
  "Person hinzufügen": "Add person",
  "Tag hinzufügen": "Add tag",
  "Sprache": "Language",
  "Zeitzone": "Time zone",
  "Standarddauer (Minuten)": "Default duration (minutes)",
  "Allgemein": "General",
  "Gespeichert": "Saved",
  "Erneut anmelden": "Sign in again",
};

let lang: "de" | "en" = "de";

export function setLanguage(l: "de" | "en"): void {
  lang = l;
  document.documentElement.lang = l;
}

export function locale(): string {
  return lang === "en" ? "en-GB" : "de-DE";
}

export function t(text: string): string {
  return lang === "en" ? EN[text] ?? text : text;
}
