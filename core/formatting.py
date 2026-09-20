"""Zentrale, rein darstellende Formatierung fuer DataDeck."""

import datetime
import math


def format_de_number(value, decimals: int = 2) -> str:
    """Formatiert Zahlen mit deutschem Dezimal- und Tausendertrennzeichen."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_compact_number(value, decimals: int = 2) -> str:
    """Kuerzt grosse Werte fuer KPI-Karten, ohne kleine Werte zu runden."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"

    absolute = abs(number)
    if absolute >= 1_000_000_000:
        return f"{format_de_number(number / 1_000_000_000, decimals)} Mrd."
    if absolute >= 1_000_000:
        return f"{format_de_number(number / 1_000_000, decimals)} Mio."
    return format_de_number(number, 0)


def format_de_date(value) -> str:
    """Formatiert Datumswerte nutzerfreundlich; ungueltige Werte bleiben leer."""
    if value in (None, ""):
        return "—"
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return value.strftime("%d.%m.%Y")
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value)
    return parsed.strftime("%d.%m.%Y")
