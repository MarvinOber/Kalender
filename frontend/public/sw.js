// Service Worker des Familienkalenders – nur für Erinnerungen per Push, kein Offline-Zwischenspeicher
// (die Oberfläche lädt weiter immer frisch vom Server). Liegt in public/, damit er unter /sw.js für die ganze
// Seite gilt.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Familienkalender";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "",
      // gleiche Kennung je Termin: Die Erinnerung „1 Tag vorher“ ersetzt die von „1 Woche vorher“
      tag: data.tag || undefined,
      renotify: Boolean(data.tag),
      icon: "/icon-192.png",
      badge: "/badge-96.png",
      lang: data.lang || "de",
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
      if (open) return open.focus();
      return self.clients.openWindow(url);
    })(),
  );
});
