# DataDeck Incident Response

Diese Kurzfassung gilt für die geschlossene Beta. Verantwortliche Person und
Kontaktweg müssen vor Einladung des ersten Testers eingetragen werden.

## Sofortmaßnahmen

1. Neue Zugriffe stoppen: Render Maintenance Mode aktivieren oder Service pausieren.
2. Zeitpunkt, Version, betroffene Korrelations-IDs und beobachtetes Verhalten notieren.
3. Keine Kundendateien über Chat, E-Mail oder Tickets anfordern.
4. Verdächtige Secrets im jeweiligen Provider rotieren.
5. Bei fehlerhaftem Release auf den letzten grünen Render-Deploy zurückrollen.
6. Dienst erst nach Ursachenanalyse und vollständiger Release-QA wieder öffnen.

## App nicht erreichbar

- Render Health, Deploy-Status, Restart-Zähler, RAM und CPU prüfen.
- Letzte Logs nur anhand Event und Korrelations-ID untersuchen.
- Bei OOM Upload-/Parallelität stoppen und auf letzte stabile Version zurückrollen.
- Keine Ressourcen hochskalieren, bevor die Ursache verstanden ist.

## Verdacht auf Datenvermischung oder PII-Leak

- Beta sofort sperren und keine weiteren Uploads zulassen.
- Betroffene Sessions durch Neustart der einzelnen Instanz beenden.
- Logs auf Dataset-Hash-Präfixe und Korrelations-IDs prüfen, ohne Rohdaten zu kopieren.
- Gemini- und OIDC-Secrets vorsorglich rotieren, falls deren Offenlegung möglich ist.
- Umfang, betroffene Personen und Meldepflicht mit Datenschutzberatung bewerten.

## Secret kompromittiert

- Altes Secret beim Anbieter widerrufen, nicht nur aus Render löschen.
- Neues Secret in Render setzen und Service neu starten.
- Funktion mit synthetischen Daten prüfen.
- Alte Werte niemals in Incident-Dokumente oder Tickets kopieren.

## Gemini-Ausfall

- Dashboard und lokale KPI-Zusammenfassung bleiben nutzbar.
- `AI_PROVIDER_ERROR`-Rate und Google-Status prüfen.
- Kein mehrfaches manuelles Wiederholen erzwingen; Quota und Kosten kontrollieren.

## Auth-Ausfall

- OIDC Redirect URI, Client-Status und Google-Providerstatus prüfen.
- Auth niemals umgehen oder `AUTH_REQUIRED` in Production deaktivieren.
- Falls keine sichere Anmeldung möglich ist, Beta geschlossen lassen.

## Fehlerhaftes Deployment und Rollback

- Render: Service > Deploys > letzten erfolgreichen Deploy > `Rollback`.
- Healthcheck abwarten, dann Login, Demo, Upload und PDF mit synthetischen Daten testen.
- Auto-Deploy stoppen, falls derselbe fehlerhafte Commit sonst erneut ausgerollt würde.

## Abschluss

Ursache, Zeitlinie, Auswirkungen, Maßnahmen und Prävention ohne Kundendaten dokumentieren.
Bei notwendiger Nutzerinformation nur bestätigte Tatsachen nennen.

