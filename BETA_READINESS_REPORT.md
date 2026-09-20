# DataDeck Closed-Beta Readiness

Stand: 20.09.2026

## Ergebnis

**NO-GO für externe Tester**, bis die drei Sicherheitsblocker unter `MUST FIX`
geschlossen sind. Die Kernanwendung selbst ist stabil und lokal vollständig grün.

## Verifizierte Evidenz

- Render-Deployment `09df910` ist live auf dem kostenlosen Frankfurt-Service.
- `/_stcore/health` antwortete mit HTTP 200 in 0,17 Sekunden bei warmer Instanz.
- Live-OIDC leitete zu Google, forderte nur `openid`, `email` und `profile` an und
  brachte das freigegebene Konto zurück ins DataDeck-Dashboard.
- Render-Logs zeigten `LOGIN_SUCCESS` nur mit Korrelations-ID und gehashter Nutzer-ID;
  keine E-Mail, Provider-Token, Upload-Inhalte oder API-Schlüssel waren sichtbar.
- Demo-Daten wurden live analysiert; PII in der Detailvorschau war maskiert.
- Render Free weist auf mögliche Wake-up-Verzögerungen von 50 Sekunden oder mehr hin.
- Der Free-Plan hat 512 MB RAM und 0,15 CPU. Tatsächliche RAM-/CPU-Zeitreihen sind auf
  diesem Plan im Render-Dashboard nicht verfügbar.
- Arbeitsbaum, gesamte Git-Historie und drei lokale Release-ZIPs enthielten kein
  erkanntes Gemini-Key-Muster. Die lokale `.env`, der Shell-Export und die persistente
  Launch-Variable wurden entfernt.
- Ein neuer, ausschließlich für die Gemini API freigegebener Produktionsschlüssel ist
  an das Dienstkonto `datadeck-gemini@datadeck-beta.iam.gserviceaccount.com` gebunden,
  in Render hinterlegt und live mit `AI_PROVIDER_SUCCESS` validiert. Gemini erhielt dabei
  weiterhin ausschließlich aggregierte Kennzahlen und keine Rohzeilen.
- Vollständige QA: 94/94 Core, 7/7 Production, 16/16 Security, 5/5 Golden-Datasets,
  Syntaxcheck und kompletter Streamlit-Runtime-Flow bestanden.

## MUST FIX

1. **Alten Gemini-Key widerrufen.** Der neue eingeschränkte Produktionsschlüssel ist live.
   Der zuvor im Chat offengelegte Schlüssel gehört jedoch zum nicht zugänglichen Google-
   Projekt `1067062801521`. Dem aktuellen Konto fehlt dort bereits
   `resourcemanager.projects.get`; der alte Schlüssel konnte deshalb nicht widerrufen
   werden und bleibt bis zur Löschung durch ein berechtigtes Konto ein Sicherheitsrest.
2. **OIDC-Abnahme vervollständigen.** Ein nicht erlaubtes Konto, Logout, Session-Cleanup,
   Browser-Zurück und die finalen Cookie-Attribute müssen live geprüft werden.
3. **Echte Zwei-Nutzer-Isolation auf Production.** Zwei getrennte erlaubte Google-Konten
   müssen gleichzeitig ALPHA/BETA durch Upload, Analyse, AI, PDF und Logout führen.

## BEFORE LAUNCH

- 100.000 Zeilen live auf Render mit Upload-, Analyse-, AI- und PDF-Dauer prüfen.
  Der deterministische 100k-Core-Test besteht; ein belastbarer Live-Lauf ist offen.
- Kontrollierten UI-Fehler auslösen und Korrelations-ID im Render-Log wiederfinden.
- Dauerhaften Feedbackkanal benennen; die App-Seite ist derzeit nur informativ.
- Betreiberangaben und rechtlich geprüfte Texte für Impressum, Datenschutz und
  Nutzungsbedingungen einsetzen. `SECURITY_NOTES.md` enthält die technische Grundlage.
- Render-Wakeup nach echter Inaktivität messen. Kein kostenpflichtiges Upgrade ohne
  separate Entscheidung.
- Externen Uptime-Monitor und Alarmempfänger konfigurieren.
- Zusätzliche HTTP-Sicherheitsheader und Identity-Cookie-Attribute an der finalen Domain
  im Browser prüfen.

## LATER

- Bezahlten Compute-Plan erst anhand echter Beta-Messwerte bewerten.
- Zentral verteiltes Rate Limiting und persistente Mandantenarchitektur erst vor
  horizontaler Skalierung planen.
- Externen Security-Test vor öffentlichem oder bezahltem Launch durchführen.

## Go/No-Go-Matrix

| Kriterium | Status | Evidenz / Blocker |
|---|---|---|
| Gemini-Key rotiert | ROT | neuer eingeschränkter Render-Key live und geprüft; offengelegter Alt-Key im unzugänglichen Projekt `1067062801521` noch nicht widerrufen |
| OIDC End-to-End | GELB | erlaubter Nutzer und Redirect erfolgreich; Deny/Logout/Cookies offen |
| Allowlist | GRUEN | freigegebenes Konto erreicht Dashboard; Fail-closed-Tests bestehen |
| Logout / Session Cleanup | GELB | automatisiert bestanden, live noch offen |
| Zwei Nutzer Production | ROT | zweites freigegebenes Testkonto fehlt |
| 100k Production | GELB | 100k Core-QA bestanden, aktueller Live-Lauf offen |
| Monitoring | GELB | Health und PII-arme Logs geprüft, kontrollierter Fehler/Alarm offen |
| Feedbackkanal | ROT | Fragen und Tracker vorhanden, kein dauerhafter Eingang konfiguriert |
| Rechtstexte | ROT | technische Hinweise vorhanden, Betreiber-/Rechtsprüfung fehlt |
| Tester vorbereitet | GELB | Vorlage und Fragen vorhanden, echte 3 bis 5 Tester noch einzutragen |
