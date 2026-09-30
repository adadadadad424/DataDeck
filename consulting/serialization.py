"""Privacy boundary between in-memory analysis and persistent history."""

from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd

from core.security import detect_pii_types, mask_pii


_SENSITIVE_CATEGORY_SOURCE_RE = re.compile(
    r"(?:e-?mail|mail|kunde|kundin|customer|name|telefon|phone|kontakt|contact|"
    r"ansprechpartner|inhaber)",
    flags=re.IGNORECASE,
)
_SENSITIVE_CATEGORY_BUCKET = "Personenbezogene Segmente"


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


def _category_source_is_sensitive(source: object) -> bool:
    return bool(source and _SENSITIVE_CATEGORY_SOURCE_RE.search(str(source)))


def _safe_category_value(value, category_source: object = None):
    if value is None:
        return None
    text = str(value).strip()[:200]
    if not text:
        return "Unbekannt"
    if _category_source_is_sensitive(category_source):
        return "[Segment aus personenbezogener Spalte maskiert]"
    masked = mask_pii(text)
    if masked != text or detect_pii_types(text):
        return masked[:200]
    return text[:200]


def aggregate_result(kpis: dict) -> dict:
    """Return only aggregate facts. Raw rows and source columns cannot cross this API."""
    segments = []
    category_frame = kpis.get("kategorien_daten")
    category_source = (kpis.get("column_mapping") or {}).get("kategorie")
    sensitive_category_source = _category_source_is_sensitive(category_source)
    masked_category_labels = False
    if isinstance(category_frame, pd.DataFrame):
        if sensitive_category_source:
            profit_sum = category_frame["Gewinn_Clean"].sum(min_count=1)
            revenue_sum = category_frame["Umsatz_Clean"].sum(min_count=1)
            margin = profit_sum / revenue_sum * 100 if revenue_sum else None
            segments.append({
                "category": _SENSITIVE_CATEGORY_BUCKET,
                "revenue": _json_value(revenue_sum),
                "profit": _json_value(profit_sum),
                "margin": _json_value(margin),
                "row_count": int(category_frame["Datensaetze"].sum()),
            })
            masked_category_labels = True
        else:
            ranked_categories = category_frame.sort_values(
                "Umsatz_Clean", ascending=False, na_position="last"
            ).head(500)
            for row in ranked_categories.to_dict("records"):
                category = _safe_category_value(row.get("Kategorie_Clean"), category_source)
                masked_category_labels = masked_category_labels or category != _json_value(row.get("Kategorie_Clean"))
                segments.append({
                    "category": category,
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
        "segments_truncated": bool(
            isinstance(category_frame, pd.DataFrame)
            and len(category_frame) > len(segments)
            and not sensitive_category_source
        ),
        "category_labels_masked": masked_category_labels,
        "category_labels_bucketed": bool(sensitive_category_source and segments),
        "time_series": time_series,
    }
