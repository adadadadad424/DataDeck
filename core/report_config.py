"""Validation helpers for consultant-controlled report presentation."""

from __future__ import annotations

import base64
import re


DEFAULT_ACCENT = "#4F46E5"


def validate_accent_color(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", candidate):
        return DEFAULT_ACCENT
    red, green, blue = (int(candidate[index:index + 2], 16) for index in (1, 3, 5))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    if luminance < 0.18 or luminance > 0.88:
        return DEFAULT_ACCENT
    return candidate


def validated_logo_data_uri(content: bytes | None, max_bytes: int = 1_000_000) -> str | None:
    if not content:
        return None
    if len(content) > max_bytes:
        raise ValueError("Logo darf maximal 1 MB groß sein")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise ValueError("Logo muss eine echte PNG- oder JPEG-Datei sein")
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def normalize_report_settings(settings: dict | None) -> dict:
    source = settings or {}
    return {
        "show_summary": bool(source.get("show_summary", True)),
        "show_kpis": bool(source.get("show_kpis", True)),
        "show_segments": bool(source.get("show_segments", True)),
        "show_time_series": bool(source.get("show_time_series", True)),
        "show_ai_insights": bool(source.get("show_ai_insights", True)),
        "show_methodology": bool(source.get("show_methodology", True)),
        "company_name": str(source.get("company_name", "")).strip()[:160],
        "accent_color": validate_accent_color(source.get("accent_color")),
        "contact_name": str(source.get("contact_name", "")).strip()[:120],
        "contact_email": str(source.get("contact_email", "")).strip()[:200],
        "footer_text": str(source.get("footer_text", "")).strip()[:300],
    }
