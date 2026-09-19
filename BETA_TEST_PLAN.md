# DataDeck Invite-only Beta Test Plan

## Umfang

Start mit 3 bis 5 Beratern, jeweils nur mit freigegebenem Konto. Die Beta dauert zwei
Wochen und verarbeitet zunächst bevorzugt synthetische oder vorher anonymisierte Dateien.

## Testablauf pro Teilnehmer

1. Login, Logout und erneuter Login; prüfen, dass keine alten Daten erscheinen.
2. Demo-Daten in Light und Dark Mode testen.
3. Eine typische CSV und eine typische XLSX hochladen.
4. Spaltenzuordnung und Datenqualitätswarnungen beurteilen.
5. Filter, Umsatz/Gewinn/Marge und Segment-Rankings mit der Quelldatei vergleichen.
6. Revenue-only-Datei testen und bestätigen, dass kein Gewinn erfunden wird.
7. AI Insights auf Nachvollziehbarkeit und unerlaubte Detaildaten prüfen.
8. PDF erzeugen und Werte mit Dashboard vergleichen.
9. Fehlerfälle testen: falscher Dateityp, zu große Datei, unpassende Spalten.
10. Verständlichkeit, Zeitersparnis und fehlende Kernfunktion bewerten.

Danach ohne Produktänderung die zehn Fragen aus `BETA_FEEDBACK_QUESTIONS.md`
beantworten lassen. Erst Muster aus mehreren Tests auswerten; einzelne Wünsche lösen
keinen Feature-Sprint aus.

## Hosting-Matrix

- 1, 2, 5 und 10 gleichzeitige Browser-Sessions
- 10k, 40k und 100k Zeilen einzeln
- zwei gleichzeitige 100k-Dateien
- fünf Nutzer mit gemischten Dateigrößen
- ALPHA/BETA mit identischem Dateinamen in zwei Browserprofilen

Pro Lauf werden Zeit, RAM, CPU, Fehler, Restarts, AI- und PDF-Dauer notiert. Bei OOM,
Session-Abbruch oder dauerhaft mehr als 85 Prozent RAM wird abgebrochen und analysiert.

## Abnahmekriterien

- Kein Datenübertritt zwischen Nutzern oder Tabs.
- Keine Rohdaten oder personenbezogenen Werte in KI-Kontext, PDF-Fehlern oder Logs.
- Keine Abweichung zwischen Dashboard und PDF bei denselben Filtern.
- Keine falsche Gewinn-/Margendarstellung ohne Kostenbasis.
- Keine Summierung gemischter Währungen.
- Kein ungeklärter Crash; jeder unerwartete Fehler liefert eine Korrelations-ID.
- Kritische Sicherheitsfehler stoppen die Beta sofort.

## Feedback erfassen

Pro Testfall: Dateityp, ungefähre Zeilen-/Spaltenzahl, erwartetes Ergebnis, tatsächliches
Ergebnis, Screenshot ohne Kundendaten, Korrelations-ID und Schweregrad. Keine Originaldateien
über unsichere Supportkanäle versenden.

Testerstatus wird ausschließlich in `BETA_TESTERS.md` gepflegt. Dort keine Datensätze,
Dateinamen, Inhalte oder sonstigen Kundendaten eintragen.

Schweregrade: `BLOCKER` für Isolation/Auth/Secrets/falsche Finanzwerte, `HIGH` für nicht
abschließbare Kernabläufe, `MEDIUM` für verständliche Workarounds und `LOW` für Polish.
