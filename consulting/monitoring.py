"""Deterministic monitoring rules for recurring aggregate analyses."""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import math
from dataclasses import dataclass, replace

from .models import AnalysisSnapshot


@dataclass(frozen=True)
class MonitoringSignal:
    rule_id: str
    severity: str
    status: str
    title: str
    detail: str
    evidence: dict[str, float | int | str | bool]
    fingerprint: str


def _number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def _signal(rule_id: str, severity: str, title: str, detail: str,
            evidence: dict[str, float | int | str | bool]) -> MonitoringSignal:
    fingerprint = hashlib.sha256(rule_id.encode()).hexdigest()
    return MonitoringSignal(rule_id, severity, "NEW", title, detail, evidence, fingerprint)


def _top_segment(snapshot: AnalysisSnapshot) -> tuple[str, float] | None:
    revenue = _number(snapshot.result.get("revenue")) or 0
    segments = snapshot.result.get("segments") or []
    valid = [(str(item.get("category", ""))[:120], _number(item.get("revenue")) or 0)
             for item in segments if item.get("category")]
    if not valid or revenue <= 0:
        return None
    name, value = max(valid, key=lambda item: item[1])
    return name, value / revenue * 100


def _complete_month(snapshot: AnalysisSnapshot) -> bool:
    start, end = snapshot.period_start, snapshot.period_end
    return (
        start.day == 1
        and (start.year, start.month) == (end.year, end.month)
        and end.day == calendar.monthrange(end.year, end.month)[1]
    )


def _consecutive_months(older: AnalysisSnapshot, newer: AnalysisSnapshot) -> bool:
    return newer.period_start.year * 12 + newer.period_start.month == (
        older.period_start.year * 12 + older.period_start.month + 1
    )


def _monthly_history(history: list[AnalysisSnapshot]) -> list[AnalysisSnapshot]:
    by_month = {}
    def sort_key(item: AnalysisSnapshot):
        uploaded_at = item.uploaded_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        if uploaded_at.tzinfo is None:
            uploaded_at = uploaded_at.replace(tzinfo=dt.timezone.utc)
        return uploaded_at, item.period_end

    for snapshot in sorted(history, key=sort_key):
        series = snapshot.result.get("time_series")
        if isinstance(series, list) and series:
            for row in series:
                if not isinstance(row, dict) or row.get("partial"):
                    continue
                try:
                    start = dt.date.fromisoformat(f"{row['period']}-01")
                except (KeyError, TypeError, ValueError):
                    continue
                end = dt.date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
                monthly_result = {
                    "revenue": row.get("revenue"), "profit": row.get("profit"),
                    "margin": row.get("margin"),
                    "profit_available": bool(snapshot.result.get("profit_available")),
                }
                by_month[(start.year, start.month)] = replace(
                    snapshot, period_start=start, period_end=end, result=monthly_result,
                )
        elif _complete_month(snapshot):
            start = snapshot.period_start
            by_month[(start.year, start.month)] = snapshot
    return [by_month[key] for key in sorted(by_month)]


