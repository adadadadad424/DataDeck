# DataDeck Mandantenhistorie

## Zweck

Die Mandantenhistorie ergänzt die bestehende Schnellanalyse um wiederkehrende
Analyseperioden. Sie ist bewusst kein CRM. Kontakte, Aufgaben, Deals und
E-Mail-Tracking gehören nicht zu diesem Modul.

## Gespeicherte Daten

- Mandantenname und optionale interne Referenz
- Analysezeitraum und Upload-Zeitpunkt
- SHA-256-Fingerprint des Datasets
- bestätigtes Spaltenmapping und Qualitätsstatus
- aggregierte KPI-, Segment- und Zeitreihenergebnisse
- vom Berater freigegebene Summary, Insights und Kommentar
- Report-Einstellungen, Version, Erstellzeitpunkt und PDF-Hash

Nicht gespeichert werden Upload-Dateien, Rohzeilen, Tabellen-Vorschauen oder
erkannte personenbezogene Werte. PDF-Dateien und Logos bleiben aktuell nur in
der geschützten Streamlit-Sitzung und werden nicht in öffentlichen URLs
abgelegt.

## Isolation

Jeder Lese-, Schreib- und Löschzugriff enthält `owner_user_id`. Zusätzlich
erzwingen zusammengesetzte Fremdschlüssel in PostgreSQL, dass Mandant, Analyse
und Report-Version demselben Eigentümer zugeordnet sind. Das Löschen eines
Mandanten entfernt dessen Analyse- und Report-Metadaten per Cascade.

## Migration

Die Tabellen werden durch `billing/migrations/002_consultant_workspace.sql`
angelegt. Die Migration ist wiederholbar über den zentralen Migration Runner:

```bash
DATABASE_URL=... python -m billing.migrate
```

Secrets gehören ausschließlich in die Umgebungsvariablen des Hosting-Dienstes,
nicht in Git, Logs oder Support-Chats. Vor erfolgreicher Migration bleibt die
Schnellanalyse funktionsfähig; die Mandantenhistorie wird als nicht verfügbar
angezeigt.

## Vergleichsregeln

- MoM nur für aufeinanderfolgende Monatsperioden
- QoQ nur für vollständige Kalenderquartale
- YoY nur für den gleichen Kalenderausschnitt im Vorjahr
- YTD nur bei vollständigen Monatsreihen beider Jahre
- Margenänderungen in Prozentpunkten, Umsatz/Gewinn in Prozent
- Trendhinweise erst ab drei lückenlosen, vergleichbaren Perioden
- 3- und 6-Monats-Durchschnitte nur bei lückenlosen Monatsperioden

Mehrere Währungen werden ohne belastbare Wechselkurse nicht summiert.
