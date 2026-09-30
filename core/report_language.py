"""Small German/English language helpers for exported reports.

The application UI can stay German. This module only controls report/PPT
wording and display formatting.
"""

from __future__ import annotations

import datetime
import math

from .formatting import format_de_number


SUPPORTED_REPORT_LANGUAGES = {"de", "en"}


def normalize_report_language(value: str | None) -> str:
    candidate = str(value or "de").strip().lower()
    return candidate if candidate in SUPPORTED_REPORT_LANGUAGES else "de"


def report_language_name(language: str | None) -> str:
    return "Englisch" if normalize_report_language(language) == "en" else "Deutsch"


def format_report_number(value, decimals: int = 2, language: str = "de") -> str:
    language = normalize_report_language(language)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "-"
    if language == "en":
        return f"{number:,.{decimals}f}"
    return format_de_number(number, decimals)


def format_report_percent(value, decimals: int = 1, language: str = "de") -> str:
    return f"{format_report_number(value, decimals, language)} %"


def format_report_money(value, language: str = "de", decimals: int = 2) -> str:
    number = _as_number(value)
    if number is None:
        return "Not available" if normalize_report_language(language) == "en" else "Nicht verfügbar"
    if normalize_report_language(language) == "en":
        return f"€{number:,.{decimals}f}"
    return f"{format_de_number(number, decimals)} €"


def format_report_money_compact(value, language: str = "de") -> str:
    number = _as_number(value)
    lang = normalize_report_language(language)
    if number is None:
        return "Not available" if lang == "en" else "Nicht verfügbar"
    absolute = abs(number)
    if lang == "en":
        if absolute >= 1_000_000_000:
            return f"€{number / 1_000_000_000:,.2f}B"
        if absolute >= 1_000_000:
            return f"€{number / 1_000_000:,.2f}M"
        if absolute >= 10_000:
            return f"€{number / 1_000:,.0f}K"
        return f"€{number:,.0f}"
    if absolute >= 1_000_000_000:
        return f"{format_de_number(number / 1_000_000_000, 2)} Mrd. €"
    if absolute >= 1_000_000:
        return f"{format_de_number(number / 1_000_000, 2)} Mio. €"
    if absolute >= 10_000:
        return f"{format_de_number(number / 1_000, 0)} Tsd. €"
    return f"{format_de_number(number, 0)} €"


def format_report_date(value=None, language: str = "de", include_time: bool = False) -> str:
    lang = normalize_report_language(language)
    current = datetime.datetime.now() if value is None else value
    if isinstance(current, datetime.date) and not isinstance(current, datetime.datetime):
        current = datetime.datetime.combine(current, datetime.time.min)
    if lang == "en":
        return current.strftime("%Y-%m-%d %H:%M") if include_time else current.strftime("%Y-%m-%d")
    return current.strftime("%d.%m.%Y %H:%M") if include_time else current.strftime("%d.%m.%Y")


def _as_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