def evaluate_monitoring(history: list[AnalysisSnapshot]) -> list[MonitoringSignal]:
    """Evaluate known aggregates only; no AI and no extrapolation are used."""
    if not history:
        return []
    latest_source = max(history, key=lambda item: (item.period_end, item.period_start))
    ordered = _monthly_history(history)
    current = ordered[-1] if ordered else None
    result = current.result if current else {}
    signals: list[MonitoringSignal] = []
    revenue = _number(result.get("revenue"))
    profit = _number(result.get("profit"))
    margin = _number(result.get("margin"))
    profit_available = bool(result.get("profit_available"))

    current_is_complete = current is not None
    previous_is_consecutive = (
        current_is_complete and len(ordered) >= 2 and _complete_month(ordered[-2])
        and _consecutive_months(ordered[-2], current)
    )

    if current_is_complete and profit_available and profit is not None and profit < 0:
        signals.append(_signal(
            "negative_profit", "IMPORTANT", "Negatives Ergebnis",
            "Der jüngste vollständige Zeitraum weist einen negativen Gewinn aus.",
            {"profit": round(profit, 2)},
        ))

    if previous_is_consecutive:
        previous = ordered[-2].result
        revenue_change = _change(revenue, _number(previous.get("revenue")))
        if revenue_change is not None and revenue_change <= -10:
            severity = "IMPORTANT" if revenue_change <= -20 else "NOTICE"
            signals.append(_signal(
                "revenue_drop", severity, "Umsatzrückgang",
                f"Der Umsatz liegt {abs(revenue_change):.1f} % unter dem vorherigen Vergleichszeitraum.",
                {"change_pct": round(revenue_change, 2)},
            ))
        previous_margin = _number(previous.get("margin"))
        if profit_available and margin is not None and previous_margin is not None:
            margin_change = margin - previous_margin
            if margin_change <= -2:
                severity = "IMPORTANT" if margin_change <= -5 else "NOTICE"
                signals.append(_signal(
                    "margin_drop", severity, "Margenrückgang",
                    f"Die Marge ist um {abs(margin_change):.1f} Prozentpunkte gefallen.",
                    {"change_pp": round(margin_change, 2)},
                ))
        if profit_available and bool(previous.get("profit_available")):
            current_cost = None if revenue is None or profit is None else revenue - profit
            previous_revenue = _number(previous.get("revenue"))
            previous_profit = _number(previous.get("profit"))
            previous_cost = None if previous_revenue is None or previous_profit is None else previous_revenue - previous_profit
            cost_change = _change(current_cost, previous_cost)
            if cost_change is not None and cost_change >= 15:
                signals.append(_signal(
                    "cost_increase", "IMPORTANT" if cost_change >= 25 else "NOTICE",
                    "Kostenanstieg", f"Die abgeleiteten Kosten sind um {cost_change:.1f} % gestiegen.",
                    {"change_pct": round(cost_change, 2)},
                ))

    if profit_available and previous_is_consecutive:
        negative_periods = 0
        for snapshot in reversed(ordered):
            if not _complete_month(snapshot):
                break
            if negative_periods and not _consecutive_months(snapshot, ordered[-negative_periods]):
                break
            value = _number(snapshot.result.get("profit"))
            if value is None or value >= 0:
                break
            negative_periods += 1
        if negative_periods >= 2:
            signals.append(_signal(
                "consecutive_negative_periods", "IMPORTANT", "Anhaltend negatives Ergebnis",
                f"{negative_periods} aufeinanderfolgende Zeiträume weisen einen negativen Gewinn aus.",
                {"periods": negative_periods},
            ))

    top = _top_segment(latest_source)
    if top and top[1] >= 40:
        signals.append(_signal(
            "segment_concentration", "IMPORTANT" if top[1] >= 60 else "NOTICE",
            "Hohe Segmentkonzentration",
            f"Das umsatzstärkste Segment trägt {top[1]:.1f} % zum Gesamtumsatz bei.",
            {"share_pct": round(top[1], 2)},
        ))
    if len(history) >= 2 and _complete_month(latest_source):
        earlier_sources = [item for item in history if item.analysis_id != latest_source.analysis_id]
        previous_source = max(earlier_sources, key=lambda item: (item.period_end, item.period_start)) if earlier_sources else None
        previous_top = (_top_segment(previous_source) if previous_source
                        and _complete_month(previous_source)
                        and _consecutive_months(previous_source, latest_source) else None)
        if top and previous_top and top[0] != previous_top[0] and abs(top[1] - previous_top[1]) >= 10:
            signals.append(_signal(
                "segment_shift", "NOTICE", "Segmentverschiebung",
                "Das umsatzstärkste Segment hat sich gegenüber dem Vormonat verändert.",
                {"current_share_pct": round(top[1], 2), "previous_share_pct": round(previous_top[1], 2)},
            ))

    refund_rate = _number(latest_source.result.get("refund_rate"))
    if refund_rate is not None and refund_rate >= 5:
        signals.append(_signal(
            "refund_spike", "IMPORTANT" if refund_rate >= 10 else "NOTICE", "Erhöhte Erstattungsquote",
            f"Die Erstattungsquote liegt bei {refund_rate:.1f} %.", {"refund_rate_pct": round(refund_rate, 2)},
        ))

    if len(ordered) >= 3 and current_is_complete:
        last_three = ordered[-3:]
        revenues = [_number(item.result.get("revenue")) for item in last_three]
        if (all(_complete_month(item) for item in last_three)
                and _consecutive_months(last_three[0], last_three[1])
                and _consecutive_months(last_three[1], last_three[2])
                and all(value is not None for value in revenues)):
            if revenues[0] > revenues[1] > revenues[2]:
                signals.append(_signal(
                    "revenue_downtrend", "NOTICE", "Dreimonatiger Umsatztrend",
                    "Der Umsatz ist in drei aufeinanderfolgenden vollständigen Zeiträumen gesunken.",
                    {"periods": 3},
                ))
            elif revenues[0] < revenues[1] < revenues[2]:
                signals.append(_signal(
                    "revenue_uptrend", "INFO", "Dreimonatiger Umsatztrend",
                    "Der Umsatz ist in drei aufeinanderfolgenden vollständigen Zeiträumen gestiegen.",
                    {"periods": 3},
                ))
    return signals


def reconcile_monitoring(previous: list[MonitoringSignal], current: list[MonitoringSignal]) -> list[MonitoringSignal]:
    """Assign lifecycle states without changing the rule results themselves."""
    previous_by_fingerprint = {item.fingerprint: item for item in previous}
    current_by_fingerprint = {item.fingerprint: item for item in current}
    reconciled = []
    for signal in current:
        old = previous_by_fingerprint.get(signal.fingerprint)
        status = "ONGOING" if old and old.status in {"NEW", "ONGOING"} else "NEW"
        reconciled.append(replace(signal, status=status))
    for fingerprint, old in previous_by_fingerprint.items():
        if fingerprint not in current_by_fingerprint and old.status != "RESOLVED":
            reconciled.append(replace(old, status="RESOLVED"))
    return reconciled
