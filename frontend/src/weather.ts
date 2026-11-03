/** WMO-Wettercode (Open-Meteo) → Symbol und deutscher Text (Übersetzungsschlüssel). */
export function weatherSymbol(code: number, isDay: boolean): { icon: string; label: string } {
  if (code === 0) return { icon: isDay ? "☀️" : "🌙", label: "Klar" };
  if (code === 1) return { icon: isDay ? "🌤️" : "🌙", label: "Überwiegend klar" };
  if (code === 2) return { icon: isDay ? "⛅" : "☁️", label: "Teilweise bewölkt" };
  if (code === 3) return { icon: "☁️", label: "Bedeckt" };
  if (code === 45 || code === 48) return { icon: "🌫️", label: "Nebel" };
  if (code >= 51 && code <= 57) return { icon: "🌦️", label: "Nieselregen" };
  if (code === 66 || code === 67) return { icon: "🌧️", label: "Gefrierender Regen" };
  if (code >= 61 && code <= 65) return { icon: "🌧️", label: "Regen" };
  if (code >= 71 && code <= 77) return { icon: "🌨️", label: "Schnee" };
  if (code >= 80 && code <= 82) return { icon: "🌦️", label: "Regenschauer" };
  if (code === 85 || code === 86) return { icon: "🌨️", label: "Schneeschauer" };
  if (code >= 95) return { icon: "⛈️", label: "Gewitter" };
  return { icon: "🌡️", label: "Wetter" };
}