REPORT_LABELS = {
    "de": {
        "html_lang": "de",
        "cover_subtitle": "Unternehmensanalyse & Strategiebericht",
        "confidential_report": "Vertraulicher Mandantenreport",
        "created_by": "Erstellt von",
        "page": "Seite",
        "of": "/",
        "prepared_for": "Erstellt für",
        "client_default": "Mandant",
        "period": "Berichtszeitraum",
        "current_period": "Aktueller Analysezeitraum",
        "created_on": "Erstellt am",
        "report_version": "Report-Version",
        "analysis": "Analyse",
        "industry": "Branche",
        "data_basis": "Datenbasis",
        "records": "Datensätze",
        "categories": "Kategorien",
        "core_metrics": "Kernkennzahlen",
        "revenue": "Umsatz",
        "costs": "Kosten",
        "profit": "Gewinn",
        "margin": "Marge",
        "measured_revenue": "Gemessene Umsatzbasis",
        "from_profit_column": "Aus Gewinnspalte",
        "from_revenue_cost": "Aus Umsatz minus Kosten",
        "not_calculable_costs": "Nicht berechenbar: Kostenbasis fehlt",
        "not_available": "Nicht verfügbar",
        "multiple_currencies": "Mehrere Währungen",
        "profit_div_revenue": "Gewinn / Umsatz",
        "clean_rows": "Bereinigte Datenzeilen",
        "currency_note": "Mehrere Währungen wurden erkannt. Ohne dokumentierte Wechselkurse enthält dieser Bericht keine Finanzsummen, Rankings oder Zeitvergleiche.",
        "revenue_only_note": "Die Datei enthält Umsatzdaten, aber keine Gewinn- oder Kostenbasis. Gewinn, Marge, Zielmargenvergleich und Profitabilitäts-Rankings sind deshalb nicht berechenbar.",
        "ai_insights": "KI-Insights",
        "summary": "Kurzfassung",
        "meaning": "Bedeutung",
        "recommendations": "Handlungsoptionen",
        "evidence": "Datengrundlage",
        "no_ai": "Für diesen Bericht wurde keine KI-Analyse erstellt.",
        "top_profit_segments": "Gewinnstärkste Segmente",
        "top_revenue_segments": "Umsatzstärkste Segmente",
        "weak_profit_segments": "Gewinnschwächste Segmente",
        "weak_revenue_segments": "Umsatzschwächste Segmente",
        "segment": "Kategorie",
        "no_segments": "Keine Kategoriendaten vorhanden.",
        "period_development": "Zeitraum & Entwicklung",
        "period_analyzed": "Analysierter Zeitraum",
        "revenue_change": "Umsatzveränderung im vergleichbaren Zeitraum",
        "partial_period": "Teilmonatsvergleich bis",
        "same_period": "verglichen wurde dasselbe Tagesfenster des Vormonats",
        "consultant_comment": "Beraterkommentar",
        "methodology": "Methodik und Datenqualität",
        "quality": "Analysequalität",
        "completeness": "Vollständigkeit",
        "checked": "geprüft",
        "missing_cells": "fehlende Zellen",
        "invalid_financial": "ungültige Finanzwerte",
        "duplicates": "mögliche Duplikate",
        "used_columns": "Verwendete Spalten",
        "date": "Datum",
        "method_note": "Finanzkennzahlen werden deterministisch in DataDeck berechnet. Die KI erstellt ausschließlich Einordnung und Handlungsempfehlungen auf Basis aggregierter Kennzahlen. Rohdaten werden nicht an die KI übertragen und die KI darf keine Finanzkennzahlen erfinden oder berechnen.",
        "disclaimer": "DataDeck unterstützt die Analyse und Entscheidungsfindung. Handlungsempfehlungen sollten im jeweiligen Unternehmenskontext bewertet werden.",
        "management_summary": "Management Summary",
        "interpretation": "Einordnung",
        "key_points": "Kernpunkte",
        "priorities": "Prioritäten",
        "performance": "Performance",
        "revenue_development": "Umsatzentwicklung",
        "timeline": "Zeitverlauf",
        "reading": "Lesart",
        "profitability": "Profitabilität",
        "result": "Ergebnis",
        "profit_development": "Gewinnentwicklung",
        "total_margin": "Gesamtmarge",
        "positive_result": "Positives Ergebnis",
        "negative_result": "Negatives Ergebnis",
        "portfolio": "Portfolio",
        "segment_overview": "Segmentübersicht",
        "revenue_by_segment": "Umsatz nach Segment",
        "appendix": "Anhang",
        "columns": "Spalten",
        "no_chart_data": "Keine vergleichbaren Daten verfügbar.",
        "method_no_raw": "An die KI werden ausschließlich aggregierte Kennzahlen übertragen, niemals vollständige Rohdaten.",
    },
    "en": {
        "html_lang": "en",
        "cover_subtitle": "Business Analysis & Strategy Report",
        "confidential_report": "Confidential Client Report",
        "created_by": "Prepared by",
        "page": "Page",
        "of": "of",
        "prepared_for": "Prepared for",
        "client_default": "Client",
        "period": "Reporting period",
        "current_period": "Current analysis period",
        "created_on": "Created on",
        "report_version": "Report version",
        "analysis": "Analysis",
        "industry": "Industry",
        "data_basis": "Data basis",
        "records": "Records",
        "categories": "Categories",
        "core_metrics": "Core metrics",
        "revenue": "Revenue",
        "costs": "Costs",
        "profit": "Profit",
        "margin": "Margin",
        "measured_revenue": "Measured revenue base",
        "from_profit_column": "From profit column",
        "from_revenue_cost": "Revenue minus costs",
        "not_calculable_costs": "Not calculable: cost base missing",
        "not_available": "Not available",
        "multiple_currencies": "Multiple currencies",
        "profit_div_revenue": "Profit / revenue",
        "clean_rows": "Cleaned data rows",
        "currency_note": "Multiple currencies were detected. Without documented exchange rates, this report does not aggregate financial totals, rankings or time comparisons.",
        "revenue_only_note": "The file contains revenue data but no profit or cost base. Profit, margin, target-margin comparison and profitability rankings cannot be calculated.",
        "ai_insights": "AI insights",
        "summary": "Summary",
        "meaning": "Interpretation",
        "recommendations": "Recommendations",
        "evidence": "Evidence base",
        "no_ai": "No AI analysis was created for this report.",
        "top_profit_segments": "Top profit segments",
        "top_revenue_segments": "Top revenue segments",
        "weak_profit_segments": "Weakest profit segments",
        "weak_revenue_segments": "Weakest revenue segments",
        "segment": "Segment",
        "no_segments": "No category data available.",
        "period_development": "Period and development",
        "period_analyzed": "Analyzed period",
        "revenue_change": "Revenue change in comparable period",
        "partial_period": "Partial-month comparison through",
        "same_period": "the same day range of the previous month was compared",
        "consultant_comment": "Consultant note",
        "methodology": "Methodology and Data Quality",
        "quality": "Analysis quality",
        "completeness": "Completeness",
        "checked": "checked",
        "missing_cells": "missing cells",
        "invalid_financial": "invalid financial values",
        "duplicates": "possible duplicates",
        "used_columns": "Used columns",
        "date": "Date",
        "method_note": "Financial KPIs are calculated deterministically in DataDeck. AI only creates interpretation and recommendations from aggregated KPIs. Raw data is not sent to AI and AI must not invent or calculate financial KPIs.",
        "disclaimer": "DataDeck supports analysis and decision-making. Recommendations should be assessed in the relevant business context.",
        "management_summary": "Management Summary",
        "interpretation": "Interpretation",
        "key_points": "Key points",
        "priorities": "Priorities",
        "performance": "Performance",
        "revenue_development": "Revenue development",
        "timeline": "Timeline",
        "reading": "How to read this",
        "profitability": "Profitability",
        "result": "Result",
        "profit_development": "Profit development",
        "total_margin": "Total margin",
        "positive_result": "Positive result",
        "negative_result": "Negative result",
        "portfolio": "Portfolio",
        "segment_overview": "Segment overview",
        "revenue_by_segment": "Revenue by segment",
        "appendix": "Appendix",
        "columns": "Columns",
        "no_chart_data": "No comparable data available.",
        "method_no_raw": "Only aggregated KPIs are sent to AI, never full raw data.",
    },
}


def labels_for(language: str | None) -> dict:
    return REPORT_LABELS[normalize_report_language(language)]
