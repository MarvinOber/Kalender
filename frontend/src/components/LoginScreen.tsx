import { t } from "../i18n";

const ERRORS: Record<string, string> = {
  nicht_freigegeben: "Diese Google-Adresse ist für den Familienkalender nicht freigegeben.",
  kein_kalender: "Ohne Zugriff auf Google Kalender geht es nicht. Bitte bei der Anmeldung den Kalenderzugriff erlauben.",
  kein_refresh: "Google hat keinen dauerhaften Zugang erteilt. Bitte erneut anmelden.",
  abgebrochen: "Die Anmeldung wurde abgebrochen.",
  ungueltig: "Die Anmeldung ist abgelaufen. Bitte noch einmal versuchen.",
  google: "Google ist gerade nicht erreichbar. Bitte später noch einmal versuchen.",
};

export function LoginScreen() {
  const code = new URLSearchParams(window.location.search).get("login_error") || "";
  return (
    <div className="login">
      <div className="login-card">
        <img src="/favicon.svg" alt="" width={72} height={72} />
        <h1>Familienkalender</h1>
        {code && <p className="notice error">{ERRORS[code] || "Die Anmeldung hat nicht geklappt."}</p>}
        <a className="btn primary big" href="/auth/login">
          {t("Mit Google anmelden")}
        </a>
        <p className="small">Zugang nur für freigegebene Adressen der Familie.</p>
      </div>
    </div>
  );
}
