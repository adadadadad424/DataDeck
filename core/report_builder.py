"""
PDF-Report-Erstellung für DataDeck (Jinja2 + WeasyPrint).

WICHTIGSTES PRINZIP (unverändert): Diese Datei erkennt KEINE Spalten und
berechnet KEINE Kennzahlen selbst - sie bekommt ausschließlich das fertige
kpis-Dict aus core/analysis.calculate_kpis() sowie das ai_insights-Dict
übergeben und rendert nur. Dashboard und PDF können dadurch strukturell
nie unterschiedliche Zahlen zeigen.

SICHERHEITS-ARCHITEKTUR (unverändert):
1. Auto-Escaping (Jinja2 autoescape=True) - jedes {{ feld }} wird
   automatisch HTML-escaped, unabhängig von der Quelle.
2. url_fetcher-Blockade gegen SSRF - das Template braucht keine externen
   Ressourcen, jeder Nachladeversuch wird blockiert.

DESIGN (aktualisiert auf DataDeck-Branding): helles, klares B2B-Layout
mit dem DataDeck-Indigo (#4F46E5) als Akzentfarbe - ersetzt das frühere
dunkle Nera-Schwarz/Ducati-Rot-Theme aus Enterprise v3.2, das zur alten
Marke gehörte. Ein heruntergeladener Geschäftsbericht folgt bewusst NICHT
dem Light/Dark-Toggle der Streamlit-Oberfläche, sondern hat eine
konstante, druckfreundliche Markendarstellung (wie bei den meisten
SaaS-Produkten).
"""

import datetime
import os
import sys
from typing import Optional

from jinja2 import Environment, select_autoescape

from .formatting import format_de_number
from .runtime_security import APP_VERSION

BRAND = "#4F46E5"


def _blocking_url_fetcher(url, *args, **kwargs):
    """Blockiert jeglichen Nachladeversuch externer Ressourcen durch
    WeasyPrint. Das Template benötigt keine externen Ressourcen."""
    raise ValueError(f"Externe Ressource im PDF-Report blockiert: {url}")


