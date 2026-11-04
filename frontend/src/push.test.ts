/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import sw from "../public/sw.js?raw";
import { deviceName, keyBytes, offsetLabel, pushSupported, REMINDER_CHOICES, sameKey } from "./push";

describe("Erinnerungen per Push", () => {
  it("benennt Vorlaufzeiten", () => {
    expect([10080, 20160, 4320, 1440, 180, 60, 15].map(offsetLabel)).toEqual([
      "1 Woche",
      "2 Wochen",
      "3 Tage",
      "1 Tag",
      "3 Stunden",
      "1 Stunde",
      "15 Minuten",
    ]);
  });

  it("bietet die Standardwerte 1 Woche, 1 Tag, 1 Stunde zur Auswahl an", () => {
    for (const m of [10080, 1440, 60]) expect(REMINDER_CHOICES).toContain(m);
  });

  it("liest den Server-Schlüssel (base64url) als Bytes", () => {
    expect([...keyBytes("AQID")]).toEqual([1, 2, 3]);
    expect([...keyBytes("-_8")]).toEqual([0xfb, 0xff]);
    expect(keyBytes("B" + "A".repeat(86)).length).toBe(65);
  });

  it("erkennt einen Wechsel des Server-Schlüssels", () => {
    const key = new Uint8Array([4, 1, 2]);
    expect(sameKey(new Uint8Array([4, 1, 2]).buffer, key)).toBe(true);
    expect(sameKey(new Uint8Array([4, 1, 3]).buffer, key)).toBe(false);
    expect(sameKey(new Uint8Array([4, 1]).buffer, key)).toBe(false);
    expect(sameKey(null, key)).toBe(false);
  });

  it("nennt das Gerät nur grob", () => {
    expect(deviceName("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36")).toBe("Android-Handy");
    expect(deviceName("Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 Chrome/141.0 Safari/537.36")).toBe("Android-Tablet");
    expect(deviceName("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("Windows");
  });

  it("ist ohne Browser (Node) nicht verfügbar", () => {
    expect(pushSupported()).toBe(false);
  });

  it("Service Worker zeigt Push-Nachrichten an und öffnet beim Tippen den Kalender", () => {
    expect(sw).toContain('addEventListener("push"');
    expect(sw).toContain("showNotification");
    expect(sw).toContain('addEventListener("notificationclick"');
    // kein fetch-Handler: Die Oberfläche kommt immer frisch vom Server
    expect(sw).not.toContain('addEventListener("fetch"');
  });
});
