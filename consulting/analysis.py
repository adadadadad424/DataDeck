"""Deterministic period comparisons, changes and internal benchmarks."""

from __future__ import annotations

import calendar
import datetime as dt
import math
from typing import Iterable

from .models import AnalysisSnapshot


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(current, previous) -> float | None:
    current_value, previous_value = _finite(current), _finite(previous)
    if current_value is None or previous_value in (None, 0):
        return None
    return (current_value - previous_value) / abs(previous_value) * 100


def _month_shift(value: dt.date, months: int) -> dt.date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return dt.date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _segments(snapshot: AnalysisSnapshot) -> dict[str, dict]:
    return {
        str(row.get("category")): row
        for row in snapshot.result.get("segments", [])
        if row.get("category") is not None
    }


def _is_month_period(snapshot: AnalysisSnapshot) -> bool:
    days = (snapshot.period_end - snapshot.period_start).days + 1
    return (
        snapshot.period_start.day == 1
        and snapshot.period_start.year == snapshot.period_end.year
        and snapshot.period_start.month == snapshot.period_end.month
        and 28 <= days <= 31
    )


def _is_quarter_period(snapshot: AnalysisSnapshot) -> bool:
    if snapshot.period_start.day != 1 or snapshot.period_start.month not in {1, 4, 7, 10}:
        return False
    quarter_end_month = snapshot.period_start.month + 2
    expected_end = dt.date(
        snapshot.period_start.year,
        quarter_end_month,
        calendar.monthrange(snapshot.period_start.year, quarter_end_month)[1],
    )
    return snapshot.period_end == expected_end


def _same_period_shape(current: AnalysisSnapshot, previous: AnalysisSnapshot) -> bool:
    if _is_month_period(current) and _is_month_period(previous):
        return True
    if _is_quarter_period(current) and _is_quarter_period(previous):
        return True
    return (
        current.period_start.day == previous.period_start.day
        and current.period_end.day == previous.period_end.day
        and (current.period_end - current.period_start).days
        == (previous.period_end - previous.period_start).days
    )


def compare_snapshots(current: AnalysisSnapshot, previous: AnalysisSnapshot) -> dict:
    """Compare two server-owned aggregate snapshots; margins use percentage points."""
    current_segments, previous_segments = _segments(current), _segments(previous)
    all_categories = sorted(set(current_segments) | set(previous_segments))
    segment_changes = []
    for category in all_categories:
        current_row = current_segments.get(category)
        previous_row = previous_segments.get(category)
        segment_changes.append({
            "category": category,
            "status": "new" if previous_row is None else "removed" if current_row is None else "existing",
            "revenue_change_pct": _pct(
                (current_row or {}).get("revenue"), (previous_row or {}).get("revenue")
            ) if current_row and previous_row else None,
            "margin_change_pp": (
                _finite(current_row.get("margin")) - _finite(previous_row.get("margin"))
                if current_row and previous_row
                and _finite(current_row.get("margin")) is not None
                and _finite(previous_row.get("margin")) is not None else None
            ),
        })
    current_margin = _finite(current.result.get("margin"))
    previous_margin = _finite(previous.result.get("margin"))
    return {
        "current_analysis_id": current.analysis_id,
        "previous_analysis_id": previous.analysis_id,
        "revenue_change_pct": _pct(current.result.get("revenue"), previous.result.get("revenue")),
        "profit_change_pct": _pct(current.result.get("profit"), previous.result.get("profit")),
        "margin_change_pp": (
            current_margin - previous_margin
            if current_margin is not None and previous_margin is not None else None
        ),
        "new_categories": [item["category"] for item in segment_changes if item["status"] == "new"],
        "removed_categories": [item["category"] for item in segment_changes if item["status"] == "removed"],
        "segment_changes": segment_changes,
    }


def find_best_comparison(
    current: AnalysisSnapshot,
    history: Iterable[AnalysisSnapshot],
) -> tuple[str, AnalysisSnapshot] | None:
    """Prefer previous month, then previous quarter, then same period last year."""
    candidates = [item for item in history if item.analysis_id != current.analysis_id]
    targets = []
    if _is_month_period(current):
        targets.append(("MoM", -1))
    if _is_quarter_period(current):
        targets.append(("QoQ", -3))
    targets.append(("YoY", -12))
    for label, months in targets:
        target = _month_shift(current.period_start, months)
        match = next(
            (
                item for item in candidates
                if item.period_start == target and _same_period_shape(current, item)
            ),
            None,
        )
        if match:
            return label, match
    earlier = [item for item in candidates if item.period_end < current.period_start]
    return ("Vorperiode", max(earlier, key=lambda item: item.period_end)) if earlier else None


