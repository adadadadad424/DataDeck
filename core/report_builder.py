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
import base64
import binascii
import os
import sys
from typing import Optional

from jinja2 import Environment, select_autoescape

from .formatting import format_de_number
from .report_config import normalize_report_settings, validated_logo_data_uri
from .report_language import (
    format_report_date,
    format_report_money,
    format_report_number,
    format_report_percent,
    labels_for,
    normalize_report_language,
)
from .runtime_security import APP_VERSION



def _blocking_url_fetcher(url, *args, **kwargs):
    """Blockiert jeglichen Nachladeversuch externer Ressourcen durch
    WeasyPrint. Das Template benötigt keine externen Ressourcen."""
    if isinstance(url, str) and url.startswith("data:image/"):
        try:
            header, encoded = url.split(",", 1)
        except ValueError as error:
            raise ValueError("Ungültiges eingebettetes Bild im PDF-Report") from error
        normalized_header = header.lower()
        allowed_headers = {
            "data:image/png;base64": "image/png",
            "data:image/jpeg;base64": "image/jpeg",
        }
        mime_type = allowed_headers.get(normalized_header)
        if not mime_type:
            raise ValueError("Nur eingebettete PNG- oder JPEG-Bilder sind im PDF erlaubt")
        if len(encoded) > 1_500_000:
            raise ValueError("Eingebettetes Bild im PDF-Report ist zu groß")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Eingebettetes Bild im PDF-Report ist ungültig") from error
        if len(image_bytes) > 1_000_000:
            raise ValueError("Eingebettetes Bild im PDF-Report ist zu groß")
        if sys.platform == "darwin":
            os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")
        from weasyprint.urls import URLFetcherResponse

        return URLFetcherResponse(
            url,
            image_bytes,
            headers={"Content-Type": mime_type},
            status=200,
        )
    raise ValueError(f"Externe Ressource im PDF-Report blockiert: {url}")


