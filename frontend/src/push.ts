import { api } from "./api";
import { t } from "./i18n";
import type { PushDevice } from "./types";

/**
 * Erinnerungen per Push: Service Worker (`public/sw.js`) anmelden, beim Push-Dienst des Browsers abonnieren und
 * das Abo an den Server geben. Der Server schickt dann zu jedem Termin die eingestellten Erinnerungen.
 */

export type PushState = "unsupported" | "denied" | "off" | "on";

/** Auswahl für die Vorlaufzeiten in den Einstellungen (Minuten); Standard 1 Woche, 1 Tag, 1 Stunde. */
export const REMINDER_CHOICES = [7 * 1440, 3 * 1440, 1440, 3 * 60, 60, 15];

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** Text für eine Vorlaufzeit, z. B. „1 Woche“, „3 Tage“, „15 Minuten“ (deutsch = Übersetzungsschlüssel). */
export function offsetLabel(minutes: number): string {
  const unit = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  if (minutes % (7 * 1440) === 0) return unit(minutes / (7 * 1440), "Woche", "Wochen");
  if (minutes % 1440 === 0) return unit(minutes / 1440, "Tag", "Tage");
  if (minutes % 60 === 0) return unit(minutes / 60, "Stunde", "Stunden");
  return unit(minutes, "Minute", "Minuten");
}

/** Öffentlicher Server-Schlüssel (base64url) als Bytes für `pushManager.subscribe`. */
export function keyBytes(base64url: string): Uint8Array {
  const b64 = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

/** Gehört das Abo zum aktuellen Server-Schlüssel? Nach einem Schlüsselwechsel muss neu abonniert werden. */
export function sameKey(current: ArrayBuffer | null | undefined, key: Uint8Array): boolean {
  if (!current) return false;
  const a = new Uint8Array(current);
  return a.length === key.length && a.every((b, i) => b === key[i]);
}

/** Kurzer Gerätename für die Abo-Liste auf dem Server (kein vollständiger User-Agent). */
export function deviceName(ua: string): string {
  if (/Android/i.test(ua)) return /Mobile/i.test(ua) ? "Android-Handy" : "Android-Tablet";
  if (/iPhone|iPad/i.test(ua)) return "iPhone/iPad";
  if (/Windows/i.test(ua)) return "Windows";
  if (/Macintosh/i.test(ua)) return "Mac";
  if (/Linux/i.test(ua)) return "Linux";
  return "";
}

export function registerWorker(): void {
  if (!pushSupported()) return;
  navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  if (!reg) await navigator.serviceWorker.register("/sw.js");
  return navigator.serviceWorker.ready;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  const sub = Notification.permission === "granted" ? await currentSubscription() : null;
  return sub ? "on" : "off";
}

async function subscribe(key: string): Promise<PushSubscription> {
  const reg = await registration();
  const bytes = keyBytes(key);
  let sub = await reg.pushManager.getSubscription();
  if (sub && !sameKey(sub.options.applicationServerKey, bytes)) {
    await sub.unsubscribe();
    sub = null;
  }
  return sub ?? reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes });
}

/** Einschalten (fragt nach der Erlaubnis – nur aus einem Tippen heraus aufrufen). */
export async function enablePush(persons: string[]): Promise<PushDevice | "denied"> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  const { key } = await api.pushKey();
  if (!key) throw new Error(t("Benachrichtigungen sind auf dem Server nicht eingerichtet."));
  const sub = await subscribe(key);
  return api.pushSubscribe(sub.toJSON(), persons, deviceName(navigator.userAgent));
}

export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.pushUnsubscribe(sub.endpoint).catch(() => undefined);
  await sub.unsubscribe();
}

/** Personen für dieses Gerät ändern (Abo bleibt). */
export async function setPushPersons(persons: string[]): Promise<PushDevice | null> {
  const sub = await currentSubscription();
  return sub ? api.pushSubscribe(sub.toJSON(), persons, deviceName(navigator.userAgent)) : null;
}

/**
 * Beim Start: Abo mit dem Server abgleichen (der Browser kann es erneuert haben, der Server-Schlüssel kann neu
 * sein). Fragt nie nach einer Erlaubnis. Liefert die Auswahl auf dem Server oder `null`, wenn aus.
 */
export async function syncPush(): Promise<PushDevice | null> {
  if (!pushSupported() || Notification.permission !== "granted") return null;
  const existing = await currentSubscription();
  if (!existing) return null;
  const { key } = await api.pushKey();
  if (!key) return null;
  const sub = await subscribe(key);
  return api.pushSubscribe(sub.toJSON(), null, deviceName(navigator.userAgent));
}

export async function testPush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) throw new Error(t("Erinnerungen sind auf diesem Gerät aus."));
  await api.pushTest(sub.endpoint);
}
