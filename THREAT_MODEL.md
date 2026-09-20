# DataDeck Threat Model

Stand: 20.09.2026. Betrachtet werden Streamlit-App, Billing-Service, PostgreSQL,
Stripe, Gemini und die Hosting-Grenze.

## Schutzwerte

- hochgeladene Finanzdaten und daraus abgeleitete Kennzahlen
- OIDC-Identitaet, Mandantenzuordnung und Session-Zustand
- Billing- und Entitlement-Status
- API-, OIDC-, Stripe- und Datenbank-Secrets
- Verfuegbarkeit und Kostenkontrolle der Analyse-, AI- und PDF-Pfade

## Vertrauensgrenzen

| Grenze | Nicht vertrauenswuerdiger Eingang | Kontrollierter Ausgang |
|---|---|---|
| Browser -> Streamlit | Uploads, Filter, Texte, Logo, Session-Aktionen | HTML, Charts, PDF |
| Streamlit -> Gemini | aggregierte und maskierte KPI-Daten | strikt validiertes Insight-JSON |
| Streamlit -> PostgreSQL | authentifizierte Nutzeraktionen | owner-gefilterte Datensaetze |
| Browser -> Billing API | Checkout/Portal/Webhook-Requests | URLs oder generische Statusantworten |
| Stripe -> Billing API | signierter Webhook-Body | idempotente Subscription-Aktualisierung |
| Internet -> Hosting | beliebige Requests und Volumen | Proxy- und Anwendungsantworten |

## Wesentliche Bedrohungen

| Bedrohung | Auswirkung | Gegenmassnahmen | Restrisiko |
|---|---|---|---|
| Manipulierter CSV/XLSX-Upload oder ZIP-Bombe | CPU/RAM-Ausfall, Parser-Missbrauch | Typ-/Magic-/ZIP-/Groessen-/Zeilen-/Spaltenlimits, Makro/OLE/Link-Sperre, Frist, Backpressure | Bibliotheksfehler; Worker-Isolation fehlt |
| Regex-/Freitext-DoS | CPU-Auslastung | harte Text- und Scanbudgets, Stress-Tests | neue Muster muessen erneut geprueft werden |
| Prompt Injection in Daten | falsche AI-Ausgabe oder Datenabfluss | nur Aggregate, Datengrenze im Prompt, Sanitizing, striktes Schema | semantisch irrefuehrende Antworten bleiben moeglich |
| XSS/SSRF ueber Reports oder AI | Browser-/Netzwerkzugriff | Autoescape, Plain-Text-Ausgabe, keine externen PDF-Ressourcen, URL-Sperre | zukuenftige Templates muessen gleich abgesichert werden |
| IDOR/Mandantenwechsel | Einsicht oder Aenderung fremder Daten | zentrale Owner-Pruefung fuer Client, Analyse, Report; Negativtests | Fehler in neuen Repository-Pfaden |
| Session-Uebernahme oder Identitaetswechsel | Datenvermischung | OIDC, Allowlist, Session-Cleanup und Rotation | Cookie-Sicherheit haengt vom Framework/Proxy ab |
| Brute Force und Ressourcenmissbrauch | Ausfall oder Kosten | Aktionslimits, Parallelitaetsgrenzen, Circuit Breaker | In-Memory-Limits sind nicht verteilt |
| Webhook-Replay/Faelschung | falscher Pro-Status | Signatur/Toleranz, Zeitfenster, Event-ID-Idempotenz, DB-Constraints | Stripe-/DB-Ausfall erfordert Monitoring |
| SQL Injection | Datenmanipulation | parametrisierte Queries, feste SQL-Strukturen, Feldlimits | Migrationen und neue Queries brauchen Review |
| Secret-Leak in Git/Logs/UI | Konto- oder Provider-Missbrauch | Secret Store, `.gitignore`, CI-Scan, Log-Sanitizing, generische Fehler | bereits extern geteilte Secrets muessen beim Provider widerrufen werden |
| Volumetrischer DDoS | Nichtverfuegbarkeit | kleine App-Limits und Backpressure | muss auf Edge/WAF/Provider-Ebene abgewehrt werden |

## Fehlerverhalten

Authentifizierung, Autorisierung, Secrets, Billing-Signatur und Entitlements
schlagen geschlossen fehl. Gemini, PDF und externe Provider schlagen kontrolliert
fehl oder liefern einen lokalen Fallback, ohne Nutzerberechtigungen zu veraendern.

## Annahmen

- Produktion nutzt ausschliesslich HTTPS.
- Secrets liegen nur im Render Secret Store.
- PostgreSQL und Stripe laufen im Testmodus, solange Billing nicht separat aktiviert ist.
- Eine Streamlit-Instanz ist vorgesehen; horizontale Skalierung erfordert verteiltes
  Rate-Limiting und externen Session-State.
