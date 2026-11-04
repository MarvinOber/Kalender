import { t } from "./i18n";

/** Woher das Foto kommt: „camera“ öffnet die Kamera direkt (`capture`), „gallery“ die Bildauswahl des Geräts. */
export type PhotoSource = "camera" | "gallery";

/**
 * Nur Touch-Geräte (Handy, Tablet) öffnen bei `capture` die Kamera; Desktop-Browser ignorieren es und zeigen
 * den Dateidialog. Dort gibt es deshalb keine Auswahl, der Knopf öffnet gleich die Dateien.
 */
export function cameraAvailable(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(pointer: coarse)").matches;
}

/** Längste Seite nach dem Verkleinern: reicht für Handschrift auf einer Kalenderseite, bleibt meist unter 1 MB. */
export const MAX_SIDE = 2048;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // wie MAX_IMAGE_BYTES im Backend
const SENDABLE = /^image\/(jpeg|png|webp|gif)$/;

export class PhotoError extends Error {}

/** Maße, die in ein Quadrat von `max` Pixeln passen; kleinere Bilder bleiben, wie sie sind. */
export function fitWithin(width: number, height: number, max = MAX_SIDE): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/**
 * Foto für den Upload vorbereiten: verkleinern und als JPEG neu speichern. Dabei fallen die Metadaten weg
 * (z. B. der Aufnahmeort); die Drehung aus der Kamera übernimmt der Browser beim Einlesen.
 */
export async function prepareImage(file: File): Promise<Blob> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return original(file); // z. B. HEIC in einem Browser, der es nicht lesen kann
  }
  try {
    const { width, height } = fitWithin(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return original(file);
    ctx.fillStyle = "#fff"; // transparente PNGs nicht schwarz werden lassen
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    return blob ?? original(file);
  } finally {
    bitmap.close();
  }
}

function original(file: File): Blob {
  if (!SENDABLE.test(file.type)) {
    throw new PhotoError(t("Dieses Bild lässt sich nicht öffnen. Bitte ein Foto als JPEG oder PNG wählen."));
  }
  if (file.size > MAX_UPLOAD_BYTES) throw new PhotoError(t("Das Foto ist zu groß (höchstens 10 MB)."));
  return file;
}
