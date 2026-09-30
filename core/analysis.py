"""
Deterministische KPI-Berechnung und Filterung für DataDeck.

REGEL (nicht verhandelbar, siehe Master-Auftrag):
    Umsatz > 0:  Marge = Gewinn / Umsatz * 100
    Umsatz = 0:  Marge = NaN
    Umsatz fehlt/ungültig: Marge = NaN
NIEMALS Umsatz=1 als Ersatzwert (v3.2-Antipattern) und NIEMALS 0%/100% als
Ersatz für "nicht berechenbar" (Antipattern meiner Vorversion, die bei
Umsatz=0 künstlich 0.0 zurückgab). Verifiziert gegen pandas 3.0.2: pd.NA
funktioniert in einer float64-Series NICHT zuverlässig (TypeError beim
Erzwingen) - hier wird ausschließlich np.nan verwendet.

Das ist die EINZIGE Stelle, an der Umsatz/Gewinn/Marge/Top/Flop berechnet
werden. Dashboard, PDF und der an Gemini gesendete Prompt beziehen sich
alle auf exakt dieses Ergebnis (kpis-Dict) - nie auf eine eigene,
abweichende Berechnung.
"""

import calendar

import numpy as np
import pandas as pd


METRIC_AVAILABLE = "AVAILABLE"
METRIC_UNAVAILABLE = "UNAVAILABLE"
METRIC_ESTIMATED = "ESTIMATED"
METRIC_PROXY = "PROXY"
METRIC_LIMITED = "LIMITED"


def _safe_margin(gewinn: pd.Series, umsatz: pd.Series) -> pd.Series:
    """
    Gewinn/Umsatz*100 elementweise, ohne künstliche Werte bei Umsatz=0.
    Ergebnis ist NaN, wenn Umsatz 0 ist - unabhängig vom Gewinn-Vorzeichen
    (auch 0 Gewinn / 0 Umsatz wird zu NaN, nicht zu 0%).
    """
    umsatz_f = umsatz.astype(float)
    gewinn_f = gewinn.astype(float)
    return pd.Series(
        np.where(umsatz_f != 0, (gewinn_f / umsatz_f.replace(0, np.nan)) * 100, np.nan),
        index=gewinn.index,
    )


def _safe_change(current: float, previous: float) -> float:
    if previous == 0 or np.isnan(previous):
        return float('nan')
    return float((current - previous) / abs(previous) * 100)


def _month_window_label(start: pd.Timestamp, end: pd.Timestamp) -> str:
    months = (
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    )
    if start.normalize() == end.normalize():
        return f"{start.day}. {months[start.month - 1]} {start.year}"
    return f"{start.day:02d}.–{end.day:02d}. {months[start.month - 1]} {start.year}"


