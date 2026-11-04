import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import { applyStyle, loadStyle } from "./style";
import { registerWorker } from "./push";

// Stil vor dem ersten Zeichnen setzen, sonst blitzt kurz „Klassisch“ auf
applyStyle(loadStyle());
// Service Worker nur für Erinnerungen per Push (kein Offline-Zwischenspeicher)
registerWorker();

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
