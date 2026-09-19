# DataDeck Beta Launch Checklist

## Technisch verifiziert

- [x] Kern-QA und echter Streamlit-Runtime-Flow
- [x] Zwei getrennte Sessions mit ALPHA-/BETA-Daten
- [x] Upload-Größe, Dateityp, Binär-CSV, Spaltenlimit und XLSX-ZIP-Schutz
- [x] Keine gemeinsamen Upload-, Analyse- oder PDF-Dateipfade
- [x] Logout-Cleanup für sensible Sessiondaten
- [x] Production sperrt ohne Auth und Allowlist
- [x] Gemini erhält keine Rohzeilen; Kategorie-PII wird maskiert
- [x] Revenue-only zeigt keinen erfundenen Gewinn
- [x] Gemischte Währungen werden nicht summiert
- [x] PDF bleibt aus derselben zentralen KPI-Basis erzeugt
- [x] Abhängigkeiten exakt gepinnt und `.env` ignoriert
- [x] Fail-closed Production-Start und HTTPS-URL-Prüfung
- [x] Render-Blueprint für Frankfurt, Einzelinstanz und Healthcheck
- [x] CI-Workflow mit vollständiger Release-QA
- [x] Fünf Golden-Datasets mit bekannten Ergebnissen
- [x] Incident- und Production-Runbook
- [x] Keine extern geladenen Fonts oder Tracking-Ressourcen

## Vor Einladung echter Tester zwingend

- [x] Hosting-Ziel Render und Region Frankfurt festgelegt
- [ ] Privates GitHub-Repository erstellen und Render verbinden
- [ ] Domain, HTTPS und Reverse-Proxy-Sicherheitsheader konfigurieren
- [ ] OIDC-Provider, Redirect-URL, Session-Ablauf und Logout end-to-end testen
- [ ] Nur echte Beta-E-Mails in `BETA_APPROVED_USERS` freigeben
- [ ] Gemini-Schlüssel rotieren, beschränken und Budget-/Quota-Alarm setzen
- [ ] Datenschutzerklärung, Impressum und Nutzungsbedingungen rechtlich freigeben
- [ ] Google-Datenverarbeitung, DPA, Retention und Region dokumentieren
- [ ] Support- und Feedbackkanal benennen
- [ ] Monitoring und Alarmempfänger testen
- [ ] Externen Uptime-Monitor auf `/_stcore/health` einrichten
- [ ] Cookie-Name und Secure/HttpOnly/SameSite an finaler Domain prüfen
- [ ] 1/2/5/10-Nutzer-Lasttest und 2 parallele 100k-Uploads auf Render
- [ ] ALPHA/BETA-Isolation mit zwei echten Browserprofilen auf Render
- [ ] Secret-Rotation und Version-A/B/A-Rollback praktisch durchführen
- [ ] Restore-/Rollback-Probe durchführen
- [ ] Geheimnis-Scan im finalen Repository und Container-Image wiederholen

## Vor öffentlichem oder bezahltem Launch

- [ ] Externer Security-/Penetrationstest
- [ ] Datenschutz-Folgen- und Löschkonzept je Zielmarkt prüfen
- [ ] Zentrales, serverübergreifendes Rate Limiting
- [ ] Persistente Nutzer-/Mandantenarchitektur nur mit sauberem Berechtigungsmodell
- [ ] Verfügbarkeit, SLA, Backups und Incident-Kommunikation definieren
- [ ] Billing, Limits und Premium-Bezeichnungen real an Produktlogik koppeln
- [ ] Barrierefreiheits- und Browserprüfung mit Zielgeräten