def _calculate_time_analysis(
    df: pd.DataFrame,
    profit_available: bool,
    today: pd.Timestamp | None = None,
) -> dict:
    if 'Datum_Clean' not in df.columns:
        return {"available": False, "reason": "Keine Datumsspalte erkannt."}

    dated = df.dropna(subset=['Datum_Clean']).copy()
    if dated.empty:
        return {"available": False, "reason": "Keine gültigen Datumswerte vorhanden."}

    dated['Datum_Clean'] = pd.to_datetime(dated['Datum_Clean'], errors='coerce').dt.tz_localize(None)
    dated = dated.dropna(subset=['Datum_Clean'])
    reference_day = (today if today is not None else pd.Timestamp.today()).normalize().tz_localize(None)
    future_rows = int((dated['Datum_Clean'] > reference_day).sum())
    dated = dated.loc[dated['Datum_Clean'] <= reference_day].copy()
    if dated.empty:
        return {
            "available": False,
            "reason": "Alle gültigen Datumswerte liegen in der Zukunft.",
            "future_rows": future_rows,
        }

    dated['Zeitraum'] = dated['Datum_Clean'].dt.to_period('M').dt.to_timestamp()
    monthly = dated.groupby('Zeitraum').agg(
        Umsatz_Clean=('Umsatz_Clean', 'sum'),
        Gewinn_Clean=('Gewinn_Clean', lambda values: values.sum(min_count=1)),
        Datensaetze=('Zeitraum', 'size'),
    ).reset_index().sort_values('Zeitraum')
    monthly['Marge'] = _safe_margin(monthly['Gewinn_Clean'], monthly['Umsatz_Clean'])
    observed = dated.groupby('Zeitraum')['Datum_Clean'].agg(['min', 'max']).reset_index()
    monthly = monthly.merge(observed, on='Zeitraum', how='left')
    monthly['Monatsende'] = monthly['Zeitraum'].map(
        lambda value: value + pd.offsets.MonthEnd(0)
    )
    monthly['Ist_Vollstaendig'] = (
        monthly['min'].dt.normalize().eq(monthly['Zeitraum'])
        & monthly['max'].dt.normalize().eq(monthly['Monatsende'])
    )
    monthly['Ist_Teilmonat'] = ~monthly['Ist_Vollstaendig']
    monthly['Zeitraum_Label'] = monthly.apply(
        lambda row: f"{row['Zeitraum']:%m/%Y}{'*' if row['Ist_Teilmonat'] else ''}", axis=1
    )

    result = {
        "available": True,
        "start": dated['Datum_Clean'].min(),
        "end": dated['Datum_Clean'].max(),
        "period_count": int(len(monthly)),
        "series": monthly,
        "comparison_available": False,
        "future_rows": future_rows,
    }
    if len(monthly) < 2:
        result["reason"] = "Für einen Vergleich werden mindestens zwei Monate benötigt."
        return result

    current = monthly.iloc[-1]
    current_period = current['Zeitraum']
    previous_period = current_period - pd.offsets.MonthBegin(1)
    previous_rows = dated.loc[dated['Zeitraum'].eq(previous_period)]
    if previous_rows.empty:
        result["reason"] = "Für den letzten Datenmonat fehlt der direkte Vormonat."
        return result

    current_start = current['min'].normalize()
    current_end = current['max'].normalize()
    comparison_type = "FULL_MONTH" if bool(current['Ist_Vollstaendig']) else "MTD"

    if comparison_type == "FULL_MONTH":
        previous_summary = monthly.loc[monthly['Zeitraum'].eq(previous_period)].iloc[0]
        if not bool(previous_summary['Ist_Vollstaendig']):
            result["reason"] = "Der Vormonat ist nicht vollständig und daher nicht belastbar vergleichbar."
            return result
        current_rows = dated.loc[dated['Zeitraum'].eq(current_period)]
        previous_window = previous_rows
        previous_start = previous_period
        previous_end = previous_period + pd.offsets.MonthEnd(0)
    else:
        previous_days = calendar.monthrange(previous_period.year, previous_period.month)[1]
        previous_start_day = min(current_start.day, previous_days)
        previous_end_day = min(current_end.day, previous_days)
        previous_start = previous_period.replace(day=previous_start_day)
        previous_end = previous_period.replace(day=previous_end_day)
        previous_observed_start = previous_rows['Datum_Clean'].min().normalize()
        previous_observed_end = previous_rows['Datum_Clean'].max().normalize()
        if previous_observed_start > previous_start or previous_observed_end < previous_end:
            result["reason"] = (
                "Der Vormonat deckt nicht dasselbe Tagesfenster ab; ein fairer "
                "Teilmonatsvergleich ist noch nicht möglich."
            )
            return result
        current_rows = dated.loc[
            dated['Zeitraum'].eq(current_period)
            & dated['Datum_Clean'].between(current_start, current_end)
        ]
        previous_window = previous_rows.loc[
            previous_rows['Datum_Clean'].between(previous_start, previous_end)
        ]

    current_revenue = float(current_rows['Umsatz_Clean'].sum())
    previous_revenue = float(previous_window['Umsatz_Clean'].sum())
    current_profit = float(current_rows['Gewinn_Clean'].sum(min_count=1)) if profit_available else float('nan')
    previous_profit = float(previous_window['Gewinn_Clean'].sum(min_count=1)) if profit_available else float('nan')
    current_margin = (
        current_profit / current_revenue * 100
        if profit_available and current_revenue != 0 else float('nan')
    )
    previous_margin = (
        previous_profit / previous_revenue * 100
        if profit_available and previous_revenue != 0 else float('nan')
    )

    result.update({
        "comparison_available": True,
        "comparison_type": comparison_type,
        "current_is_partial": comparison_type == "MTD",
        "current_period": current_period,
        "previous_period": previous_period,
        "current_data_through": current_end,
        "current_window_start": current_start,
        "current_window_end": current_end,
        "previous_window_start": previous_start,
        "previous_window_end": previous_end,
        "comparison_label": (
            f"{_month_window_label(current_start, current_end)} vs. "
            f"{_month_window_label(previous_start, previous_end)}"
        ),
        "current_revenue": current_revenue,
        "previous_revenue": previous_revenue,
        "revenue_change_pct": _safe_change(current_revenue, previous_revenue),
        "profit_change_pct": (
            _safe_change(current_profit, previous_profit)
            if profit_available else float('nan')
        ),
        "margin_change_pp": (
            float(current_margin - previous_margin)
            if profit_available and not np.isnan(current_margin) and not np.isnan(previous_margin)
            else float('nan')
        ),
    })
    return result


