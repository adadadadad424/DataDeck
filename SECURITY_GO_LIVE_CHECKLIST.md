# DataDeck Security Go-Live Checklist

Stand: 20.09.2026. Checkboxen mit `[ ]` sind reale Launch-Blocker oder manuelle
Abnahmen, keine automatisch als erledigt angenommenen Punkte.

## Im Code verifiziert

- [x] Auth und Allowlist sind in Produktion fail-closed.
- [x] Identitaetswechsel und Logout loeschen sensible Session-Daten.
- [x] Mandanten-, Analyse- und Reportzugriffe pruefen zentral den Besitzer.
- [x] Upload-, XLSX-/ZIP-, CSV-, Logo-, PII- und Ausgabegrenzen sind aktiv.
- [x] AI bekommt keine Rohzeilen und validiert Antworten gegen ein striktes Schema.
- [x] PDF-HTML wird escaped; externe Ressourcen und uebergrosse PDFs sind gesperrt.
- [x] Stripe-Webhooks pruefen Signatur, Zeitfenster, Body-Limit und Idempotenz.
- [x] PostgreSQL-Verbindungen und Abfragen besitzen Zeitlimits.
- [x] Rate-, Parallelitaets-, Backpressure- und Circuit-Breaker-Tests bestehen.
- [x] CI fuehrt Gesamt-QA, Secret-Scan, `pip check` und `pip-audit` aus.

## Vor oeffentlichem Zugriff

- [ ] Finale HTTPS-Domain, Redirect-URI und OIDC-Login/Logout end-to-end pruefen.
- [ ] Streamlit Identity Cookie auf `Secure`, `HttpOnly` und passendes `SameSite` pruefen.
- [ ] HSTS, Proxy-Body-Limit, Edge-Rate-Limits und WAF beim Hoster aktivieren/pruefen.
- [ ] Nur benoetigte Render-Secrets setzen; alte/offengelegte Provider-Keys widerrufen.
- [ ] Alarmierung fuer 5xx, hohe Latenz, Speicher, Restarts, AI- und Webhook-Fehler setzen.
- [ ] PostgreSQL-Backup, Restore und Migration `003_security_constraints.sql` testen.
- [ ] Datenschutzerklaerung, Impressum, AV-Vertraege, Loesch- und Incident-Prozess pruefen.
- [ ] Externen Penetrationstest bzw. unabhaengiges Security Review terminieren.

## Nur bei Billing-Aktivierung

- [ ] Ausschliesslich Stripe-Testkeys und Test-Price verwenden.
- [ ] Webhook-Secret getrennt im Render Secret Store setzen.
- [ ] Checkout, Portal, Zahlungsausfall, Kuendigung und Duplicate Event end-to-end pruefen.
- [ ] Billing erst nach bestandenem Testlauf mit `BILLING_ENABLED=true` aktivieren.