TEMPLATE_HTML = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>DataDeck Report</title>
    <style>
        @page {
            size: A4;
            margin: 20mm;
            @bottom-right {
                content: "Seite " counter(page) " / " counter(pages);
                font-size: 8pt; color: #9A9AAC; font-family: Arial, sans-serif;
            }
        }
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            color: #12121A;
            background-color: #FFFFFF;
            line-height: 1.55;
            font-size: 12px;
            margin: 0;
        }
        .cover {
            page-break-after: always;
            height: 245mm;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .cover-eyebrow { color: __BRAND__; font-size: 10pt; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
        .cover-logo { font-size: 34pt; font-weight: 800; color: #12121A; margin-top: 6px; letter-spacing: -0.01em; }
        .cover-logo span { color: __BRAND__; }
        .cover-subtitle { font-size: 12pt; color: #6B6B7A; margin-top: 12px; max-width: 120mm; }
        .cover-meta {
            margin-top: 60px; font-size: 9.5pt; color: #6B6B7A;
            border-top: 1px solid #E6E6EF; padding-top: 16px; max-width: 120mm;
        }
        .header { border-bottom: 2px solid __BRAND__; padding-bottom: 10px; margin-bottom: 22px; }
        .logo { font-size: 16pt; font-weight: 800; color: #12121A; }
        .logo span { color: __BRAND__; }
        .subtitle { font-size: 9pt; color: #6B6B7A; margin-top: 3px; }
        h2 {
            font-size: 13pt; font-weight: 700; color: #12121A;
            margin-top: 26px; margin-bottom: 12px;
            padding-bottom: 6px; border-bottom: 1px solid #E6E6EF;
        }
        .kpi-container { width: 100%; margin-bottom: 14px; display: table; table-layout: fixed; border-spacing: 0; }
        .kpi-box {
            display: table-cell; width: 25%; padding: 12px 8px; text-align: left;
            background: #F7F7FB; border: 1px solid #E6E6EF; border-radius: 6px;
            box-sizing: border-box;
        }
        .kpi-title { font-size: 8.5pt; color: #6B6B7A; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
        .kpi-value { font-size: 13pt; font-weight: 800; color: #12121A; margin-top: 4px; white-space: nowrap; letter-spacing: -0.01em; }
        .kpi-reason { font-size: 7.5pt; color: #6B6B7A; margin-top: 3px; min-height: 18px; line-height: 1.25; }
        .report-note {
            background: #FFF8E6; border: 1px solid #F1D48A; color: #5A4200;
            border-radius: 6px; padding: 9px 11px; margin: 10px 0 16px 0;
            font-size: 9.5pt;
        }
        table { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 10.5pt; }
        th, td { border-bottom: 1px solid #E6E6EF; padding: 8px 10px; text-align: left; }
        th { color: #6B6B7A; font-weight: 600; font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.03em; }
        ul { margin-top: 6px; padding-left: 18px; }
        li { margin-bottom: 6px; }
        .insight-box {
            background: #F7F7FB; padding: 13px 15px; border-left: 3px solid __BRAND__;
            margin-bottom: 10px; border-radius: 0 6px 6px 0; font-size: 11pt;
        }
        .insight-tag { font-size: 8pt; font-weight: 700; letter-spacing: 0.05em; color: #6B6B7A; text-transform: uppercase; display: block; margin-bottom: 3px; }
        .empty-note { color: #9A9AAC; font-style: italic; }
    </style>
</head>
<body>

    <div class="cover">
        <div class="cover-eyebrow">Data Intelligence</div>
        <div class="cover-logo">Data<span>Deck</span></div>
        <div class="cover-subtitle">Unternehmensanalyse &amp; Strategiebericht</div>
        <div class="cover-meta">
            Erstellt am {{ date }}<br>
            Version: {{ app_version }}<br>
            {% if niche %}Branche: {{ niche }}<br>{% endif %}
            Datenbasis: {{ kpis.anzahl_zeilen | de_number(0) if kpis.anzahl_zeilen is defined else "n/v" }} Positionen
            in {{ kpis.anzahl_kategorien if kpis.anzahl_kategorien is defined else "n/v" }} Kategorien
        </div>
    </div>

    <div class="header">
        <div class="logo">Data<span>Deck</span></div>
        <div class="subtitle">
            Unternehmensanalyse &amp; Strategiebericht &bull; {{ date }}
            {% if niche %}&bull; {{ niche }}{% endif %}
        </div>
    </div>

    <h2>Kernkennzahlen</h2>
    <div class="kpi-container">
        <div class="kpi-box"><div class="kpi-title">Umsatz</div><div class="kpi-value">{% if aggregation_limited %}&mdash;{% else %}{{ kpis.gesamt_umsatz | de_number }}&nbsp;&euro;{% endif %}</div><div class="kpi-reason">{% if aggregation_limited %}Mehrere Währungen{% else %}Gemessene Umsatzbasis{% endif %}</div></div>
        <div class="kpi-box"><div class="kpi-title">Gewinn</div><div class="kpi-value">{% if revenue_only or aggregation_limited %}&mdash;{% else %}{{ kpis.gesamt_gewinn | de_number }}&nbsp;&euro;{% endif %}</div><div class="kpi-reason">{% if aggregation_limited %}Mehrere Währungen{% elif revenue_only %}Nicht berechenbar: Kostenbasis fehlt{% elif kpis.metrics.gewinn.status == 'ESTIMATED' %}Aus Umsatz minus Kosten{% else %}Aus Gewinnspalte{% endif %}</div></div>
        <div class="kpi-box"><div class="kpi-title">Marge</div><div class="kpi-value">{% if revenue_only or aggregation_limited %}&mdash;{% else %}{{ kpis.aktuelle_marge | de_number }}{% if kpis.aktuelle_marge == kpis.aktuelle_marge %}&nbsp;%{% endif %}{% endif %}</div><div class="kpi-reason">{% if aggregation_limited %}Mehrere Währungen{% elif revenue_only %}Nicht verfügbar{% else %}Gewinn / Umsatz{% endif %}</div></div>
        <div class="kpi-box"><div class="kpi-title">Datensätze</div><div class="kpi-value">{{ kpis.anzahl_zeilen | de_number(0) if kpis.anzahl_zeilen is defined else "n/v" }}</div><div class="kpi-reason">Bereinigte Datenzeilen</div></div>
    </div>
    {% if aggregation_limited %}
    <div class="report-note">Mehrere Währungen wurden erkannt. Ohne dokumentierte Wechselkurse enthält dieser Bericht keine Finanzsummen, Rankings oder Zeitvergleiche.</div>
    {% endif %}
    {% if revenue_only %}
    <div class="report-note">
        Die Datei enthält Umsatzdaten, aber keine Gewinn- oder Kostenbasis. Gewinn, Marge,
        Zielmargenvergleich und Profitabilitäts-Rankings sind deshalb nicht berechenbar.
    </div>
    {% endif %}

    {% if insights %}
    <h2>KI-Insights</h2>
    <div class="insight-box"><span class="insight-tag">Kurzfassung</span>{{ insights.zusammenfassung }}</div>
    <div class="insight-box"><span class="insight-tag">Bedeutung</span>{{ insights.ziel_analyse }}</div>
    <strong style="font-size:10.5pt;">Handlungsoptionen</strong>
    <ul>
        {% for plan in insights.action_plan %}
        <li>{{ plan }}</li>
        {% endfor %}
    </ul>
    {% if insights.datengrundlage %}
    <div class="insight-box"><span class="insight-tag">Datengrundlage</span>{{ insights.datengrundlage }}</div>
    {% endif %}
    {% else %}
    <h2>KI-Insights</h2>
    <p class="empty-note">Für diesen Bericht wurde keine KI-Analyse erstellt.</p>
    {% endif %}

    {% if not aggregation_limited %}<h2>{% if revenue_only %}Umsatzstärkste Segmente{% else %}Gewinnstärkste Segmente{% endif %}</h2>
    {% if kpis.top_performer %}
    <table>
        <thead><tr><th>Kategorie</th><th>{% if revenue_only %}Umsatz{% else %}Gewinn{% endif %}</th>{% if not revenue_only %}<th>Marge</th>{% endif %}</tr></thead>
        <tbody>
            {% for row in kpis.top_performer %}
            <tr><td>{{ row.Kategorie_Clean }}</td><td>{{ (row.Umsatz_Clean if revenue_only else row.Gewinn_Clean) | de_number }} &euro;</td>{% if not revenue_only %}<td>{{ row.Marge | de_number }}{% if row.Marge == row.Marge %} %{% endif %}</td>{% endif %}</tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}<p class="empty-note">Keine Kategoriendaten vorhanden.</p>{% endif %}

    <h2>{% if revenue_only %}Umsatzschwächste Segmente{% else %}Gewinnschwächste Segmente{% endif %}</h2>
    {% if kpis.flop_performer %}
    <table>
        <thead><tr><th>Kategorie</th><th>{% if revenue_only %}Umsatz{% else %}Gewinn{% endif %}</th>{% if not revenue_only %}<th>Marge</th>{% endif %}</tr></thead>
        <tbody>
            {% for row in kpis.flop_performer %}
            <tr><td>{{ row.Kategorie_Clean }}</td><td>{{ (row.Umsatz_Clean if revenue_only else row.Gewinn_Clean) | de_number }} &euro;</td>{% if not revenue_only %}<td>{{ row.Marge | de_number }}{% if row.Marge == row.Marge %} %{% endif %}</td>{% endif %}</tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}<p class="empty-note">Keine Kategoriendaten vorhanden.</p>{% endif %}{% endif %}

    {% if kpis.time_analysis and kpis.time_analysis.available %}
    <h2>Zeitraum &amp; Entwicklung</h2>
    <p>Analysierter Zeitraum: {{ kpis.time_analysis.start.strftime('%d.%m.%Y') }} bis {{ kpis.time_analysis.end.strftime('%d.%m.%Y') }}.</p>
    {% if kpis.time_analysis.comparison_available %}
    <p>Umsatzveränderung im vergleichbaren Zeitraum {{ kpis.time_analysis.comparison_label }}:
       <strong>{{ kpis.time_analysis.revenue_change_pct | de_number(1) }} %</strong>.</p>
    {% if kpis.time_analysis.current_is_partial %}<p class="empty-note">Teilmonatsvergleich bis {{ kpis.time_analysis.current_data_through.strftime('%d.%m.%Y') }}; verglichen wurde dasselbe Tagesfenster des Vormonats.</p>{% endif %}
    {% else %}<p class="empty-note">{{ kpis.time_analysis.reason }}</p>{% endif %}
    {% endif %}

    <h2>Datenqualität &amp; Methodik</h2>
    {% if data_quality %}
    <p>Analysequalität: <strong>{{ data_quality.level | replace('eingeschraenkt', 'eingeschränkt') | replace('nicht_ausreichend', 'nicht ausreichend') | capitalize }}</strong>; Vollständigkeit: <strong>{{ (data_quality.completeness * 100) | de_number(0) }} %</strong>.</p>
    <ul>
        <li>{{ data_quality.rows | de_number(0) }} Datensätze und {{ data_quality.columns }} Spalten geprüft.</li>
        <li>{{ data_quality.missing_cells | de_number(0) }} fehlende Zellen, {{ data_quality.invalid_numeric | de_number(0) }} ungültige Finanzwerte, {{ data_quality.duplicate_rows | de_number(0) }} mögliche Duplikate.</li>
        {% for issue in data_quality.issues %}<li><strong>{{ issue.title }}:</strong> {{ issue.detail }}</li>{% endfor %}
    </ul>
    {% endif %}
    {% if column_mapping %}
    <p><strong>Verwendete Spalten:</strong>
       Umsatz: {{ column_mapping.umsatz or '—' }};
       Gewinn: {{ column_mapping.gewinn or '—' }};
       Kosten: {{ column_mapping.kosten or '—' }};
       Datum: {{ column_mapping.datum or '—' }}.</p>
    {% endif %}
    <p class="empty-note">Kennzahlen wurden deterministisch in DataDeck berechnet. Ergebnisse sollten vor geschäftlichen Entscheidungen fachlich geprüft werden. An die KI wurden ausschließlich aggregierte Kennzahlen und Kategorienamen übertragen, keine Rohzeilen.</p>

</body>
</html>
""".replace("__BRAND__", BRAND)

_jinja_env = Environment(
    autoescape=select_autoescape(enabled_extensions=('html', 'xml'), default_for_string=True)
)
_jinja_env.filters['de_number'] = format_de_number
_template = _jinja_env.from_string(TEMPLATE_HTML)


def generate_pdf(
    kpis: dict,
    ai_insights: Optional[dict],
    niche: Optional[str] = None,
    revenue_only: bool = False,
    data_quality: Optional[dict] = None,
    column_mapping: Optional[dict] = None,
) -> bytes:
    """Rendert das HTML-Template (Jinja2 Auto-Escaping) und erzeugt ein PDF
    via WeasyPrint. kpis MUSS das Ergebnis von core.analysis.calculate_kpis
    sein (bereits gefiltert, falls Dashboard-Filter aktiv sind)."""
    if sys.platform == "darwin":
        os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")
    from weasyprint import HTML

    html_content = _template.render(
        date=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        app_version=APP_VERSION,
        kpis=kpis,
        insights=ai_insights if ai_insights else None,
        niche=niche,
        revenue_only=revenue_only,
        data_quality=data_quality,
        column_mapping=column_mapping or kpis.get("column_mapping", {}),
        aggregation_limited=not kpis.get("financial_aggregation_available", True),
    )
    return HTML(string=html_content, url_fetcher=_blocking_url_fetcher).write_pdf()