TEMPLATE_HTML = """
<!DOCTYPE html>
<html lang="{{ labels.html_lang }}">
<head>
    <meta charset="UTF-8">
    <title>DataDeck Report</title>
    <style>
        @page {
            size: A4;
            margin: 20mm;
            @bottom-right {
                content: "{{ labels.page }} " counter(page) " {{ labels.of }} " counter(pages);
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
            position: relative;
        }
        .cover-top {
            position: absolute;
            top: 8mm;
            left: 0;
            right: 0;
            text-align: center;
        }
        .cover-image { max-width: 400px; max-height: 132px; object-fit: contain; }
        .cover-brand-text { font-size: 14pt; font-weight: 800; color: #12121A; letter-spacing: -0.01em; }
        .cover-main {
            position: absolute;
            top: 78mm;
            left: 0;
            right: 0;
            max-width: 140mm;
        }
        .cover-eyebrow {
            color: #77798A;
            font-size: 8pt;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 9mm;
        }
        .cover-logo { font-size: 30pt; line-height: 1.12; font-weight: 800; color: #11121A; letter-spacing: -0.01em; }
        .cover-logo span { color: __BRAND__; }
        .cover-client {
            margin-top: 9mm;
            padding-left: 5mm;
            border-left: 3px solid __BRAND__;
            color: #3F4354;
            font-size: 14pt;
            font-weight: 700;
            line-height: 1.25;
        }
        .cover-meta {
            position: absolute;
            left: 0;
            right: 0;
            bottom: 28mm;
            max-width: 146mm;
            display: table; table-layout: fixed; width: 100%;
            border-top: 1px solid #E6E6EF; padding-top: 12px;
            color: #5E5E70; font-size: 9pt; line-height: 1.45;
        }
        .cover-meta-row { display: table-row; }
        .cover-meta-label {
            display: table-cell; width: 38mm; padding: 2px 10px 2px 0;
            color: #8A8A9B; font-weight: 700; text-transform: uppercase; font-size: 7.5pt; letter-spacing: 0.04em;
        }
        .cover-meta-value {
            display: table-cell; padding: 2px 0;
            color: #3D3D49; font-weight: 600;
        }
        .cover-footer {
            position: absolute;
            left: 0;
            right: 0;
            bottom: 0;
            color: #9A9AAC;
            font-size: 8pt;
            border-top: 1px solid #EFEFF5;
            padding-top: 5mm;
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
        <div class="cover-top">
            {% if logo_data_uri %}<img src="{{ logo_data_uri }}" class="cover-image">{% else %}<div class="cover-brand-text">{{ brand_name }}</div>{% endif %}
        </div>
        <div class="cover-main">
            <div class="cover-eyebrow">{{ labels.confidential_report }}</div>
            <div class="cover-logo">{{ labels.cover_subtitle }}</div>
            {% if client_name %}<div class="cover-client">{{ client_name }}</div>{% endif %}
        </div>
        <div class="cover-meta">
            {% if period_label %}<div class="cover-meta-row"><div class="cover-meta-label">{{ labels.period }}</div><div class="cover-meta-value">{{ period_label }}</div></div>{% endif %}
            <div class="cover-meta-row"><div class="cover-meta-label">{{ labels.created_on }}</div><div class="cover-meta-value">{{ date }}</div></div>
            <div class="cover-meta-row"><div class="cover-meta-label">{{ labels.report_version }}</div><div class="cover-meta-value">{{ report_version }} &bull; {{ labels.analysis }} {{ app_version }}</div></div>
            {% if niche %}<div class="cover-meta-row"><div class="cover-meta-label">{{ labels.industry }}</div><div class="cover-meta-value">{{ niche }}</div></div>{% endif %}
            <div class="cover-meta-row"><div class="cover-meta-label">{{ labels.data_basis }}</div><div class="cover-meta-value">{{ kpis.anzahl_zeilen | report_number(0, language) if kpis.anzahl_zeilen is defined else "n/a" }} {{ labels.records }} in {{ kpis.anzahl_kategorien if kpis.anzahl_kategorien is defined else "n/a" }} {{ labels.categories }}</div></div>
        </div>
        <div class="cover-footer">{% if brand_name and brand_name != "DataDeck" %}{{ labels.created_by }} {{ brand_name }} &bull; DataDeck{% else %}DataDeck{% endif %}</div>
    </div>

    <div class="header">
        <div class="logo">{{ brand_name }}</div>
        <div class="subtitle">
            {{ labels.cover_subtitle }} &bull; {{ date }}
            {% if niche %}&bull; {{ niche }}{% endif %}
        </div>
    </div>

    {% if report_settings.show_kpis %}<h2>{{ labels.core_metrics }}</h2>
    <div class="kpi-container">
        <div class="kpi-box"><div class="kpi-title">{{ labels.revenue }}</div><div class="kpi-value">{% if aggregation_limited %}&mdash;{% else %}{{ kpis.gesamt_umsatz | report_money(language) }}{% endif %}</div><div class="kpi-reason">{% if aggregation_limited %}{{ labels.multiple_currencies }}{% else %}{{ labels.measured_revenue }}{% endif %}</div></div>
        <div class="kpi-box"><div class="kpi-title">{{ labels.profit }}</div><div class="kpi-value">{% if revenue_only or aggregation_limited %}&mdash;{% else %}{{ kpis.gesamt_gewinn | report_money(language) }}{% endif %}</div><div class="kpi-reason">{% if aggregation_limited %}{{ labels.multiple_currencies }}{% elif revenue_only %}{{ labels.not_calculable_costs }}{% elif kpis.metrics.gewinn.status == 'ESTIMATED' %}{{ labels.from_revenue_cost }}{% else %}{{ labels.from_profit_column }}{% endif %}</div></div>
        <div class="kpi-box"><div class="kpi-title">{{ labels.margin }}</div><div class="kpi-value">{% if revenue_only or aggregation_limited %}&mdash;{% else %}{{ kpis.aktuelle_marge | report_percent(1, language) if kpis.aktuelle_marge == kpis.aktuelle_marge else "-" }}{% endif %}</div><div class="kpi-reason">{% if aggregation_limited %}{{ labels.multiple_currencies }}{% elif revenue_only %}{{ labels.not_available }}{% else %}{{ labels.profit_div_revenue }}{% endif %}</div></div>
        <div class="kpi-box"><div class="kpi-title">{{ labels.records }}</div><div class="kpi-value">{{ kpis.anzahl_zeilen | report_number(0, language) if kpis.anzahl_zeilen is defined else "n/a" }}</div><div class="kpi-reason">{{ labels.clean_rows }}</div></div>
    </div>
    {% endif %}
    {% if aggregation_limited %}
    <div class="report-note">{{ labels.currency_note }}</div>
    {% endif %}
    {% if revenue_only %}
    <div class="report-note">{{ labels.revenue_only_note }}</div>
    {% endif %}

    {% if report_settings.show_ai_insights and insights %}
    <h2>{{ labels.ai_insights }}</h2>
    {% if report_settings.show_summary %}
    <div class="insight-box"><span class="insight-tag">{{ labels.summary }}</span>{{ insights.zusammenfassung }}</div>
    {% endif %}
    <div class="insight-box"><span class="insight-tag">{{ labels.meaning }}</span>{{ insights.ziel_analyse }}</div>
    <strong style="font-size:10.5pt;">{{ labels.recommendations }}</strong>
    <ul>
        {% for plan in insights.action_plan %}
        <li>{{ plan }}</li>
        {% endfor %}
    </ul>
    {% if insights.datengrundlage %}
    <div class="insight-box"><span class="insight-tag">{{ labels.evidence }}</span>{{ insights.datengrundlage }}</div>
    {% endif %}
    {% elif report_settings.show_ai_insights %}
    <h2>{{ labels.ai_insights }}</h2>
    <p class="empty-note">{{ labels.no_ai }}</p>
    {% endif %}

    {% if report_settings.show_segments and not aggregation_limited %}<h2>{% if revenue_only %}{{ labels.top_revenue_segments }}{% else %}{{ labels.top_profit_segments }}{% endif %}</h2>
    {% if kpis.top_performer %}
    <table>
        <thead><tr><th>{{ labels.segment }}</th><th>{% if revenue_only %}{{ labels.revenue }}{% else %}{{ labels.profit }}{% endif %}</th>{% if not revenue_only %}<th>{{ labels.margin }}</th>{% endif %}</tr></thead>
        <tbody>
            {% for row in kpis.top_performer %}
            <tr><td>{{ row.Kategorie_Clean }}</td><td>{{ (row.Umsatz_Clean if revenue_only else row.Gewinn_Clean) | report_money(language) }}</td>{% if not revenue_only %}<td>{{ row.Marge | report_percent(1, language) if row.Marge == row.Marge else "-" }}</td>{% endif %}</tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}<p class="empty-note">{{ labels.no_segments }}</p>{% endif %}

    <h2>{% if revenue_only %}{{ labels.weak_revenue_segments }}{% else %}{{ labels.weak_profit_segments }}{% endif %}</h2>
    {% if kpis.flop_performer %}
    <table>
        <thead><tr><th>{{ labels.segment }}</th><th>{% if revenue_only %}{{ labels.revenue }}{% else %}{{ labels.profit }}{% endif %}</th>{% if not revenue_only %}<th>{{ labels.margin }}</th>{% endif %}</tr></thead>
        <tbody>
            {% for row in kpis.flop_performer %}
            <tr><td>{{ row.Kategorie_Clean }}</td><td>{{ (row.Umsatz_Clean if revenue_only else row.Gewinn_Clean) | report_money(language) }}</td>{% if not revenue_only %}<td>{{ row.Marge | report_percent(1, language) if row.Marge == row.Marge else "-" }}</td>{% endif %}</tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}<p class="empty-note">{{ labels.no_segments }}</p>{% endif %}{% endif %}

    {% if report_settings.show_time_series and kpis.time_analysis and kpis.time_analysis.available %}
    <h2>{{ labels.period_development }}</h2>
    <p>{{ labels.period_analyzed }}: {{ kpis.time_analysis.start | report_date(language) }} - {{ kpis.time_analysis.end | report_date(language) }}.</p>
    {% if kpis.time_analysis.comparison_available %}
    <p>{{ labels.revenue_change }} {{ kpis.time_analysis.comparison_label }}:
       <strong>{{ kpis.time_analysis.revenue_change_pct | report_percent(1, language) }}</strong>.</p>
    {% if kpis.time_analysis.current_is_partial %}<p class="empty-note">{{ labels.partial_period }} {{ kpis.time_analysis.current_data_through | report_date(language) }}; {{ labels.same_period }}.</p>{% endif %}
    {% else %}<p class="empty-note">{{ kpis.time_analysis.reason }}</p>{% endif %}
    {% endif %}

    {% if consultant_comment %}<h2>{{ labels.consultant_comment }}</h2><div class="insight-box">{{ consultant_comment }}</div>{% endif %}

    {% if report_settings.show_methodology %}<h2>{{ labels.methodology }}</h2>
    {% if data_quality %}
    <p>{{ labels.quality }}: <strong>{{ data_quality.level | replace('eingeschraenkt', 'eingeschränkt') | replace('nicht_ausreichend', 'nicht ausreichend') | capitalize }}</strong>; {{ labels.completeness }}: <strong>{{ (data_quality.completeness * 100) | report_percent(0, language) }}</strong>.</p>
    <ul>
        <li>{{ data_quality.rows | report_number(0, language) }} {{ labels.records }} und {{ data_quality.columns }} {{ labels.columns }} {{ labels.checked }}.</li>
        <li>{{ data_quality.missing_cells | report_number(0, language) }} {{ labels.missing_cells }}, {{ data_quality.invalid_numeric | report_number(0, language) }} {{ labels.invalid_financial }}, {{ data_quality.duplicate_rows | report_number(0, language) }} {{ labels.duplicates }}.</li>
        {% for issue in data_quality.issues %}<li><strong>{{ issue.title }}:</strong> {{ issue.detail }}</li>{% endfor %}
    </ul>
    {% endif %}
    {% if column_mapping %}
    <p><strong>{{ labels.used_columns }}:</strong>
       {{ labels.revenue }}: {{ column_mapping.umsatz or '-' }};
       {{ labels.profit }}: {{ column_mapping.gewinn or '-' }};
       {{ labels.costs }}: {{ column_mapping.kosten or '-' }};
       {{ labels.date }}: {{ column_mapping.datum or '-' }}.</p>
    {% endif %}
    <p class="empty-note">{{ labels.method_note }}</p>
    <p class="empty-note">{{ labels.disclaimer }}</p>
    {% endif %}

    {% if report_settings.footer_text or report_settings.contact_name or report_settings.contact_email %}
    <div style="margin-top:24px;padding-top:10px;border-top:1px solid #E6E6EC;color:#6B6B7A;font-size:8.5pt;">
        {{ report_settings.footer_text }}{% if report_settings.contact_name %}<br>{{ report_settings.contact_name }}{% endif %}{% if report_settings.contact_email %} &bull; {{ report_settings.contact_email }}{% endif %}
    </div>
    {% endif %}

</body>
</html>
"""

