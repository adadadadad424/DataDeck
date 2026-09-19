# DataDeck Closed-Beta Readiness

Stand: 19.09.2026

## Ergebnis

**NO-GO für externe Tester**, bis die drei Sicherheitsblocker unter `MUST FIX`
geschlossen sind. Die Kernanwendung selbst ist stabil und lokal vollständig grün.

## Verifizierte Evidenz

- Render-Deployment `4992d17` ist live auf dem kostenlosen Frankfurt-Service.
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
- Vollständige QA: 93/93 Core, 7/7 Production, 16/16 Security, 5/5 Golden-Datasets,
  Syntaxcheck und kompletter Streamlit-Runtime-Flow bestanden.

## MUST FIX

1. **Gemini-Key rotieren.** Die Gemini API ist im Projekt `datadeck-beta` aktiviert,
   aber Google verweigert dem aktuellen Konto sowohl AI-Studio-Schlüsselerstellung als
   auch das erforderliche Dienstkonto. Der bisherige Render-Key ist deshalb noch aktiv
   und darf nicht für externe Tests weiterverwendet werden.
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
| Gemini-Key rotiert | ROT | Google-Konto blockiert neue Schlüsselerstellung; alter Render-Key noch aktiv |
| OIDC End-to-End | GELB | erlaubter Nutzer und Redirect erfolgreich; Deny/Logout/Cookies offen |
| Allowlist | GRUEN | freigegebenes Konto erreicht Dashboard; Fail-closed-Tests bestehen |
| Logout / Session Cleanup | GELB | automatisiert bestanden, live noch offen |
| Zwei Nutzer Production | ROT | zweites freigegebenes Testkonto fehlt |
| 100k Production | GELB | 100k Core-QA bestanden, aktueller Live-Lauf offen |
| Monitoring | GELB | Health und PII-arme Logs geprüft, kontrollierter Fehler/Alarm offen |
| Feedbackkanal | ROT | Fragen und Tracker vorhanden, kein dauerhafter Eingang konfiguriert |
| Rechtstexte | ROT | technische Hinweise vorhanden, Betreiber-/Rechtsprüfung fehlt |
| Tester vorbereitet | GELB | Vorlage und Fragen vorhanden, echte 3 bis 5 Tester noch einzutragen |
