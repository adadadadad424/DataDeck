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
work/.venv/bin/python -m py_compile main.py core/*.py
work/.venv/bin/python qa_test_final.py
work/.venv/bin/python qa_runtime.py
work/.venv/bin/python qa_beta_security.py
work/.venv/bin/python qa_production.py
work/.venv/bin/python qa_golden_datasets.py
work/.venv/bin/pip check
```

## Architektur

- `main.py`: UI, Session State und Ablaufsteuerung
- `core/data_processing.py`: Upload-Prüfung, Import, Mapping, Bereinigung
- `core/analysis.py`: zentrale KPI- und Zeitvergleichslogik
- `core/security.py`: PII-Erkennung, Maskierung und Prompt-Bereinigung
- `core/ai_insights.py`: Gemini-Aufruf und lokaler Fallback
- `core/report_builder.py`: PDF aus den zentral berechneten Kennzahlen
- `core/runtime_security.py`: Produktionsschutz, Allowlist, Session-Cleanup
- `core/theme.py`: Light-/Dark-Designsystem

Produktionsbetrieb, Sicherheitsgrenzen und der Beta-Ablauf sind in
`DEPLOYMENT.md`, `PRODUCTION_RUNBOOK.md`, `SECURITY_NOTES.md` und
`BETA_LAUNCH_CHECKLIST.md` beschrieben.
