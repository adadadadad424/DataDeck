"""Validation helpers for consultant-controlled report presentation."""

from __future__ import annotations

import base64
import io
import re
import warnings

from PIL import Image, UnidentifiedImageError

from .report_language import normalize_report_language


DEFAULT_ACCENT = "#4F46E5"
PPT_DECK_STYLES = {"full", "short"}
PPT_AUDIENCES = {"management", "finance", "growth"}


def normalize_ppt_deck_style(value: str | None) -> str:
    candidate = str(value or "full").strip().lower()
    return candidate if candidate in PPT_DECK_STYLES else "full"


def normalize_ppt_audience(value: str | None) -> str:
    candidate = str(value or "management").strip().lower()
    return candidate if candidate in PPT_AUDIENCES else "management"


def validate_accent_color(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", candidate):
        return DEFAULT_ACCENT
    red, green, blue = (int(candidate[index:index + 2], 16) for index in (1, 3, 5))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    if luminance < 0.18 or luminance > 0.88:
        return DEFAULT_ACCENT
    return candidate


def validated_logo_data_uri(
    content: bytes | None,
    max_bytes: int = 1_000_000,
    max_dimension: int = 4_096,
    max_pixels: int = 10_000_000,
) -> str | None:
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
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                if width < 1 or height < 1 or width > max_dimension or height > max_dimension:
                    raise ValueError(f"Logo darf maximal {max_dimension} x {max_dimension} Pixel groß sein")
                if width * height > max_pixels:
                    raise ValueError("Logo überschreitet das sichere Pixellimit")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                sanitized = image.convert("RGBA" if mime == "image/png" else "RGB")
                output = io.BytesIO()
                sanitized.save(
                    output,
                    format="PNG" if mime == "image/png" else "JPEG",
                    optimize=True,
                )
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError("Logo ist beschädigt oder kein unterstütztes Bild") from error
    safe_content = output.getvalue()
    return f"data:{mime};base64,{base64.b64encode(safe_content).decode('ascii')}"


def validated_logo_bytes(content: bytes | None) -> bytes | None:
    """Return decoded, sanitized image bytes for non-HTML report formats."""
    data_uri = validated_logo_data_uri(content)
    if data_uri is None:
        return None
    return base64.b64decode(data_uri.split(",", 1)[1])


def normalize_report_settings(settings: dict | None) -> dict:
    source = settings or {}
    return {
        "show_summary": bool(source.get("show_summary", True)),
        "show_kpis": bool(source.get("show_kpis", True)),
        "show_segments": bool(source.get("show_segments", True)),
        "show_time_series": bool(source.get("show_time_series", True)),
        "show_ai_insights": bool(source.get("show_ai_insights", True)),
        "show_methodology": bool(source.get("show_methodology", True)),
        "language": normalize_report_language(source.get("language")),
        "ppt_deck_style": normalize_ppt_deck_style(source.get("ppt_deck_style")),
        "ppt_audience": normalize_ppt_audience(source.get("ppt_audience")),
        "ppt_speaker_notes": bool(source.get("ppt_speaker_notes", False)),
        "company_name": str(source.get("company_name", "")).strip()[:160],
        "client_name": str(source.get("client_name", "")).strip()[:160],
        "accent_color": validate_accent_color(source.get("accent_color")),
        "contact_name": str(source.get("contact_name", "")).strip()[:120],
        "contact_email": str(source.get("contact_email", "")).strip()[:200],
        "footer_text": str(source.get("footer_text", "")).strip()[:300],
    }
