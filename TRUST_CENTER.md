# DataDeck Trust Center

DataDeck befindet sich in einer technischen Beta. Diese Übersicht beschreibt den implementierten Stand und ist keine Zertifizierung oder Rechtsberatung.

## Datenfluss

Uploads werden validiert und in der laufenden Sitzung verarbeitet. Die Finanz-KPIs werden deterministisch in Python berechnet. Gemini erhält nur aggregierte Kennzahlen und begrenzte Kategorienamen, niemals vollständige Rohzeilen. In der PostgreSQL-Historie werden ausschließlich Aggregate, Zuordnungen und Report-Metadaten gespeichert.

## Zugriff und Isolation

OIDC schützt den Zugang. Workspace-Rollen (`OWNER`, `PARTNER`, `CONSULTANT`, `VIEWER`) werden serverseitig pro Ressource geprüft. UI-Sichtbarkeit ist keine Sicherheitsgrenze. Historische Analysen, Reportversionen und Audit-Ereignisse sind unveränderlich.

## Dienstleister

- Render: Anwendung und PostgreSQL in der konfigurierten Region.
- Google: Anmeldung sowie optionale Gemini-Interpretation aggregierter Daten.
- Stripe: optionales Billing, nur wenn vom Betreiber aktiviert.

## Ehrliche Grenzen

Die automatische Erkennung personenbezogener Muster ist keine vollständige DSGVO-Anonymisierung. DataDeck besitzt derzeit keine ISO-27001-, SOC-2- oder vergleichbare Zertifizierung. Nutzer bleiben für Datenminimierung, Rechtsgrundlage und fachliche Prüfung verantwortlich.
