# DataDeck Security Notes

Stand: 18.09.2026, Version 0.8.0-beta.

## Datenfluss

1. CSV/XLSX wird als Bytes im Arbeitsspeicher der jeweiligen Streamlit-Session empfangen.
2. Dateityp, Größe, Binärinhalt, Spaltenzahl und XLSX-ZIP-Struktur werden geprüft.
3. Pandas/OpenPyXL lesen die Datei aus dem Speicher. DataDeck legt keine Upload-Datei ab.
4. Bereinigte Daten und Ergebnisse liegen ausschließlich in `st.session_state` dieser Session.
5. PDF-Reports entstehen als Bytes im Session State, nicht als gemeinsamer Dateipfad.
6. Gemini erhält nur aggregierte KPIs und bereinigte Kategorienamen. Rohzeilen werden nicht übertragen.

## Isolation

- Es existieren keine globalen DataFrames, Uploads, Analyseergebnisse oder PDF-Pfade.
- Der Dataset-Schlüssel basiert auf SHA-256 des Inhalts, nicht nur auf dem Dateinamen.
- Filter, Mapping, KI-Ergebnis und PDF werden pro Streamlit-Session gehalten.
- Logout entfernt hochgeladene und abgeleitete Kundendaten aus der Session.
- Ein automatisierter ALPHA-/BETA-Test prüft zwei getrennte App-Sessions mit demselben Dateinamen.

Streamlit-Sessions sind an die WebSocket-Sitzung gebunden. Ein Refresh oder Server-Neustart
kann den Zustand verwerfen. DataDeck verspricht in dieser Beta keine dauerhafte Speicherung.
Der OIDC-Login-Cookie kann zwischen Tabs geteilt werden; die Datenzustände der Tabs bleiben
getrennte Streamlit-Sessions.

## Zugriffsschutz

Production läuft standardmäßig nur mit Streamlit OIDC und serverseitiger E-Mail-Allowlist.
Eigene Passwortspeicherung wurde bewusst nicht implementiert. In `APP_ENV=production`
sperrt DataDeck den Zugriff, wenn Auth deaktiviert oder die Allowlist leer ist.

Erforderlich:

- OIDC-Provider in `.streamlit/secrets.toml` oder im Secret Store der Plattform
- `AUTH_REQUIRED=true`
- `BETA_APPROVED_USERS=<kommagetrennte freigegebene E-Mails>`
- HTTPS und sichere Redirect-URL auf der endgültigen Domain

Production nutzt einen einzelnen, unbenannten Google-OIDC-Provider. Streamlit verwaltet
`state` und `nonce`; `expose_tokens = []` verhindert, dass Provider-Token in `st.user`
oder Anwendungslogs gelangen.

## Cookies

| Cookie | Zweck | Lebensdauer | Sicherheitsprüfung |
|---|---|---|---|
| Streamlit Identity Cookie | Anmeldung zwischen Sessions | 30 Tage oder bis Logout | Exakter Framework-Name sowie Secure, HttpOnly und SameSite werden beim HTTPS-OIDC-Abnahmetest im Browser protokolliert. |
| Provider-Cookies | Google-Anmeldung | durch Google bestimmt | Werden nicht von DataDeck gesetzt oder beim DataDeck-Logout gelöscht. |

DataDeck setzt keine Tracking- oder Marketing-Cookies. Die noch offene Live-Prüfung ist
bewusst dokumentiert, weil Cookie-Attribute erst an der finalen HTTPS-Domain belastbar
verifiziert werden können.

## Upload-Schutz

- nur `.csv` und `.xlsx`; altes `.xls` wird abgelehnt
- Standardlimit 50 MB, maximal 100.000 Premium-Zeilen, 250 Spalten
- maximal 50 XLSX-Sheets und 250 MB entpackter XLSX-Inhalt
- Erkennung verdächtiger Kompressionsraten, externer Links und VBA-Bestandteile
- OpenPyXL läuft mit `read_only`, `data_only` und deaktivierten externen Links
- Formeln werden nicht ausgeführt; es werden vorhandene Zellwerte gelesen

## Datenminimierung

Analytisch notwendig sind Umsatz sowie optional Gewinn/Kosten, Kategorie und Datum.
Andere Spalten bleiben für die lokale Vorschau verfügbar, werden dort aber per
Mustererkennung maskiert. E-Mail, Telefon, IBAN, Karten-, Steuer-, Adress- und weitere
Muster werden erkannt. Die Erkennung ist eine Hilfestellung und keine vollständige
DSGVO-Anonymisierung. Hochsensible Freitexte sollten vor Upload entfernt werden.

Gemini-Anfragen enthalten aggregierte Beträge, Margen, Zeitvergleiche, Datenqualitätswerte
und maskierte/gekürzte Kategorienamen. Welche Aufbewahrung für die konfigurierte Google-
Organisation gilt, muss vor Beta-Start anhand Vertrag, Region und Google-Einstellungen
geprüft und in der Datenschutzerklärung genannt werden.

## Logging und Fehler

Logs enthalten Ereignistyp, zufällige Korrelations-ID, anonymisierte Nutzer-ID,
Dataset-Hash-Präfix, Mengen, Laufzeiten und Exception-Klasse. Dateinamen, Rohdaten,
Prompt-Inhalte, E-Mail-Adressen und API-Fehlertexte werden nicht protokolliert.
Unerwartete UI-Fehler zeigen nur eine Korrelations-ID.

## Bekannte Grenzen

- Keine Malware-Engine; Upload-Schutz ist Struktur- und Ressourcenprüfung.
- Rate Limits sind sessionlokal, nicht verteilt über mehrere Serverinstanzen.
- Keine persistente Audit-Datenbank oder externe Monitoring-Plattform konfiguriert.
- Security Header, TLS, Request-Limits und IP-Rate-Limits müssen am Hosting-Proxy gesetzt werden.
- PII-Erkennung kann falsch-positive und falsch-negative Treffer liefern.
- Mehrere Währungen werden erkannt und nicht zusammengerechnet; Wechselkursumrechnung existiert nicht.
- Es gibt keinen CSV-/Excel-Export. Ein zukünftiger Tabellenexport muss Werte mit `=`, `+`, `-` oder `@` gegen Formula Injection neutralisieren.
- OIDC muss mit dem endgültigen Provider und der endgültigen Domain separat end-to-end geprüft werden.
- Eine einzelne Render-Instanz ist absichtlich vorgegeben; horizontale Skalierung ohne externen Session-State ist nicht freigegeben.

Vor einer öffentlichen oder bezahlten Nutzung sind Penetrationstest, Datenschutzprüfung,
Auftragsverarbeitungsverträge, Löschkonzept und Incident-Prozess erforderlich.
