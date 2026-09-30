"""Deterministic what-if scenarios. These are explicitly not forecasts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioResult:
    label: str
    baseline: dict[str, float | None]
    scenario: dict[str, float | None]
    difference: dict[str, float | None]
    assumptions: dict[str, float]
    disclaimer: str = "Szenario, keine Prognose"


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else default
    except (TypeError, ValueError):
        return default


def calculate_scenario(
    aggregate: dict,
    *,
    revenue_change_pct: float = 0,
    cost_change_pct: float = 0,
    personnel_change: float = 0,
    marketing_change: float = 0,
) -> ScenarioResult:
    revenue_change_pct = max(-100.0, min(_finite(revenue_change_pct), 500.0))
    cost_change_pct = max(-100.0, min(_finite(cost_change_pct), 500.0))
    personnel_change = max(-10_000_000.0, min(_finite(personnel_change), 10_000_000.0))
    marketing_change = max(-10_000_000.0, min(_finite(marketing_change), 10_000_000.0))

    revenue = _finite(aggregate.get("revenue"))
    profit_available = bool(aggregate.get("profit_available"))
    profit = _finite(aggregate.get("profit")) if profit_available else None
    costs = revenue - profit if profit is not None else None
    scenario_revenue = revenue * (1 + revenue_change_pct / 100)
    scenario_costs = None
    scenario_profit = None
    scenario_margin = None
    if costs is not None:
        scenario_costs = costs * (1 + cost_change_pct / 100) + personnel_change + marketing_change
        scenario_profit = scenario_revenue - scenario_costs
        scenario_margin = scenario_profit / scenario_revenue * 100 if scenario_revenue else None
    baseline_margin = profit / revenue * 100 if profit is not None and revenue else None

    baseline = {"revenue": revenue, "costs": costs, "profit": profit, "margin": baseline_margin}
    scenario = {
        "revenue": scenario_revenue, "costs": scenario_costs,
        "profit": scenario_profit, "margin": scenario_margin,
    }
    difference = {
        key: None if baseline[key] is None or scenario[key] is None else scenario[key] - baseline[key]
        for key in baseline
    }
    assumptions = {
        "revenue_change_pct": revenue_change_pct, "cost_change_pct": cost_change_pct,
        "personnel_change": personnel_change, "marketing_change": marketing_change,
    }
    return ScenarioResult("Benutzerdefiniertes Szenario", baseline, scenario, difference, assumptions)
