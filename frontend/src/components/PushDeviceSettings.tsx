import { useEffect, useState } from "react";
import { toggle } from "../filter";
import { t } from "../i18n";
import { disablePush, enablePush, pushState, type PushState, setPushPersons, syncPush, testPush } from "../push";
import type { Person } from "../types";
import { colorVar } from "./eventStyle";

interface Props {
  /** gespeicherte Personen (neue, noch nicht gespeicherte haben keine Kennung) */
  persons: Person[];
  onError: (err: unknown) => void;
}

/** Erinnerungen auf diesem Gerät ein- und ausschalten – wirkt sofort, nicht erst mit „Speichern“. */
export function PushDeviceSettings({ persons, onError }: Props) {
  const [state, setState] = useState<PushState | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    let alive = true;
    pushState()
      .then(async (st) => {
        if (!alive) return;
        setState(st);
        if (st !== "on") return;
        const device = await syncPush().catch(() => null);
        if (alive && device) setChosen(device.persons);
      })
      .catch(() => alive && setState("unsupported"));
    return () => {
      alive = false;
    };
  }, []);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setNote("");
    try {
      await fn();
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  };

  const turnOn = () =>
    act(async () => {
      const result = await enablePush(chosen);
      if (result === "denied") {
        setState(Notification.permission === "denied" ? "denied" : "off");
        return;
      }
      setChosen(result.persons);
      setState("on");
      setNote(t("Eingeschaltet. Mit „Test senden“ lässt es sich ausprobieren."));
    });

  const turnOff = () =>
    act(async () => {
      await disablePush();
      setState("off");
    });

  const sendTest = () =>
    act(async () => {
      await testPush();
      setNote(t("Test gesendet – die Benachrichtigung kommt in wenigen Sekunden."));
    });

  const choose = (next: string[]) => {
    setChosen(next);
    if (state !== "on") return;
    act(async () => {
      const device = await setPushPersons(next);
      if (device) setChosen(device.persons);
    });
  };

  return (
    <>
      <div className="chips">
        <span>
          {t("Auf diesem Gerät")}
          {state === "on" ? `: ${t("an")}` : state === "off" ? `: ${t("aus")}` : ""}
        </span>
        {state === null && <p className="small">{t("Lade …")}</p>}
        {state === "unsupported" && (
          <p className="small">
            {t("Dieser Browser kann keine Benachrichtigungen empfangen. Auf Android Chrome verwenden, auf dem iPhone die App zuerst zum Home-Bildschirm hinzufügen.")}
          </p>
        )}
        {state === "denied" && (
          <p className="small">
            {t("Benachrichtigungen sind für diese Seite blockiert. Im Browser über das Symbol links neben der Adresse → Berechtigungen → Benachrichtigungen erlauben.")}
          </p>
        )}
        {state === "off" && (
          <div>
            <button type="button" className="btn primary" disabled={busy} onClick={turnOn}>
              🔔 {t("Erinnerungen einschalten")}
            </button>
          </div>
        )}
        {state === "on" && (
          <div>
            <button type="button" className="btn" disabled={busy} onClick={sendTest}>
              {t("Test senden")}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={turnOff}>
              {t("Ausschalten")}
            </button>
          </div>
        )}
      </div>
      {(state === "on" || state === "off") && persons.length > 0 && (
        <div className="chips">
          <span>{t("Erinnern an Termine von")}</span>
          <div>
            <button type="button" className={`chip ${chosen.length ? "" : "on"}`} aria-pressed={!chosen.length} onClick={() => choose([])}>
              {t("Alle")}
            </button>
            {persons.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`chip person ${chosen.includes(p.id) ? "on" : ""}`}
                style={colorVar(p.color)}
                aria-pressed={chosen.includes(p.id)}
                onClick={() => choose(toggle(chosen, p.id))}
              >
                <i className="dot" />
                {p.name}
              </button>
            ))}
          </div>
        </div>
      )}
      {note && <p className="small">{note}</p>}
    </>
  );
}