def calculate_kpis(df: pd.DataFrame, analysis_context: dict | None = None) -> dict:
    """
    Berechnet Gesamtsummen, Gesamt-Marge sowie Top-/Flop-Performer je
    Kategorie. Erwartet ein bereits bereinigtes/gefiltertes DataFrame mit
    den Spalten Umsatz_Clean, Gewinn_Clean, Kategorie_Clean (siehe
    core/data_processing.clean_and_prepare_data und filter_data() unten).
    """

    gesamt_umsatz = float(df['Umsatz_Clean'].sum())
    profit_available = bool(df['Gewinn_Clean'].notna().any())
    gesamt_gewinn = (
        float(df['Gewinn_Clean'].sum(min_count=1))
        if profit_available else float('nan')
    )

    aktuelle_marge = (
        (gesamt_gewinn / gesamt_umsatz) * 100
        if profit_available and gesamt_umsatz != 0
        else float('nan')
    )

    cat_df = df.groupby('Kategorie_Clean', dropna=False).agg(
        Umsatz_Clean=('Umsatz_Clean', 'sum'),
        Gewinn_Clean=('Gewinn_Clean', lambda values: values.sum(min_count=1)),
        Datensaetze=('Kategorie_Clean', 'size'),
    ).reset_index()

    cat_df['Marge'] = _safe_margin(cat_df['Gewinn_Clean'], cat_df['Umsatz_Clean'])

    ranking_column = 'Gewinn_Clean' if profit_available else 'Umsatz_Clean'
    ranking_label = 'Gewinn' if profit_available else 'Umsatz'
    top_performer = cat_df.sort_values(
        by=[ranking_column, 'Umsatz_Clean'], ascending=[False, False], na_position='last'
    ).head(3).to_dict('records')
    flop_performer = cat_df.sort_values(
        by=[ranking_column, 'Umsatz_Clean'], ascending=[True, True], na_position='last'
    ).head(3).to_dict('records')

    context = analysis_context or {}
    data_quality = context.get("data_quality") or {}
    financial_aggregation_available = not bool(data_quality.get("multiple_currencies"))
    aggregation_reason = (
        "Mehrere Währungen ohne Wechselkurse erkannt; Summen sind nicht aggregierbar."
        if not financial_aggregation_available else ""
    )
    profit_status = (
        METRIC_AVAILABLE if profit_available and context.get("kosten_source") is None
        else METRIC_ESTIMATED if profit_available
        else METRIC_UNAVAILABLE
    )
    profit_reason = ""
    if not profit_available:
        profit_reason = "Keine Gewinn- oder Kostenbasis vorhanden."
    elif context.get("kosten_source"):
        profit_reason = "Aus Umsatz abzüglich Kosten berechnet."

    metrics = {
        "umsatz": {
            "value": gesamt_umsatz,
            "status": METRIC_AVAILABLE if financial_aggregation_available else METRIC_LIMITED,
            "reason": aggregation_reason,
            "source": context.get("umsatz_source"),
        },
        "gewinn": {
            "value": gesamt_gewinn,
            "status": profit_status if financial_aggregation_available else METRIC_LIMITED,
            "reason": aggregation_reason or profit_reason,
            "source": context.get("gewinn_source"),
        },
        "marge": {
            "value": float(aktuelle_marge),
            "status": (
                profit_status if profit_available else METRIC_UNAVAILABLE
            ) if financial_aggregation_available else METRIC_LIMITED,
            "reason": (
                aggregation_reason
                or "Bei Gesamtumsatz null nicht berechenbar."
                if profit_available and np.isnan(aktuelle_marge)
                else aggregation_reason or profit_reason
            ),
            "source": "Gewinn / Umsatz",
        },
        "datensaetze": {
            "value": int(len(df)),
            "status": METRIC_AVAILABLE,
            "reason": "",
            "source": "Bereinigte Datenzeilen",
        },
    }

    time_analysis = (
        _calculate_time_analysis(df, profit_available)
        if financial_aggregation_available
        else {"available": False, "reason": aggregation_reason}
    )
    return {
        "gesamt_umsatz": gesamt_umsatz,
        "gesamt_gewinn": gesamt_gewinn,
        "aktuelle_marge": float(aktuelle_marge),
        "anzahl_zeilen": int(len(df)),
        "anzahl_kategorien": int(cat_df.shape[0]),
        "top_performer": top_performer if financial_aggregation_available else [],
        "flop_performer": flop_performer if financial_aggregation_available else [],
        "kategorien_daten": cat_df,
        "profit_available": profit_available,
        "financial_aggregation_available": financial_aggregation_available,
        "ranking_metric": ranking_column,
        "ranking_label": ranking_label,
        "metrics": metrics,
        "metric_status": {name: metric["status"] for name, metric in metrics.items()},
        "column_mapping": {
            "umsatz": context.get("umsatz_source"),
            "gewinn": context.get("gewinn_source"),
            "kosten": context.get("kosten_source"),
            "kategorie": context.get("kategorie_source"),
            "datum": context.get("datum_source"),
        },
        "data_quality": data_quality,
        "mapping_confidence": context.get("mapping_confidence", {}),
        "warnings": list(context.get("analysis_limitations", [])),
        "date_range": {
            "start": time_analysis.get("start"),
            "end": time_analysis.get("end"),
        },
        "time_analysis": time_analysis,
    }


