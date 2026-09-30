# Connector Feasibility (Research only)

Stand: 21.09.2026. In diesem Sprint wurden keine Live-Integrationen gebaut.

## Gemeinsame Adaptergrenze

Jede Datenquelle muss `authenticate`, `fetch_data`, `normalize` und `validate` implementieren. Normalisierte Daten laufen anschließend durch dieselbe sichere DataDeck-Pipeline wie CSV/XLSX. Credentials gehören in einen verwalteten Secret Store, niemals in Logs, Audit-Metadaten oder Analysehistorien.

## DATEV

Das DATEV Developer Portal bietet Online- und Desktop-Schnittstellen sowie Use-Case-spezifische API-Produkte. Einzelne Online-APIs verwenden OAuth 2.0 mit OpenID Connect. Portalregistrierung, Produktfreigabe und möglicherweise kostenpflichtige Verträge müssen je konkretem Rechnungswesen-Use-Case geklärt werden. Ein generischer „DATEV Connector“ ohne festgelegtes API-Produkt wäre deshalb fachlich unseriös.

Empfehlung: Erst mit drei Beta-Kanzleien den konkreten Export-/API-Use-Case bestimmen, danach passendes DATEV-Produkt und Sandbox beantragen. Quellen: [DATEV Developer Portal](https://developer.datev.de/en/products/988700e4-e0c5-40bf-814b-cd7327dad67a), [DATEV Portal-Nutzungsbedingungen](https://developer.datev.de/en/assets/Terms_of_Use_DATEV_Developer_Portal_and_DATEV_Interfaces.pdf).

## sevdesk

sevdesk stellt eine REST API bereit; laut offizieller Hilfe ist sie aktuell an den Tarif Buchhaltung Pro gebunden. Die Authentifizierung muss über den Authorization-Header erfolgen; Token in URL-Parametern wurden aus Sicherheitsgründen entfernt. Für DataDeck wäre zunächst ein lesender Import von Rechnungen, Gutschriften und Belegen mit minimalen Berechtigungen sinnvoll.

Empfehlung: Vor Implementierung Limits, Pagination, Änderungszeitstempel und Testkonto verifizieren; Token verschlüsselt und workspace-isoliert speichern. Quellen: [sevdesk API](https://hilfe.sevdesk.de/de/articles/9374668-sevdesk-api), [Änderung der Authentifizierung](https://tech.sevdesk.com/api_news/posts/2025_02_06-authentication-method-removed/).

## Xero

Die Xero Accounting API unterstützt unter anderem Invoices, Credit Notes, Accounts, Bank Transactions und Reports. Für eine Multi-Organisation-SaaS-Anbindung ist der OAuth-2-Authorization-Code-Flow vorgesehen; API-Aufrufe benötigen den autorisierten Tenant-Kontext. Custom Connections sind auf eine Organisation begrenzt, regional eingeschränkt und können kostenpflichtig sein.

Empfehlung: Authorization Code Flow mit minimalen Read-Scopes, verschlüsselter Refresh-Token-Ablage, expliziter Tenant-Bindung und Xero Demo Company. Quellen: [Accounting API Overview](https://developer.xero.com/documentation/api/accounting/overview), [OAuth 2.0 Overview](https://developer.xero.com/documentation/guides/oauth2/overview/), [Authorization Code Flow](https://developer.xero.com/documentation/guides/oauth2/auth-flow).

## Priorisierung

1. CSV/XLSX bleibt Launch-Pfad und Referenzadapter.
2. sevdesk eignet sich als erster Discovery-Kandidat für deutsche Micro-SaaS-/Beratungskunden.
3. Xero eignet sich für internationale Validierung, erfordert aber konsequente Tenant- und Token-Isolation.
4. DATEV folgt erst nach klarer Auswahl des konkreten API-Produkts und Partnerprozesses.

## Offene technische Prüfung vor einer Umsetzung

| Quelle | Authentifizierung | Testumgebung | Limits und Kosten | Benötigte Felder | Freigabe und Recht |
| --- | --- | --- | --- | --- | --- |
| DATEV | Produktabhängig, für Online-APIs teils OAuth/OIDC | Für das konkrete API-Produkt zu prüfen | Produkt- und Vertragsbedingungen zu prüfen | Buchungsdatum, Betrag, Währung, Kostenstelle oder Kategorie; Verfügbarkeit je Produkt prüfen | Portalzugang, Produktfreigabe, Mandantenberechtigung und AV-Verträge klären |
| sevdesk | API-Token im Authorization-Header | Testkonto und Sandbox-Verfügbarkeit zu prüfen | Tarifbindung bekannt; API-Limits und Zusatzkosten vorab prüfen | Rechnungsdatum, Nettobetrag, Kosten, Gutschriften, Währung und Kunde nur soweit für den Use-Case nötig | Lesende Berechtigung, Token-Aufbewahrung und Mandantenzustimmung klären |
| Xero | OAuth 2.0 mit Tenant-Bindung | Demo Company laut Anbieter; konkreten Testablauf prüfen | Rate Limits und mögliche Kosten je Verbindung prüfen | Invoices, Credit Notes, Accounts, Reports; minimales Feldset festlegen | Scopes, Tenant-Zuordnung, Token-Rotation und Datenübertragung prüfen |

Ein Connector wird erst nach einem dokumentierten Feldmapping, einem Test mit synthetischen Daten und einer Kostenprüfung als Produktfunktion geplant. Ungeprüfte Punkte sind bewusst als offen markiert.
