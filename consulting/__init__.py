"""Consultant workspace domain for privacy-preserving recurring analyses."""

from .analysis import (
    available_comparisons, compare_snapshots, detect_trends, find_best_comparison,
    internal_benchmarks, moving_average, year_to_date_comparison,
)
from .models import AnalysisSnapshot, Client

__all__ = [
    "AnalysisSnapshot", "Client", "compare_snapshots", "detect_trends",
    "find_best_comparison", "internal_benchmarks", "available_comparisons",
    "moving_average", "year_to_date_comparison",
]
