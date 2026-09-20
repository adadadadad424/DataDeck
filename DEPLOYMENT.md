# DataDeck Deployment

## Gewählte Plattform

Für die geschlossene Beta ist Render vorgesehen: Docker- und WebSocket-Support,
verwaltetes HTTPS, Frankfurt-Region, HTTP-Healthchecks und schnelle Rollbacks bei
geringer operativer Komplexität. Die erste technische Online-Validierung läuft auf
einer kostenlosen Einzelinstanz mit 0,1 CPU, 512 MB RAM und ohne persistenten
Datenträger. Vor einer Beta mit mehreren gleichzeitigen Nutzern wird anhand der
Lasttests entschieden, ob ein kostenpflichtiger Plan erforderlich ist.

Cloud Run wurde für diese erste Stufe nicht gewählt. Streamlit hält Sessiondaten im
Prozess; Cloud Runs Session Affinity ist nur best effort und WebSockets unterliegen
Request-Timeouts. Eine horizontale Architektur braucht deshalb zunächst externen State.

## Production Build

`Dockerfile` installiert ausschließlich gepinnte Laufzeitabhängigkeiten und startet als
unprivilegierter Nutzer. `.dockerignore` entfernt Secrets, lokale Artefakte, Tests,
Screenshots, Logs, Git-Metadaten und Upload-/PDF-Ausgaben aus dem Build-Kontext.

`production_start.py` validiert die vollständige Production-Konfiguration und verweigert
den Start mit Exit-Code 78, wenn etwas fehlt. Erst danach wird eine nur für den
Container gültige OIDC-Konfiguration mit Dateirechten `0600` erzeugt und Streamlit
gestartet. Der Wert eines Secrets wird dabei nie ausgegeben.

## Render Blueprint

`render.yaml` definiert Region, Plan, Einzelinstanz, Limits und Healthcheck. Werte mit
`sync: false` werden ausschließlich im Render-Dashboard eingetragen. Das Blueprint
enthält keine Credentials.

Der Free-Plan ist nur für technische Validierung und eine sehr kleine geschlossene
Beta vorgesehen. Er kann bei Inaktivität herunterfahren, hat begrenzte monatliche
Laufzeit und bietet nur 512 MB RAM. Kaltstarts und fehlende Kapazität für parallele
große Uploads sind daher erwartbare Plattformgrenzen und keine App-Fehler.

Für Production gelten zunächst:

- maximal 25 MB Upload
- maximal 100.000 Premium-Zeilen
- maximal 250 Spalten
- maximal 25 XLSX-Sheets
- maximal 100 MB entpackter XLSX-Inhalt
- genau eine App-Instanz

## Domain und OIDC

Erster Test über die verwaltete Render-HTTPS-Domain. Danach kann eine eigene Domain
verbunden werden. Bei jedem Domainwechsel müssen `OIDC_REDIRECT_URI` in Render und die
autorisierte Redirect URI im Google-OAuth-Client identisch auf
`https://<domain>/oauth2callback` gesetzt werden.

Production nutzt genau einen, unbenannten Google-OIDC-Provider. Streamlit übernimmt
State, Nonce und Tokenvalidierung. `expose_tokens = []` verhindert die Freigabe von
ID-/Access-Token an die App.

## CI und Release

`.github/workflows/ci.yml` führt Syntaxprüfung, alle QA-Suiten, `pip check` und
`pip-audit` aus. Render deployt nur nach bestandenen Checks. Das Projekt muss dafür in
ein privates GitHub-Repository übernommen werden.

## Health, Logs und Rollback

Healthcheck: `/_stcore/health`. Render startet eine nicht mehr reagierende Instanz neu.
Ein externer Uptime-Monitor wird zusätzlich eingerichtet.

Logs enthalten nur technische Metadaten und Korrelations-IDs. Der konkrete Betriebs-
und Rollbackablauf steht in `PRODUCTION_RUNBOOK.md`, Notfälle in
`INCIDENT_RESPONSE.md`.

## Persistenzgrenze

Upload, DataFrame, Analyse und PDF liegen nur im Arbeitsspeicher der jeweiligen Session.
Es gibt keine persistente Speicherung oder Backups von Kundendateien. Allowlist und
Secrets liegen im Render Secret Store; Quellcode und Deployment-Konfiguration werden
über das private Repository versioniert.

Wenn Billing später aktiviert wird, speichert eine getrennte PostgreSQL-Datenbank nur
Nutzerzuordnung, Stripe-IDs, Abo-Status und verarbeitete Event-IDs. Uploads, Kennzahlen,
KI-Inhalte und PDFs werden nicht in diese Datenbank geschrieben. Der unabhängige
Webhook-Dienst verwendet `Dockerfile.billing`; Einrichtung und Migration stehen in
`BILLING.md`.
