"""Privacy boundary between in-memory analysis and persistent history."""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (int, str, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return str(value)[:200]


def aggregate_result(kpis: dict) -> dict:
    """Return only aggregate facts. Raw rows and source columns cannot cross this API."""
    segments = []
    category_frame = kpis.get("kategorien_daten")
    if isinstance(category_frame, pd.DataFrame):
        for row in category_frame.to_dict("records"):
            segments.append({
                "category": _json_value(row.get("Kategorie_Clean")),
                "revenue": _json_value(row.get("Umsatz_Clean")),
                "profit": _json_value(row.get("Gewinn_Clean")),
                "margin": _json_value(row.get("Marge")),
                "row_count": int(row.get("Datensaetze", 0)),
            })
    time_series = []
    series = (kpis.get("time_analysis") or {}).get("series")
    if isinstance(series, pd.DataFrame):
        for row in series.to_dict("records"):
            time_series.append({
                "period": _json_value(row.get("Zeitraum")),
                "revenue": _json_value(row.get("Umsatz_Clean")),
                "profit": _json_value(row.get("Gewinn_Clean")),
                "margin": _json_value(row.get("Marge")),
                "row_count": int(row.get("Datensaetze", 0)),
                "partial": bool(row.get("Ist_Teilmonat", False)),
            })
    return {
        "revenue": _json_value(kpis.get("gesamt_umsatz")),
        "profit": _json_value(kpis.get("gesamt_gewinn")),
        "margin": _json_value(kpis.get("aktuelle_marge")),
        "row_count": int(kpis.get("anzahl_zeilen", 0)),
        "category_count": int(kpis.get("anzahl_kategorien", 0)),
        "profit_available": bool(kpis.get("profit_available")),
        "financial_aggregation_available": bool(kpis.get("financial_aggregation_available", True)),
        "segments": segments,
        "time_series": time_series,
    }
