"""Integration checks against installed Streamlit, Plotly and WeasyPrint."""

import io
import os
import re
from pathlib import Path

import openpyxl
from streamlit.testing.v1 import AppTest


def assert_ok(app):
    assert not app.exception, [item.message for item in app.exception]


def kpis(app):
    cards = [item.value for item in app.markdown if item.value.startswith('<div class="dd-card" style="margin-bottom:0;">')]
    return dict(
        re.findall(
            r'class="dd-kpi-label">([^<]+)</div><div class="dd-kpi-value"[^>]*>([^<]+)',
            "".join(cards),
        )
    )


def main():
    env_file = Path(".env")
    env_backup = Path("work/.env.qa_runtime_backup")
    if env_file.exists():
        env_backup.parent.mkdir(exist_ok=True)
        env_file.replace(env_backup)
    os.environ["GEMINI_API_KEY"] = ""
    try:
        app = AppTest.from_file("main.py", default_timeout=30).run()
        assert_ok(app)
        app.button(key="demo_btn").click().run()
        assert_ok(app)
        assert kpis(app)["Umsatz"] == "9.200 €"

        app.button(key="generate_ai_btn").click().run()
        assert_ok(app)
        assert app.session_state["ai_insights_source"] == "local"
        assert app.session_state["ai_insights"]["action_plan"]

        app.toggle(key="theme_toggle").set_value(True).run()
        assert_ok(app)
        assert app.session_state["theme"] == "dark"
        app.toggle(key="theme_toggle").set_value(False).run()
        assert_ok(app)
        assert app.session_state["theme"] == "light"

        app.toggle(key="premium_toggle").set_value(True).run()
        assert_ok(app)
        app.button(key="generate_pdf_btn").click().run()
        assert_ok(app)
        assert app.session_state["pdf_bytes"].startswith(b"%PDF-")

        csv = b"Kategorie,Umsatz,Gewinn\nPlus,1000,300\nMinus,500,-400\n"
        app.file_uploader(key="file_uploader").set_value(("sample.csv", csv, "text/csv")).run()
        assert_ok(app)
        assert kpis(app) == {"Umsatz": "1.500 €", "Gewinn": "-100 €", "Marge": "-6,7 %", "Datensätze": "2"}
        assert app.session_state["pdf_bytes"] is None
        assert any("lokale KPI-Analyse" in item.value for item in app.info)

        app.button(key="generate_pdf_btn").click().run()
        assert_ok(app)
        assert app.session_state["pdf_bytes"].startswith(b"%PDF-")
        app.text_input(key="category_filter").set_value("Plus")
        app.button(key="FormSubmitter:filter_form-Filter anwenden").click().run()
        assert_ok(app)
        assert kpis(app)["Gewinn"] == "300 €"
        assert app.session_state["pdf_bytes"] is None

        app.text_input(key="category_filter").set_value("[")
        app.button(key="FormSubmitter:filter_form-Filter anwenden").click().run()
        assert_ok(app)
        assert any("Keine Daten" in item.value for item in app.warning)

        updated_csv = csv.replace(b"1000", b"2000")
        assert len(updated_csv) == len(csv)
        app.file_uploader(key="file_uploader").set_value(("sample.csv", updated_csv, "text/csv")).run()
        assert_ok(app)
        assert kpis(app)["Umsatz"] == "2.500 €"
        assert app.session_state["category_filter"] == ""

        revenue_only_csv = b"Segment,Revenue\nEnterprise,2000\nStarter,500\n"
        app.file_uploader(key="file_uploader").set_value(
            ("revenue_only.csv", revenue_only_csv, "text/csv")
        ).run()
        assert_ok(app)
        assert kpis(app)["Gewinn"] == "—"
        assert kpis(app)["Marge"] == "—"
        assert app.number_input(key="ziel_marge_input").disabled is True
        assert any("Kosteninformationen fehlen" in item.value for item in app.markdown)
        app.button(key="generate_pdf_btn").click().run()
        assert_ok(app)
        assert app.session_state["pdf_bytes"].startswith(b"%PDF-")

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Kategorie", "Umsatz", "Gewinn"])
        sheet.append(["Excel A", 800, 160])
        sheet.append(["Excel B", 200, -50])
        buffer = io.BytesIO()
        workbook.save(buffer)
        app.file_uploader(key="file_uploader").set_value(("sample.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
        assert_ok(app)
        assert kpis(app)["Umsatz"] == "1.000 €"

        app.session_state["ai_insights"] = {
            "zusammenfassung": "OLD AI",
            "ziel_analyse": "OLD EVALUATION",
            "action_plan": ["OLD ACTION"],
        }
        app.session_state["ai_insights_key"] = "old-context"
        app.button(key="generate_pdf_btn").click().run()
        assert_ok(app)
        assert app.session_state["pdf_bytes"].startswith(b"%PDF-")
        assert any("ohne die veraltete KI-Analyse" in item.value for item in app.caption)

        app.file_uploader(key="file_uploader").clear().run()
        assert_ok(app)
        assert app.session_state["raw_df"] is None
        print("Runtime QA: Demo, CSV, Revenue-only, XLSX, Filter, Theme, no-key AI, stale AI and real PDF PASS")
    finally:
        if env_backup.exists():
            env_backup.replace(env_file)


if __name__ == "__main__":
    main()