def filter_data(
    df: pd.DataFrame,
    min_gewinn: float = 0.0,
    min_marge: float = 0.0,
) -> pd.DataFrame:
    """
    Live-Dashboard-Filter (Mindest-Gewinn, Mindest-Marge) auf Zeilenebene -
    Feature aus Enterprise v3.2, hier aber mit korrekter Umsatz=0-Behandlung
    (v3.2 hatte an dieser Stelle Umsatz=0 durch 1 ersetzt, um die Division
    zu ermöglichen - das wird hier NICHT übernommen).

    Zeilen mit Umsatz=0 (Zeilen-Marge = NaN) erfüllen einen aktiven
    min_marge>0-Filter grundsätzlich nicht (NaN >= x ist immer False) -
    das ist beabsichtigt: eine Zeile ohne bewertbare Marge kann keinen
    Mindest-Margen-Filter erfüllen. Bei min_marge=0 (Filter deaktiviert)
    bleiben auch Umsatz=0-Zeilen erhalten.
    """
    if df.empty:
        return df

    profit_available = bool(df['Gewinn_Clean'].notna().any())
    mask = pd.Series(True, index=df.index)

    if profit_available:
        mask &= df['Gewinn_Clean'] >= min_gewinn
    elif min_gewinn > 0 or min_marge > 0:
        return df.iloc[0:0].copy()

    if profit_available and min_marge > 0:
        marge_zeile = _safe_margin(df['Gewinn_Clean'], df['Umsatz_Clean'])
        mask &= marge_zeile >= min_marge

    return df.loc[mask].copy()
