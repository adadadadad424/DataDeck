# DataDeck Security Notes

Stand: 20.09.2026, Version 0.9.1-beta.

## Sicherheitsgrenzen

- Uploads und Rohzeilen bleiben im RAM der jeweiligen Streamlit-Session.
- DataDeck speichert keine Upload-Dateien. PDF-Dateien entstehen als Bytes im
  Session State und verwenden keinen gemeinsamen Dateipfad.
- Gemini erhaelt ausschliesslich deterministisch berechnete Aggregate und
  begrenzte, maskierte Kategorienamen. Rohzeilen werden nicht uebertragen.
- PostgreSQL speichert bei aktivierter Historie nur Besitzerzuordnung,
  Dataset-Fingerprint, Mapping, Aggregate, freigegebene Insight-Texte und
  Report-Metadaten. Jede Abfrage wird an die angemeldete Besitzer-ID gebunden.
- Logout und Identitaetswechsel entfernen sensible Session-Daten und rotieren
  die interne Session-ID.

## Zentrale Lastgrenzen

Die Anwendung erzwingt pro Prozess Rate-, Parallelitaets- und globale Grenzen.
Die Standardwerte sind konservativ und ueber `SECURITY_<ACTION>_*` anpassbar.

| Aktion | Nutzerlimit | Parallel pro Nutzer | Parallel global |
|---|---:|---:|---:|
| Login | 10 / 10 Minuten | 1 | 50 |
| Upload | 12 / Stunde | 1 | 4 |
| Analyse | 60 / 10 Minuten | 1 | 4 |
| AI Insights | 6 / Stunde | 1 | 2 |
| PDF | 12 / Stunde | 1 | 2 |
| Checkout | 6 / Stunde | 1 | 10 |
| Portal | 12 / Stunde | 1 | 10 |
| Client-Schreibzugriff | 30 / Stunde | 1 | 10 |
| Stripe-Webhook | 120 / Minute je IP | 4 | 20 |

Ueberlastung wird frueh mit einer generischen Meldung und Wartezeit abgewiesen.
Diese In-Memory-Grenzen schuetzen eine einzelne Instanz. Sie ersetzen weder
Edge-Rate-Limiting noch WAF- oder DDoS-Schutz des Hosters.

## Upload- und Parser-Schutz

- Nur `.csv` und `.xlsx`, Standardlimit 25 MB.
- Dateiname, Endung, Magic Bytes, Binär-/Steuerzeichen und Struktur werden vor
  dem Parsen geprueft. Verzeichniswechsel und versteckte Dateinamen sind gesperrt.
- Maximal 250 Spalten, 250.000 Quellzeilen, 25 XLSX-Sheets, 2.000 ZIP-Eintraege,
  100 MB entpackter XLSX-Inhalt und 32 MB XML je relevante Arbeitsdatei.
- ZIP-Pfade, Expansion Ratio, Makros, OLE, ActiveX, externe Links und auffaellige
  deklarierte Tabellenbereiche werden abgewiesen.
- CSV-Felder sind auf 100.000 Zeichen begrenzt. Die Parser-Frist betraegt
  standardmaessig 20 Sekunden und wird zwischen kontrollierten Phasen geprueft.
- OpenPyXL liest `read_only`, `data_only` und ohne externe Links. Formeln werden
  nicht ausgefuehrt.

Die Parser-Frist ist kooperativ; ein einzelner blockierender Bibliotheksaufruf
ist kein harter Prozess-Sandbox-Timeout. Fuer oeffentliche, nicht vertrauenswuerdige
Uploads ist zusaetzliche Isolation in einem Worker-Prozess empfehlenswert.

## Inhalte, Bilder und Ausgaben

- Die PII-Erkennung begrenzt Zelltext, Anzahl gescannter Werte und Gesamtzellen.
  Sie ist eine Warnhilfe und keine vollstaendige DSGVO-Anonymisierung.
- Regex-Eingaben werden auf 2.000 Zeichen begrenzt, um pathologische Laufzeiten
  bei sehr langen Freitexten zu vermeiden.
