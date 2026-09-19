# DataDeck Closed Beta Runbook

## Zielarchitektur

- Render Web Service in Frankfurt
- Docker Runtime, Plan `1c-2g`, genau eine Instanz
- verwaltetes HTTPS und WebSocket-Unterstützung
- Google OIDC, serverseitige E-Mail-Allowlist
- keine Datenbank und kein persistenter Datenträger
- Uploads und PDFs ausschließlich im Session-Speicher

Eine Instanz ist für die erste Beta bewusst gewählt: Streamlit hält den aktiven
Datensatz im Prozessspeicher. Horizontale Skalierung kommt erst nach einer expliziten
State-Architektur infrage.

## Vor dem ersten Deploy

1. Privates Git-Repository erstellen und nur die bereinigten Projektdateien hochladen.
2. In Google Cloud einen Web-OAuth-Client anlegen.
3. Render Blueprint aus `render.yaml` verbinden.
4. Beim Blueprint-Dialog alle mit `sync: false` markierten Werte eintragen.
5. Zunächst die Render-HTTPS-URL als `OIDC_REDIRECT_URI` verwenden:
   `https://<render-host>/oauth2callback`.
6. Genau diese URI bei Google als autorisierte Redirect URI eintragen.
7. Erst nach erfolgreichem Test eine eigene Domain verbinden und beide Seiten aktualisieren.

## Pflichtvariablen

`production_start.py` verweigert den Start, falls eine Pflichtvariable fehlt, eine URL
nicht HTTPS nutzt, der Redirect nicht auf `/oauth2callback` endet oder das Cookie-Secret
zu kurz ist. Secret-Werte werden nicht in die Fehlermeldung geschrieben.

Die vier Rechts-/Feedback-URLs müssen auf vom Betreiber freigegebene Inhalte zeigen.
DataDeck erzeugt dafür bewusst keine Rechtstexte.

## Release-Prüfung

```bash
python -m py_compile main.py production_start.py core/*.py qa*.py
python qa_test_final.py
python qa_runtime.py
python qa_beta_security.py
python qa_production.py
python qa_golden_datasets.py
python -m pip check
pip-audit -r requirements.txt
```

Danach Render-Deploy starten und `/_stcore/health` prüfen. Deployment nur fortsetzen,
wenn alle Checks grün sind.

## OIDC-Abnahme

Mit privatem Browserfenster testen:

1. Ohne Login erscheint ausschließlich die Loginseite.
2. Freigegebenes Google-Konto erreicht das Dashboard.
3. Nicht freigegebenes Konto sieht die Ablehnung und keine Daten.
4. Browser-Konsole und Render-Logs enthalten keine Token.
5. Logout entfernt DataFrame, Mapping, KI-Ergebnis und PDF aus der Session.
6. Browser-Zurück zeigt keine wiederhergestellten Kundendaten.

Streamlit handhabt OIDC `state` und `nonce` selbst. Token werden durch
`expose_tokens = []` nicht an die App freigegeben. Der Identity-Cookie läuft nach
30 Tagen ab; DataDeck prüft zusätzlich den `exp`-Claim des Identity-Tokens.

## Production-Abnahme

- ALPHA/BETA mit zwei Browserprofilen gleichzeitig testen.
- Danach 1, 2, 5 und 10 Nutzer stufenweise simulieren.
- Bei jeder Stufe RAM, CPU, Antwortzeit, Fehler und Restarts notieren.
- Lasttest abbrechen bei OOM, Session-Abbrüchen oder dauerhaft über 85 Prozent RAM.
- 10k, 40k und 100k separat messen; zwei gleichzeitige 100k-Uploads prüfen.
- Gemini nur mit synthetischen Daten und gesetztem Kostenlimit testen.

## Monitoring

Render Healthcheck nutzt `/_stcore/health`. Zusätzlich einen externen HTTPS-Uptime-
Monitor auf denselben Pfad setzen. Alerts mindestens für Ausfall, Restarts, hohen RAM,
`UNEXPECTED_ERROR`, `AI_PROVIDER_ERROR` und `PDF_ERROR` konfigurieren.

Logs enthalten keine Rohdaten. Externes Error Tracking wird erst aktiviert, wenn
automatische Local-Variable-/Request-Body-Erfassung sicher deaktiviert und PII-Scrubbing
getestet wurde.

## Secret-Rotation

Gemini:

1. Neuen Schlüssel in Google AI Studio/Cloud erzeugen und beschränken.
2. Render `GEMINI_API_KEY` ersetzen, Service neu deployen.
3. AI mit Demo-Daten prüfen, dann alten Schlüssel widerrufen.

OIDC:

1. Neues Client-Secret bei Google erzeugen.
2. Render `OIDC_CLIENT_SECRET` ersetzen und neu deployen.
3. Login/Logout prüfen, anschließend altes Secret widerrufen.

Cookie-Secret-Rotation meldet alle Nutzer ab und wird deshalb angekündigt durchgeführt.

## Rollback

Render Service > Deploys > letzter erfolgreicher Deploy > `Rollback`. Render behält die
aktuelle Secret-Konfiguration bei. Nach Rollback Health, Login, Upload, Gemini und PDF
testen. Der Rollback gilt erst als bestanden, wenn dieser Ablauf einmal mit zwei harmlosen
Test-Releases praktisch durchgeführt wurde.

## Betriebskosten

Der Render-Plan `1c-2g` kostet derzeit 25 USD pro Monat. Hinzu kommen Domain,
Uptime-Monitor und variable Gemini-Nutzung. Quota- und Budgetalarme sind vor realen
Tester-Einladungen Pflicht.

