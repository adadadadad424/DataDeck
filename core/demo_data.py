"""Synthetic, deterministic financial data for the public product demo."""

from __future__ import annotations

import pandas as pd


_REVENUE = {
    "Enterprise": (82, 88, 91, 96, 101, 108, 112, 119, 126, 132, 139, 147),
    "Growth": (48, 51, 54, 56, 61, 63, 67, 70, 72, 76, 79, 84),
    "Starter": (26, 28, 29, 31, 30, 34, 35, 36, 38, 40, 41, 43),
}
_COST_RATIOS = {"Enterprise": 0.68, "Growth": 0.75, "Starter": 0.92}
DEMO_SEGMENTS = ("Gesamt", *_REVENUE)


def demo_financials(segment: str = "Gesamt", periods: int = 12) -> pd.DataFrame:
    if segment not in DEMO_SEGMENTS or not 3 <= periods <= 12:
        raise ValueError("Ungültige Demo-Auswahl")
    selected = _REVENUE if segment == "Gesamt" else {segment: _REVENUE[segment]}
    rows = []
    for month_index, month in enumerate(pd.date_range("2025-10-01", periods=12, freq="MS")):
        revenue = sum(values[month_index] for values in selected.values())
        costs = sum(values[month_index] * _COST_RATIOS[name] for name, values in selected.items())
        profit = revenue - costs
        rows.append({
            "Monat": month, "Umsatz": float(revenue), "Kosten": round(costs, 2),
            "Gewinn": round(profit, 2), "Marge": profit / revenue * 100,
        })
    return pd.DataFrame(rows).tail(periods).reset_index(drop=True)