- Report-Logos muessen gueltige PNG/JPEG-Dateien sein, werden vollstaendig
  dekodiert, auf 1 MB, 4.096 x 4.096 und 10 Millionen Pixel begrenzt und ohne
  Metadaten neu kodiert. SVG ist nicht erlaubt.
- PDF-Templates maskieren HTML, laden keine externen Ressourcen und lehnen
  Ausgaben ueber 10 MB ab.
- Ein spaeterer CSV/XLSX-Export muss Werte mit `=`, `+`, `-` oder `@` gegen
  Formula Injection neutralisieren. Aktuell gibt es keinen Tabellenexport.

## AI-Schutz

- Dataset-Texte sind im Prompt ausdruecklich als nicht vertrauenswuerdige Daten
  markiert. Typische Prompt-Direktiven und personenbezogene Muster werden entfernt.
- Das JSON-Ergebnis besitzt ein striktes Pydantic-Schema ohne Zusatzfelder sowie
  Laengen- und Mengenlimits. HTML/Steuerzeichen werden vor Anzeige entfernt.
- Nach drei Provider-Fehlern oeffnet ein Circuit Breaker standardmaessig 60
  Sekunden. Fehler fuehren zum lokalen KPI-Fallback, nicht zum Verlust der Analyse.

## Auth, Datenbank und Billing

- Produktion startet geschlossen, wenn OIDC, Allowlist oder erforderliche Secrets
  fehlen. Tokens werden nicht an die Anwendung exponiert.
- PostgreSQL nutzt begrenzte Connect-, Statement-, Lock- und Idle-Transaction-
  Zeiten. Persistierte JSON- und Textfelder haben Anwendungs- und DB-Limits.
- Zentrale Autorisierungsfunktionen pruefen Client, Analyse und Report immer gegen
  den angemeldeten Besitzer. Listen sind paginiert/begrenzt.
- Stripe-Webhooks akzeptieren maximal 256 KB, pruefen die Signatur mit 300 Sekunden
  Toleranz, verwerfen unplausible alte Events und speichern Event-IDs idempotent.
- Billing- und Autorisierungsfehler sind fail-closed. Gemini/PDF/externe Ausfaelle
  degradieren kontrolliert, ohne bestehende Nutzerdaten oder Berechtigungen zu aendern.

## Logging, Secrets und HTTP

- Logs enthalten keine Rohdaten, Dateinamen, E-Mail-Adressen, Prompts, Tokens oder
  Provider-Antworttexte. Steuerzeichen und Zeilenumbrueche werden neutralisiert.
- Unerwartete UI-Fehler zeigen nur eine zufaellige Korrelations-ID.
- `.env`, Schluessel und lokale Datenbanken sind nicht versioniert. CI prueft
  Quelltexte auf typische reale Google-, Stripe-, Webhook-, PostgreSQL- und
  Private-Key-Muster, ohne gefundene Werte auszugeben.
- Der Billing-Service setzt CSP, Frame-Schutz, `nosniff`, `no-store`, Referrer- und
  Permissions-Policy. HSTS und die finalen Streamlit-/OIDC-Cookie-Attribute muessen
  an der echten HTTPS-Domain bzw. am Reverse Proxy geprueft werden.

## Bekannte Restrisiken

- Kein Anwendungscode kann volumetrische DDoS-Angriffe allein abwehren. Vor einer
  oeffentlichen Beta sind Edge-Rate-Limits, WAF, Request-Body-Limits und Alarmierung
  beim Hosting-Provider erforderlich.
- In-Memory-Limits werden bei Prozessneustart zurueckgesetzt und sind nicht zwischen
  mehreren Instanzen geteilt.
- Es gibt keine Malware-Engine, keinen persistenten Security-Audit-Stream und noch
  keinen externen Penetrationstest.
- PII-Erkennung kann falsch-positive und falsch-negative Ergebnisse liefern.
- Der Feedback-Link ist extern; Missbrauchsschutz muss dort konfiguriert werden.
- Vor bezahlter oder oeffentlicher Nutzung bleiben Datenschutzpruefung, AV-Vertraege,
  Loeschkonzept, Backup-Restore-Test und Incident-Prozess erforderlich.
