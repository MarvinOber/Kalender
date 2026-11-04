import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Im Betrieb liefert das Backend die gebaute Oberfläche selbst aus (gleicher Ursprung, kein CORS).
// Lokal leitet der Vite-Server /api und /auth an das Backend auf Port 8080 weiter.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8080", "/auth": "http://localhost:8080" },
  },
  build: { outDir: "dist", sourcemap: false },
  // style.test.ts liest styles.css als Text (?raw); ohne das liefert Vitest für CSS nur einen leeren Text
  test: { css: { include: [/styles\.css/] } },
});
