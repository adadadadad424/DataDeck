# DataDeck

DataDeck ist ein Streamlit-MVP für die kontrollierte Analyse von CSV- und
XLSX-Finanzdaten. Kennzahlen werden deterministisch in Python berechnet. Gemini
interpretiert ausschließlich aggregierte Ergebnisse und erhält keine Rohzeilen.

## Lokal starten

```bash
python -m venv work/.venv
work/.venv/bin/pip install -r requirements.txt
cp .env.example .env
work/.venv/bin/streamlit run main.py
```

Die lokale Entwicklung läuft standardmäßig ohne Login. Ein Gemini-Schlüssel ist
optional; ohne ihn steht eine lokale, deterministische KPI-Zusammenfassung bereit.

## Qualität prüfen

```bash
work/.venv/bin/python qa_all.py
work/.venv/bin/pip check
```

`qa_all.py` umfasst Kernlogik, UI-Formatierung, Runtime-Flows, Security,
Produktionskonfiguration, 50+ Golden Datasets, Importadapter,
Mandanten-Isolation und das deaktivierte Stripe-Testbilling.

## Architektur

- `main.py`: UI, Session State und Ablaufsteuerung
- `core/data_processing.py`: Upload-Prüfung, Import, Mapping, Bereinigung
- `core/import_adapters.py`: formatneutrale Importgrenze für CSV/XLSX
- `core/analysis.py`: zentrale KPI- und Zeitvergleichslogik
- `core/formatting.py`: deutsche Zahlen-, Kurz- und Datumsformatierung
- `core/security.py`: PII-Erkennung, Maskierung und Prompt-Bereinigung
- `core/ai_insights.py`: Gemini-Aufruf und lokaler Fallback
- `core/report_builder.py`: PDF aus den zentral berechneten Kennzahlen
- `core/runtime_security.py`: Produktionsschutz, Allowlist, Session-Cleanup
- `core/theme.py`: Light-/Dark-Designsystem
- `billing/`: persistenter Billing-Status, Stripe-Checkout, Portal und Entitlements
- `billing_service.py`: unabhängiger, signaturgeprüfter Stripe-Webhook-Endpunkt
- `consulting/`: owner-sichere Mandanten, Analysehistorie, Vergleiche und Report-Versionen

## Mandantenhistorie

Die Schnellanalyse bleibt ohne Datenbank verfügbar. Mit einer PostgreSQL-
`DATABASE_URL` kann ein Berater Analysen einem Mandanten zuordnen. Persistiert
werden ausschließlich Mapping, Zeitraum, Dataset-Fingerprint, aggregierte
Kennzahlen, freigegebene Insight-Texte und Report-Metadaten. Upload-Dateien und
Rohzeilen werden nicht gespeichert.

Vor Aktivierung einmal die versionierten Migrationen ausführen:

```bash
python -m billing.migrate
```

Details zu Datenschutz, Isolation und Betrieb stehen in
`CONSULTING_HISTORY.md`.

Produktionsbetrieb, Sicherheitsgrenzen und der Beta-Ablauf sind in
`DEPLOYMENT.md`, `PRODUCTION_RUNBOOK.md`, `SECURITY_NOTES.md` und
`BETA_LAUNCH_CHECKLIST.md` beschrieben. Die noch deaktivierte Stripe-Testintegration
und ihre manuellen Einrichtungsschritte stehen in `BILLING.md`.