_jinja_env = Environment(
    autoescape=select_autoescape(enabled_extensions=('html', 'xml'), default_for_string=True)
)
_jinja_env.filters['de_number'] = format_de_number
_jinja_env.filters['report_number'] = format_report_number
_jinja_env.filters['report_money'] = format_report_money
_jinja_env.filters['report_percent'] = format_report_percent
_jinja_env.filters['report_date'] = format_report_date
_template = _jinja_env.from_string(TEMPLATE_HTML.replace("__BRAND__", "#4F46E5"))
_template.globals.update(
    app_version=APP_VERSION,
    report_settings=normalize_report_settings(None),
    language="de",
    labels=labels_for("de"),
    consultant_comment="",
    brand_name="DataDeck",
    client_name="",
    period_label="",
    report_version=1,
    logo_data_uri=None,
    aggregation_limited=False,
    revenue_only=False,
    data_quality=None,
    column_mapping={},
)


def generate_pdf(
    kpis: dict,
    ai_insights: Optional[dict],
    niche: Optional[str] = None,
    revenue_only: bool = False,
    data_quality: Optional[dict] = None,
    column_mapping: Optional[dict] = None,
    report_settings: Optional[dict] = None,
    consultant_comment: str = "",
    client_name: str = "",
    period_label: str = "",
    report_version: int = 1,
    logo_bytes: bytes | None = None,
) -> bytes:
    """Rendert das HTML-Template (Jinja2 Auto-Escaping) und erzeugt ein PDF
    via WeasyPrint. kpis MUSS das Ergebnis von core.analysis.calculate_kpis
    sein (bereits gefiltert, falls Dashboard-Filter aktiv sind)."""
    if sys.platform == "darwin":
        os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")
    from weasyprint import HTML

    settings = normalize_report_settings(report_settings)
    language = normalize_report_language(settings.get("language"))
    template = _jinja_env.from_string(TEMPLATE_HTML.replace("__BRAND__", settings["accent_color"]))
    html_content = template.render(
        date=format_report_date(datetime.datetime.now(), language, include_time=True),
        app_version=APP_VERSION,
        kpis=kpis,
        insights=ai_insights if ai_insights else None,
        niche=niche,
        language=language,
        labels=labels_for(language),
        revenue_only=revenue_only,
        data_quality=data_quality,
        column_mapping=column_mapping or kpis.get("column_mapping", {}),
        aggregation_limited=not kpis.get("financial_aggregation_available", True),
        report_settings=settings,
        consultant_comment=consultant_comment[:2_000],
        brand_name=settings["company_name"] or "DataDeck",
        client_name=client_name[:160],
        period_label=period_label[:120],
        report_version=max(1, int(report_version)),
        logo_data_uri=validated_logo_data_uri(logo_bytes),
    )
    pdf_bytes = HTML(string=html_content, url_fetcher=_blocking_url_fetcher).write_pdf()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise ValueError("Der PDF-Report überschreitet das sichere Größenlimit")
    return pdf_bytes
