"""Provider-neutral records for the consultant workspace."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Client:
    client_id: str
    owner_user_id: str
    name: str
    internal_reference: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


@dataclass(frozen=True)
class AnalysisSnapshot:
    analysis_id: str
    owner_user_id: str
    client_id: str
    dataset_hash: str
    period_start: dt.date
    period_end: dt.date
    mapping: dict[str, Any]
    result: dict[str, Any]
    quality_status: str
    insights: list[dict[str, Any]] = field(default_factory=list)
    executive_summary: str = ""
    consultant_comment: str = ""
    analysis_version: str = "1"
    analysis_engine_version: str = "1"
    analysis_schema_version: int = 1
    uploaded_at: dt.datetime | None = None


@dataclass(frozen=True)
class ReportSettings:
    show_summary: bool = True
    show_kpis: bool = True
    show_segments: bool = True
    show_time_series: bool = True
    show_ai_insights: bool = True
    show_methodology: bool = True
    company_name: str = ""
    accent_color: str = "#6C63FF"
    contact_name: str = ""
    contact_email: str = ""
    footer_text: str = ""


@dataclass(frozen=True)
class ReportMetadata:
    report_id: str
    owner_user_id: str
    client_id: str
    analysis_id: str
    report_version: int
    settings: dict[str, Any]
    report_hash: str | None = None
    created_at: dt.datetime | None = None