def available_comparisons(
    current: AnalysisSnapshot,
    history: Iterable[AnalysisSnapshot],
) -> dict[str, dict]:
    """Return every exact calendar comparison that is actually supported by history."""
    items = [item for item in history if item.analysis_id != current.analysis_id]
    comparisons = {}
    targets = []
    if _is_month_period(current):
        targets.append(("MoM", -1))
    if _is_quarter_period(current):
        targets.append(("QoQ", -3))
    targets.append(("YoY", -12))
    for label, months in targets:
        target = _month_shift(current.period_start, months)
        previous = next(
            (
                item for item in items
                if item.period_start == target and _same_period_shape(current, item)
            ),
            None,
        )
        if previous:
            comparisons[label] = compare_snapshots(current, previous)
    return comparisons


def year_to_date_comparison(
    history: Iterable[AnalysisSnapshot], current_year: int, through_month: int,
) -> dict | None:
    """Compare complete stored monthly aggregates through the same month in two years."""
    if through_month not in range(1, 13):
        raise ValueError("through_month muss zwischen 1 und 12 liegen")
    items = list(history)
    current = [item for item in items if item.period_start.year == current_year and item.period_start.month <= through_month]
    previous = [item for item in items if item.period_start.year == current_year - 1 and item.period_start.month <= through_month]
    expected_months = set(range(1, through_month + 1))
    if len(current) != through_month or {item.period_start.month for item in current} != expected_months:
        return None
    if len(previous) != through_month or {item.period_start.month for item in previous} != expected_months:
        return None
    if not all(
        _is_month_period(item)
        and item.period_end.day == calendar.monthrange(item.period_end.year, item.period_end.month)[1]
        for item in current + previous
    ):
        return None
    current_revenue = sum(_finite(item.result.get("revenue")) or 0 for item in current)
    previous_revenue = sum(_finite(item.result.get("revenue")) or 0 for item in previous)
    return {
        "comparison_type": "YTD",
        "through_month": through_month,
        "revenue_current": current_revenue,
        "revenue_previous": previous_revenue,
        "revenue_change_pct": _pct(current_revenue, previous_revenue),
    }


def moving_average(
    history: Iterable[AnalysisSnapshot], metric: str = "revenue", window: int = 3,
) -> float | None:
    if window not in {3, 6}:
        raise ValueError("Unterstützt werden 3- oder 6-Monats-Durchschnitte")
    ordered = sorted(history, key=lambda item: item.period_start)
    if len(ordered) < window:
        return None
    recent = ordered[-window:]
    if not all(_is_month_period(item) for item in recent):
        return None
    if any(
        current.period_start != _month_shift(previous.period_start, 1)
        for previous, current in zip(recent, recent[1:])
    ):
        return None
    values = [_finite(item.result.get(metric)) for item in recent]
    if any(value is None for value in values):
        return None
    return sum(values) / window


def detect_trends(history: Iterable[AnalysisSnapshot]) -> list[dict]:
    ordered = sorted(history, key=lambda item: item.period_start)
    if len(ordered) < 3:
        return []
    recent = ordered[-3:]
    month_series = all(_is_month_period(item) for item in recent) and all(
        current.period_start == _month_shift(previous.period_start, 1)
        for previous, current in zip(recent, recent[1:])
    )
    quarter_series = all(_is_quarter_period(item) for item in recent) and all(
        current.period_start == _month_shift(previous.period_start, 3)
        for previous, current in zip(recent, recent[1:])
    )
    if not month_series and not quarter_series:
        return []
    trends = []
    for key, label in (("revenue", "Umsatz"), ("margin", "Marge")):
        values = [_finite(item.result.get(key)) for item in recent]
        if any(value is None for value in values):
            continue
        direction = "steigend" if values[0] < values[1] < values[2] else "sinkend" if values[0] > values[1] > values[2] else None
        if direction:
            trends.append({
                "metric": key, "label": label, "direction": direction,
                "periods": 3, "confidence": "hoch",
                "reason": "Drei aufeinanderfolgende Analyseperioden mit derselben Richtung.",
            })
    return trends


def internal_benchmarks(snapshot: AnalysisSnapshot, target_margin: float | None = None) -> list[dict]:
    segments = snapshot.result.get("segments", [])
    total_revenue = _finite(snapshot.result.get("revenue"))
    company_margin = _finite(snapshot.result.get("margin"))
    benchmarks = []
    for row in segments:
        revenue, margin = _finite(row.get("revenue")), _finite(row.get("margin"))
        benchmarks.append({
            "category": row.get("category"),
            "revenue_share_pct": revenue / total_revenue * 100 if revenue is not None and total_revenue not in (None, 0) else None,
            "margin_vs_company_pp": margin - company_margin if margin is not None and company_margin is not None else None,
        })
    if target_margin is not None and company_margin is not None:
        benchmarks.append({"category": "Gesamt", "margin_vs_target_pp": company_margin - target_margin})
    return benchmarks
