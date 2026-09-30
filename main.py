"""
DataDeck - Streamlit-Einstiegspunkt.

KI-gestützte Unternehmensanalyse für Unternehmensberater und
Beratungskanzleien: Finanzdaten hochladen, automatisch bereinigen und
aggregieren, KI-gestützte Interpretation, PDF-Strategiebericht.

main.py orchestriert ausschließlich UI, Session State und den Ablauf.
Jegliche Business-Logik lebt in core/ (unverändert gegenüber der
vorherigen QA-Runde, 53/54 -> nach Bugfix 54/54 - siehe qa_test_final.py):
    core.data_processing  - Datei laden, bereinigen, Spalten erkennen
    core.analysis          - Umsatz/Gewinn/Marge/Top-Flop, Filter (Wahrheit)
    core.security           - PII-Erkennung/-Maskierung, Prompt-Sanitizing
    core.ai_insights        - Gemini-Interpretation der bereits berechneten Fakten
    core.report_builder      - PDF-Erstellung aus denselben Fakten
    core.theme               - zentrales Design-System (Light/Dark-Tokens)

Die App bleibt bewusst eine gefuehrte Einzelseiten-Ansicht. Stripe-Billing
ist als standardmaessig deaktivierte, serverseitige Infrastruktur in
billing/ vorbereitet; Aktivierung und Testbetrieb sind in BILLING.md
dokumentiert. Mandantenhistorie speichert ausschließlich aggregierte Ergebnisse.
"""

import datetime
import hashlib
import logging
import math
import os
import time
import uuid
from contextlib import nullcontext

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from billing.config import BillingConfig, billing_enabled
from billing.entitlements import entitlement_for, premium_feature_access
from billing.models import Identity, stable_user_id
from billing.service import BillingService
from consulting.analysis import compare_snapshots, detect_trends, find_best_comparison
from consulting.monitoring import evaluate_monitoring
from consulting.models import AnalysisSnapshot
from consulting.scenario import calculate_scenario
from consulting.serialization import aggregate_result
from consulting.store import PostgresConsultingStore

from core.ai_insights import (
    AIConfigError,
    AIInsightError,
    AIRateLimitError,
    generate_ai_summary,
    generate_local_summary,
)
from core.analysis import calculate_kpis, filter_data
from core.data_processing import (
    assess_data_quality,
    clean_and_prepare_data,
    inspect_file_structure,
    load_and_validate_file,
)
from core.formatting import format_compact_number, format_de_date, format_de_number
from core.report_builder import generate_pdf
from core.presentation_builder import generate_pptx
from core.demo_data import DEMO_SEGMENTS, demo_financials
from core.report_config import validated_logo_data_uri
from core.report_language import normalize_report_language, report_language_name
from core.trust_center import SUBPROCESSORS, TRUST_SECTIONS, generate_security_whitepaper
from core.security import escape_html, mask_pii, scan_dataframe_for_pii
from core.security_controls import (
    SecurityLimitError,
    enforce_rate_limit,
    guarded_operation,
    sanitize_log_value,
)
from core.theme import DEFAULT_THEME, get_theme, inject_theme_css, plotly_layout_colors
from core.runtime_security import (
    APP_VERSION,
    action_allowed,
    anonymized_user_id,
    app_environment,
    auth_required,
    clear_sensitive_session,
    dataset_hash,
    is_approved_user,
    new_correlation_id,
    oidc_claims_expired,
    production_config_errors,
    safe_exception_name,
)

REPORT_EXPORT_CONTEXT_VERSION = "report-export-2026-09-keynote-safe-pptx"
PREVIEW_MAX_ROWS = 50
LARGE_XLSX_HINT_BYTES = 5 * 1024 * 1024


def _uncached_decorator(*args, **kwargs):
    del args, kwargs

    def decorate(function):
        return function

    return decorate


_cache_resource = getattr(st, "cache_resource", _uncached_decorator)
_cache_data = getattr(st, "cache_data", _uncached_decorator)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DataDeck")
logging.getLogger("weasyprint").setLevel(logging.WARNING)
logging.getLogger("fontTools").setLevel(logging.WARNING)

if app_environment() != "production":
    load_dotenv(override=False)

st.set_page_config(page_title="DataDeck", page_icon="◆", layout="wide")

NISCHEN = [
    "SaaS / Micro-SaaS",
    "Gastronomie / Café",
    "E-Commerce / Online-Shop",
    "KFZ-Betrieb / Werkstatt",
    "Allgemein / Sonstige",
]

def _build_consulting_demo_data() -> dict:
    services = [
        ("Executive Coaching", "Führungskräfte", "DACH", 4200, 0.43),
        ("Bewerbungsstrategie", "Berufseinsteiger", "DACH", 1800, 0.52),
        ("LinkedIn Profil", "Fachkräfte", "Remote", 950, 0.46),
        ("Assessment Training", "Career Change", "NRW", 2400, 0.55),
    ]
    rows = []
    for month_index, month in enumerate(pd.date_range("2025-10-01", periods=24, freq="MS")):
        growth = 1 + month_index * 0.035
        september_pressure = 0.08 if month.month == 9 else 0.0
        for service_index, (service, segment, region, base_revenue, cost_ratio) in enumerate(services):
            seasonal = 1 + ((month.month % 4) - 1.5) * 0.025
            revenue = round(base_revenue * growth * seasonal * (1 + service_index * 0.015), 2)
            costs = round(revenue * (cost_ratio + september_pressure + service_index * 0.01), 2)
            rows.append({
                "Datum": month,
                "Leistung": service,
                "Segment": segment,
                "Region": region,
                "Umsatz": revenue,
                "Kosten": costs,
                "Kunden-E-Mail": f"demo-kunde-{len(rows) + 1:03d}@example.com",
            })
    return {key: [row[key] for row in rows] for key in rows[0]}


DEMO_DATA = _build_consulting_demo_data()


def _start_demo_analysis(is_premium: bool) -> None:
    _reset_filters()
    _reset_data_caches()
    _reset_import_review()
    st.session_state.raw_df = pd.DataFrame(DEMO_DATA)
    st.session_state.data_source = "demo"
    st.session_state.data_signature = f"consulting_demo_{is_premium}"
    st.session_state.dataset_fingerprint = hashlib.sha256(b"datadeck-consulting-demo-v2").hexdigest()
    st.session_state.column_mapping = {}
    st.session_state.revenue_only_mode = False
    st.session_state.upload_truncated = False
    st.session_state.upload_max_rows = None
    st.session_state.performance_flow_started = time.perf_counter()
    st.session_state.performance_total_key = None
    _reset_analysis_outputs()


@_cache_resource(show_spinner=False)
def _consulting_store(database_url: str) -> PostgresConsultingStore:
    return PostgresConsultingStore(database_url)


@_cache_data(ttl=20, show_spinner=False)
def _consulting_clients(database_url: str, owner_user_id: str, cache_version: int):
    del cache_version
    return _consulting_store(database_url).list_clients(owner_user_id)


@_cache_data(ttl=20, show_spinner=False)
def _consulting_history(
    database_url: str, owner_user_id: str, client_id: str, cache_version: int,
):
    del cache_version
    return _consulting_store(database_url).list_analyses(owner_user_id, client_id)


def _init_session_state() -> None:
    defaults = {
        "theme": DEFAULT_THEME,
        "raw_df": None,
        "data_source": None,
        "data_signature": None,
        "last_upload_signature": None,
        "pending_upload_hash": None,
        "ai_insights": None,
        "ai_insights_key": None,
        "ai_insights_source": None,
        "ai_insights_created_at": None,
        "pdf_bytes": None,
        "pdf_filename": None,
        "pdf_context_key": None,
        "pptx_bytes": None,
        "pptx_filename": None,
        "pptx_context_key": None,
        "revenue_only_mode": False,
        "column_mapping": {},
        "correlation_id": new_correlation_id(),
        "user_id_hash": "local-dev",
        "security_session_id": uuid.uuid4().hex,
        "ai_in_progress": False,
        "pdf_in_progress": False,
        "pptx_in_progress": False,
        "last_ai_started": None,
        "last_pdf_started": None,
        "last_ai_context": None,
        "last_pdf_context": None,
        "auth_audit_subject": None,
        "auth_denied_logged": False,
        "billing_checkout_url": None,
        "billing_return_synced": False,
        "pii_cache_key": None,
        "pii_scan_cache": None,
        "prepared_cache_key": None,
        "prepared_df_cache": None,
        "prepared_warnings_cache": None,
        "prepared_quality_cache": None,
        "kpi_cache_key": None,
        "kpi_cache": None,
        "import_review_signature": None,
        "import_inspection": None,
        "upload_truncated": False,
        "upload_max_rows": None,
        "import_cache_key": None,
        "import_cache_df": None,
        "import_cache_truncated": False,
        "import_cache_max_rows": None,
        "consultant_comment": "",
        "report_settings": {
            "show_summary": True, "show_kpis": True, "show_segments": True,
            "show_time_series": True, "show_ai_insights": True, "show_methodology": True,
            "company_name": "", "client_name": "", "accent_color": "#4F46E5", "contact_name": "",
            "contact_email": "", "footer_text": "", "language": "de",
            "ppt_deck_style": "full", "ppt_audience": "management", "ppt_speaker_notes": False,
        },
        "report_logo_bytes": None,
        "report_version": 1,
        "dataset_fingerprint": None,
        "consulting_cache_version": 0,
        "saved_analysis_id": None,
        "saved_analysis_client_id": None,
        "workspace_audit_logged": False,
        "audit_dataset_fingerprint": None,
        "last_report_id": None,
        "performance_timings": {},
        "performance_flow_started": None,
        "performance_total_key": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _log_event(event: str, level: int = logging.INFO, **fields) -> None:
    safe_fields = " ".join(
        f"{sanitize_log_value(key, 40)}={sanitize_log_value(value)}"
        for key, value in sorted(fields.items())
    )
    logger.log(
        level,
        "%s correlation_id=%s user_id=%s%s",
        event,
        st.session_state.get("correlation_id", "startup"),
        st.session_state.get("user_id_hash", "anonymous"),
        f" {safe_fields}" if safe_fields else "",
    )


def _record_performance_timing(stage: str, started: float, **fields) -> int:
    """Store only numeric timings in the current isolated Streamlit session."""
    duration_ms = max(0, round((time.perf_counter() - started) * 1000))
    timings = dict(st.session_state.get("performance_timings") or {})
    timings[stage] = duration_ms
    st.session_state.performance_timings = timings
    _log_event("PERFORMANCE_TIMING", stage=stage, duration_ms=duration_ms, **fields)
    return duration_ms


def _record_workspace_event(store, user_id: str, event_type: str, resource_type: str = "session",
                            resource_id: str | None = None, metadata: dict | None = None) -> None:
    if store is None:
        return
    try:
        store.record_event(user_id, event_type, resource_type, resource_id, metadata)
    except Exception as error:
        _log_event("AUDIT_WRITE_ERROR", logging.WARNING, error_type=safe_exception_name(error))


_ACTIVITY_LABELS = {
    "LOGIN": "Angemeldet",
    "CLIENT_SAVED": "Mandant gespeichert",
    "CLIENT_DELETED": "Mandant gelöscht",
    "IMPORT_COMPLETED": "Daten importiert",
    "ANALYSIS_SAVED": "Analyse gespeichert",
    "INSIGHT_GENERATED": "Einordnung erstellt",
    "INSIGHT_EDITED": "Einordnung bearbeitet",
    "REPORT_EXPORTED": "Report erstellt",
    "REPORT_APPROVED": "Report freigegeben",
    "BRANDING_CHANGED": "Report-Gestaltung geändert",
    "MONITORING_UPDATED": "Monitoring aktualisiert",
    "WORKSPACE_CREATED": "Workspace erstellt",
    "MEMBER_ROLE_CHANGED": "Mitgliedsrolle geändert",
}


def _operation_guard(action: str):
    return guarded_operation(
        action,
        st.session_state.get("user_id_hash", "anonymous"),
        session_id=st.session_state.get("security_session_id"),
    )


def _show_security_limit(action: str, error: SecurityLimitError) -> None:
    _log_event("RATE_LIMITED", logging.WARNING, action=action, retry_after=error.retry_after)
    st.warning("Dieser Vorgang wurde zu häufig gestartet. Bitte warten Sie kurz und versuchen Sie es erneut.")


def _show_unexpected_error(step: str) -> None:
    error_id = st.session_state.get("correlation_id") or new_correlation_id()
    st.error(
        "Die Analyse konnte nicht abgeschlossen werden. Die hochgeladene Datei "
        f"wurde nicht verändert. Bitte versuchen Sie es erneut. Fehler-ID: {error_id}"
    )
    _log_event("UNEXPECTED_ERROR", logging.ERROR, step=step)


def _render_public_beta_page() -> bool:
    """Render public beta notices without requiring an authenticated session."""
    query_params = getattr(st, "query_params", {})
    page = str(query_params.get("page", "")).strip().casefold()
    if page not in {"impressum", "datenschutz", "nutzungsbedingungen", "feedback", "demo", "trust"}:
        return False

    st.markdown('<div class="dd-eyebrow">DATADECK BETA</div>', unsafe_allow_html=True)
    if page == "demo":
        st.title("Nordstern GmbH")
        st.caption("Beispielanalyse · synthetische Daten · Werte in T€")
        segment = st.segmented_control(
            "Segment", list(DEMO_SEGMENTS), default="Gesamt", key="public_demo_segment",
        )
        periods = st.slider("Zeitraum", 3, 12, 12, key="public_demo_periods")
        visible = demo_financials(segment or "Gesamt", periods)
        revenue = visible["Umsatz"].sum()
        costs = visible["Kosten"].sum()
        profit = revenue - costs
        margin = profit / revenue * 100 if revenue else None
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Umsatz", f"{revenue:,.0f} T€".replace(",", "."))
        c2.metric("Kosten", f"{costs:,.0f} T€".replace(",", "."))
        c3.metric("Gewinn", f"{profit:,.0f} T€".replace(",", "."))
        c4.metric("Marge", f"{margin:.1f} %".replace(".", ",") if margin is not None else "–")
        st.line_chart(visible.set_index("Monat")[["Umsatz", "Gewinn"]])
        latest_change = (visible["Umsatz"].iloc[-1] / visible["Umsatz"].iloc[-2] - 1) * 100
        with st.expander("Einordnung", expanded=True):
            st.write(
                f"Der Umsatz im jüngsten Monat liegt {latest_change:+.1f} % gegenüber dem Vormonat. "
                f"Im ausgewählten Zeitraum ergibt sich eine berechnete Marge von {margin:.1f} %."
            )
            st.caption("Regelbasierte Einordnung der Beispielzahlen. Keine externe KI-Abfrage.")
        with st.expander("Report-Vorschau"):
            st.subheader(f"Nordstern GmbH · {segment or 'Gesamt'}")
            st.write(f"Umsatz {revenue:,.0f} T€ · Kosten {costs:,.0f} T€ · Gewinn {profit:,.0f} T€")
            st.write(f"Die Marge beträgt {margin:.1f} %. Die letzte Monatsveränderung liegt bei {latest_change:+.1f} %.")
            st.caption("Vorschau auf einen Beraterbericht mit Kennzahlen, Zeitverlauf und Methodik.")
        st.link_button("Eigene Daten testen", "/", width="stretch")
    elif page == "trust":
        st.title("Trust Center")
        st.write("Technische Transparenz für die aktuelle DataDeck-Beta.")
        for title, description in TRUST_SECTIONS:
            st.subheader(title)
            st.write(description)
        st.subheader("Dienstleister")
        st.dataframe(pd.DataFrame(SUBPROCESSORS, columns=["Dienst", "Zweck", "Hinweis"]), hide_index=True)
        st.warning("Keine ISO-, SOC-2- oder DSGVO-Zertifizierung. Automatische Mustererkennung ersetzt keine Rechtsprüfung.")
        if st.button("Security Whitepaper erstellen", key="trust_whitepaper_btn"):
            st.session_state.trust_whitepaper = generate_security_whitepaper()
        if st.session_state.get("trust_whitepaper"):
            st.download_button("Security Whitepaper herunterladen", st.session_state.trust_whitepaper,
                               "DataDeck_Security_Whitepaper.pdf", "application/pdf")
    elif page == "impressum":
        st.title("Impressum")
        st.info(
            "DataDeck befindet sich in einer geschlossenen technischen Beta. "
            "Die vollständigen Betreiberangaben werden vor einer öffentlichen "
            "Veröffentlichung ergänzt. Dies ist noch kein öffentliches Angebot."
        )
    elif page == "datenschutz":
        st.title("Datenschutzhinweise zur geschlossenen Beta")
        st.write(
            "Hochgeladene CSV- und XLSX-Dateien werden ausschließlich für die "
            "angeforderte Analyse in der aktuellen Sitzung verarbeitet. An Gemini "
            "werden nur berechnete und aggregierte Kennzahlen übertragen, niemals "
            "die vollständigen Rohdaten des Uploads."
        )
        st.write(
            "Für die Zugangskontrolle verarbeitet DataDeck die E-Mail-Adresse des "
            "angemeldeten Google-Kontos. Die Anwendung wird für diese Beta auf "
            "Render betrieben; KI-Interpretationen werden über Google Gemini erzeugt."
        )
        st.warning(
            "Vor einer öffentlichen Veröffentlichung wird dieser technische Hinweis "
            "durch die finale Datenschutzerklärung des Betreibers ersetzt."
        )
    elif page == "nutzungsbedingungen":
        st.title("Nutzungsbedingungen der geschlossenen Beta")
        st.write(
            "Der Zugang ist ausschließlich für eingeladene Testpersonen bestimmt. "
            "DataDeck ist eine Vorabversion; Analyseergebnisse und PDF-Berichte müssen "
            "vor einer geschäftlichen Weiterverwendung fachlich geprüft werden."
        )
        st.warning(
            "Verbindliche Nutzungsbedingungen werden vor einer öffentlichen "
            "Veröffentlichung durch den Betreiber bereitgestellt."
        )
    else:
        st.title("Beta-Feedback")
        st.write("Für das Testgespräch helfen insbesondere diese Punkte:")
        st.markdown(
            "- War Upload und Spaltenzuordnung verständlich?\n"
            "- Stimmen die berechneten Kennzahlen mit Ihrer Erwartung überein?\n"
            "- Waren KI-Einordnung und PDF-Bericht hilfreich?\n"
            "- Was war unklar, und welche Analyse hat gefehlt?"
        )
        st.info(
            "Es werden auf dieser Seite keine Datensätze oder Nachrichten automatisch "
            "übertragen. Feedback wird im vereinbarten Beta-Testgespräch aufgenommen."
        )

    if st.button("Zurück zu DataDeck", type="primary", key=f"public_back_{page}"):
        query_params.clear()
        st.rerun()
    st.caption("Vorläufiger Hinweis für die geschlossene Beta, keine Rechtsberatung.")
    return True


def _auth_gate() -> dict | None:
    errors = production_config_errors()
    if errors:
        st.error("Die Produktionskonfiguration ist unvollständig. Der Zugriff bleibt gesperrt.")
        logger.error("PRODUCTION_CONFIG_REFUSED issue_count=%s", len(errors))
        return None

    if not auth_required():
        st.session_state.user_id_hash = "local-dev"
        return {
            "subject": "local-dev",
            "issuer": "https://local.datadeck.invalid",
            "email": "local@datadeck.invalid",
        }

    try:
        logged_in = bool(getattr(st.user, "is_logged_in", False))
    except Exception:
        logged_in = False

    if not logged_in:
        st.markdown('<div class="dd-eyebrow">INVITE-ONLY BETA</div>', unsafe_allow_html=True)
        st.title("DataDeck Beta")
        st.write("Melden Sie sich mit dem für die Beta freigegebenen Konto an.")
        nav1, nav2 = st.columns(2)
        with nav1:
            st.link_button("Demo ansehen", "?page=demo", width="stretch")
        with nav2:
            st.link_button("Trust Center", "?page=trust", width="stretch")
        if st.button("Sicher anmelden", type="primary", key="login_btn"):
            try:
                enforce_rate_limit(
                    "login",
                    "anonymous",
                    session_id=st.session_state.get("security_session_id"),
                )
                st.login()
            except SecurityLimitError as error:
                _show_security_limit("login", error)
            except Exception as error:
                _log_event("AUTH_LOGIN_ERROR", logging.ERROR, error_type=safe_exception_name(error))
                st.error("Die Anmeldung ist momentan nicht verfügbar. Bitte kontaktieren Sie den Beta-Support.")
        return None

    claims = dict(st.user)
    if oidc_claims_expired(claims):
        clear_sensitive_session(st.session_state)
        st.warning("Ihre Anmeldung ist abgelaufen. Bitte melden Sie sich erneut an.")
        st.logout()
        return None
    email = claims.get("email") or claims.get("preferred_username")
    subject = claims.get("sub") or claims.get("oid")
    authenticated_hash = anonymized_user_id(subject, email)
    previous_hash = st.session_state.get("auth_audit_subject")
    if previous_hash and previous_hash != authenticated_hash:
        clear_sensitive_session(st.session_state)
        _init_session_state()
        st.session_state.security_session_id = uuid.uuid4().hex
        st.session_state.correlation_id = new_correlation_id()
        _log_event("SESSION_IDENTITY_CHANGED", logging.WARNING)
    st.session_state.user_id_hash = authenticated_hash
    if claims.get("email_verified") is False or not is_approved_user(email):
        if not st.session_state.get("auth_denied_logged"):
            _log_event("LOGIN_DENIED", logging.WARNING)
            st.session_state.auth_denied_logged = True
        st.error("Dieses Konto ist nicht für die DataDeck-Beta freigegeben.")
        if st.button("Abmelden", key="denied_logout_btn"):
            clear_sensitive_session(st.session_state)
            st.logout()
        return None

    if st.session_state.get("auth_audit_subject") != st.session_state.user_id_hash:
        _log_event("LOGIN_SUCCESS")
        st.session_state.auth_audit_subject = st.session_state.user_id_hash
        st.session_state.auth_denied_logged = False
    issuer = claims.get("iss") or "https://accounts.google.com"
    return {"subject": subject, "issuer": issuer, "email": email}


def _billing_identity(auth_identity: dict) -> Identity:
    issuer = str(auth_identity["issuer"])
    subject = str(auth_identity["subject"])
    email = str(auth_identity["email"])
    return Identity(
        user_id=stable_user_id(issuer, subject),
        issuer=issuer,
        subject=subject,
        email=email,
        beta_access=not auth_required() or is_approved_user(email),
    )


def _billing_status_label(status: str | None, cancel_at_period_end: bool) -> str:
    if cancel_at_period_end and status in {"active", "trialing"}:
        return "Kündigung vorgemerkt"
    return {
        "active": "Aktiv",
        "trialing": "Testphase",
        "past_due": "Zahlung überfällig",
        "unpaid": "Zahlung fehlgeschlagen",
        "incomplete": "Noch nicht abgeschlossen",
        "canceled": "Beendet",
    }.get(status, "Kein Abonnement")


def _compute_insight_key(
    kpis: dict,
    ziel_marge: float | None,
    niche: str,
    is_premium: bool,
    language: str = "de",
) -> str:
    """Fingerabdruck dessen, worauf sich eine KI-Analyse bezieht. Ändert er
    sich (z.B. weil ein Filter geändert wurde), gilt die vorhandene Analyse
    als veraltet - sie bleibt sichtbar, wird aber deutlich markiert."""
    # Der Tarif beeinflusst die Texttiefe, aber nicht die Faktenbasis. Ein
    # Wechsel für den Export macht eine vorhandene Einordnung nicht veraltet.
    del is_premium
    categories = kpis["kategorien_daten"].to_json(orient="records")
    category_sig = hashlib.sha256(categories.encode("utf-8")).hexdigest()
    return "|".join([
        f"u{round(kpis['gesamt_umsatz'], 2)}", f"g{round(kpis['gesamt_gewinn'], 2)}",
        f"r{kpis['anzahl_zeilen']}", f"z{ziel_marge if ziel_marge is not None else 'na'}", f"n{niche}",
        f"l{normalize_report_language(language)}", f"c{category_sig}",
        f"a{kpis.get('financial_aggregation_available', True)}",
    ])


def _report_presentation_key() -> str:
    settings = tuple(
        sorted((str(key), str(value)) for key, value in st.session_state.report_settings.items())
    )
    logo = st.session_state.report_logo_bytes or b""
    payload = repr((REPORT_EXPORT_CONTEXT_VERSION, settings, st.session_state.consultant_comment)).encode("utf-8") + logo
    return hashlib.sha256(payload).hexdigest()


def _as_date(value, fallback: datetime.date) -> datetime.date:
    if value is None or pd.isna(value):
        return fallback
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return fallback


def _report_period_label(kpis: dict) -> str:
    date_range = kpis.get("date_range") or {}
    start, end = date_range.get("start"), date_range.get("end")
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return ""
    return f"{format_de_date(start)} bis {format_de_date(end)}"


def _monthly_chart_ticks(values, max_ticks: int = 4) -> tuple[list[pd.Timestamp], list[str]]:
    """Compact German month labels without exposing raw timestamp formatting."""
    parsed = pd.to_datetime(pd.Series(values), errors="coerce").dropna().drop_duplicates().sort_values()
    if parsed.empty:
        return [], []
    points = parsed.tolist()
    step = max(1, math.ceil(len(points) / max(2, max_ticks)))
    selected = points[::step]
    if selected[-1] != points[-1] and len(selected) < max_ticks:
        selected.append(points[-1])
    months = ("Jan", "Feb", "Mrz", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")
    return selected, [f"{months[value.month - 1]} {str(value.year)[-2:]}" for value in selected]


def _report_client_name(selected_client) -> str:
    configured = str(st.session_state.report_settings.get("client_name", "")).strip()
    if configured:
        return configured[:160]
    if selected_client is not None:
        return str(selected_client.name).strip()[:160]
    return ""


def _card_html(html_inner: str, extra_class: str = "") -> str:
    class_name = f"dd-card {extra_class}".strip()
    return f'<div class="{class_name}">{html_inner}</div>'


def _card(html_inner: str, extra_class: str = "") -> None:
    st.markdown(_card_html(html_inner, extra_class), unsafe_allow_html=True)


def _section_header(title: str, description: str = "") -> None:
    description_html = (
        f'<div class="dd-section-description">{escape_html(description)}</div>'
        if description else ""
    )
    st.markdown(
        f'<div class="dd-section-header"><h3>{escape_html(title)}</h3>{description_html}</div>',
        unsafe_allow_html=True,
    )


def _assistant_card(title: str, body: str, items: list[str] | None = None, extra_class: str = "assistant") -> None:
    item_html = ""
    if items:
        item_html = "<ol>" + "".join(f"<li>{escape_html(item)}</li>" for item in items) + "</ol>"
    _card(
        f'<div class="dd-eyebrow">ANALYSE-ASSISTENT</div>'
        f'<b>{escape_html(title)}</b><br>'
        f'<span class="dd-muted">{escape_html(body)}</span>'
        f'{item_html}',
        extra_class,
    )


def _kpi_card(
    label: str,
    value: str,
    delta_text: str = "",
    delta_kind: str = "na",
    subtext: str = "",
    exact_value: str = "",
) -> str:
    delta_cls = {"pos": "dd-kpi-delta-pos", "neg": "dd-kpi-delta-neg"}.get(delta_kind, "dd-kpi-delta-na")
    delta_html = f'<div class="{delta_cls}">{delta_text}</div>' if delta_text else ""
    subtext_html = f'<div class="dd-kpi-reason">{escape_html(subtext) if subtext else "&nbsp;"}</div>'
    value_title = f' title="{escape_html(exact_value)}"' if exact_value else ""
    return (
        f'<div class="dd-card" style="margin-bottom:0;">'
        f'<div class="dd-kpi-label">{label}</div>'
        f'<div class="dd-kpi-value"{value_title}>{value}</div>{delta_html}{subtext_html}</div>'
    )


def _data_preview_table(df: pd.DataFrame, max_rows: int = PREVIEW_MAX_ROWS) -> str:
    bounded_rows = max(1, min(int(max_rows), PREVIEW_MAX_ROWS))
    preview = df.head(bounded_rows)
    headers = "".join(f"<th>{escape_html(col)}</th>" for col in preview.columns)
    rows = []
    for _, row in preview.iterrows():
        display_values = []
        for value in row.tolist():
            if pd.isna(value):
                display_values.append("–")
            elif isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
                display_values.append(format_de_date(value))
            elif isinstance(value, str):
                display_values.append(escape_html(mask_pii(value[:500])))
            else:
                display_values.append(escape_html(value))
        cells = "".join(f"<td>{value}</td>" for value in display_values)
        rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="dd-table-wrap">'
        '<table class="dd-table">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def _reset_filters() -> None:
    for key in ("min_gain_filter", "min_margin_filter", "category_filter"):
        st.session_state.pop(key, None)


def _active_filter_values(df_clean: pd.DataFrame, warnings: dict) -> tuple[float, float, str]:
    """Read persisted filter widgets before their collapsed UI is rendered."""
    search = str(st.session_state.get("category_filter", ""))
    if warnings.get("revenue_only_mode"):
        return 0.0, 0.0, search

    lowest_gain = math.floor(min(0.0, float(df_clean["Gewinn_Clean"].min())))
    highest_gain = math.ceil(max(1.0, float(df_clean["Gewinn_Clean"].max())))
    gain = float(st.session_state.get("min_gain_filter", lowest_gain))
    margin = float(st.session_state.get("min_margin_filter", 0))
    return min(max(gain, lowest_gain), highest_gain), min(max(margin, 0), 100), search


def _render_advanced_options(
    df_clean: pd.DataFrame,
    df_filtered: pd.DataFrame,
    warnings: dict,
    kpis: dict,
    financial_available: bool,
) -> None:
    """Keep optional analysis controls in one quiet, predictable place."""
    with st.expander("Erweiterte Optionen", expanded=False):
        st.markdown("**Filter**")
        with st.form("filter_form"):
            if warnings.get("revenue_only_mode"):
                st.text_input(
                    "Kategorie durchsuchen",
                    value=str(st.session_state.get("category_filter", "")),
                    placeholder="z. B. Premium",
                    key="category_filter",
                )
                st.caption("Gewinn- und Margenfilter benötigen eine Gewinn- oder Kostenspalte.")
            else:
                lowest_gain = math.floor(min(0.0, float(df_clean["Gewinn_Clean"].min())))
                highest_gain = math.ceil(max(1.0, float(df_clean["Gewinn_Clean"].max())))
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    st.slider(
                        "Mindest-Gewinn (€)", lowest_gain, highest_gain,
                        int(min(max(st.session_state.get("min_gain_filter", lowest_gain), lowest_gain), highest_gain)),
                        key="min_gain_filter",
                    )
                with fc2:
                    st.slider(
                        "Mindest-Marge (%)", 0, 100,
                        int(min(max(st.session_state.get("min_margin_filter", 0), 0), 100)),
                        key="min_margin_filter",
                    )
                with fc3:
                    st.text_input(
                        "Kategorie durchsuchen",
                        value=str(st.session_state.get("category_filter", "")),
                        placeholder="z. B. Premium",
                        key="category_filter",
                    )
            st.form_submit_button("Filter anwenden", width="stretch")

        st.divider()
        st.markdown("**Szenario**")
        st.caption("Mathematische Variante der aktuellen Kennzahlen, keine Prognose.")
        if not financial_available:
            st.info("Szenarien benötigen Beträge in einer einheitlichen Währung.")
        else:
            sc1, sc2 = st.columns(2)
            with sc1:
                scenario_revenue = st.number_input(
                    "Umsatzänderung (%)", -100.0, 500.0, 0.0, 1.0, key="scenario_revenue",
                )
                scenario_personnel = st.number_input(
                    "Personaländerung (€)", -10_000_000.0, 10_000_000.0, 0.0, 1000.0,
                    key="scenario_personnel",
                )
            with sc2:
                scenario_cost = st.number_input(
                    "Kostenänderung (%)", -100.0, 500.0, 0.0, 1.0, key="scenario_cost",
                )
                scenario_marketing = st.number_input(
                    "Marketingänderung (€)", -10_000_000.0, 10_000_000.0, 0.0, 1000.0,
                    key="scenario_marketing",
                )
            scenario = calculate_scenario(
                aggregate_result(kpis), revenue_change_pct=scenario_revenue,
                cost_change_pct=scenario_cost, personnel_change=scenario_personnel,
                marketing_change=scenario_marketing,
            )

            def scenario_row(label: str, values: dict) -> dict:
                return {
                    "Stand": label,
                    "Umsatz": "—" if values["revenue"] is None else f"{format_de_number(values['revenue'])} €",
                    "Kosten": "—" if values["costs"] is None else f"{format_de_number(values['costs'])} €",
                    "Gewinn": "—" if values["profit"] is None else f"{format_de_number(values['profit'])} €",
                    "Marge": "—" if values["margin"] is None else f"{format_de_number(values['margin'], 1)} {'Pkt.' if label == 'Differenz' else '%'}",
                }

            scenario_table = pd.DataFrame([
                scenario_row("Ausgangswert", scenario.baseline),
                scenario_row("Szenario", scenario.scenario),
                scenario_row("Differenz", scenario.difference),
            ])
            st.markdown(_data_preview_table(scenario_table, max_rows=3), unsafe_allow_html=True)

        st.divider()
        st.markdown("**Datenvorschau**")
        st.caption(f"Maskierte Vorschau der ersten {PREVIEW_MAX_ROWS} gefilterten Datensätze.")
        st.markdown(_data_preview_table(df_filtered), unsafe_allow_html=True)
        if len(df_filtered) > PREVIEW_MAX_ROWS:
            st.caption("Weitere Datensätze bleiben Teil der Analyse.")


def _reset_analysis_outputs() -> None:
    st.session_state.ai_insights = None
    st.session_state.ai_insights_key = None
    st.session_state.ai_insights_source = None
    st.session_state.ai_insights_created_at = None
    st.session_state.pdf_bytes = None
    st.session_state.pdf_filename = None
    st.session_state.pdf_context_key = None
    st.session_state.pptx_bytes = None
    st.session_state.pptx_filename = None
    st.session_state.pptx_context_key = None
    st.session_state.consultant_comment = ""
    st.session_state.saved_analysis_id = None
    st.session_state.saved_analysis_client_id = None
    st.session_state.report_version = 1


def _reset_data_caches() -> None:
    """Remove cached derivatives whenever the active dataset is replaced."""
    for key in (
        "pii_cache_key", "pii_scan_cache", "prepared_cache_key",
        "prepared_df_cache", "prepared_warnings_cache", "prepared_quality_cache",
        "kpi_cache_key", "kpi_cache",
    ):
        st.session_state[key] = None
    st.session_state.performance_timings = {}
    st.session_state.performance_flow_started = None
    st.session_state.performance_total_key = None


def _reset_import_review() -> None:
    st.session_state.import_review_signature = None
    st.session_state.import_inspection = None
    st.session_state.upload_truncated = False
    st.session_state.upload_max_rows = None
    st.session_state.pending_upload_hash = None


def _effective_column_mapping() -> dict | None:
    mapping = st.session_state.get("column_mapping") or {}
    normalized = {}
    for key, value in mapping.items():
        if value in (None, "", "__auto__"):
            continue
        if value == "__none__" and key not in {"gewinn", "kosten", "kategorie", "datum"}:
            continue
        normalized[key] = value
    return normalized or None


def _stable_mapping_key(mapping: dict | None) -> tuple[tuple[str, str], ...]:
    """Create a deterministic, hashable key for one column mapping."""
    return tuple(sorted((str(key), str(value)) for key, value in (mapping or {}).items()))


def _mapping_option_label(value) -> str:
    labels = {
        "__auto__": "Automatisch erkennen",
        "__none__": "Keine Spalte",
    }
    return labels.get(value, str(value))


def _option_index(options: list, selected) -> int:
    for index, option in enumerate(options):
        if option == selected:
            return index
    return 0


def _mapping_requires_review(warnings: dict | None) -> bool:
    confidence = (warnings or {}).get("mapping_confidence", {})
    uncertain = {"mittel", "niedrig", "nicht_verfuegbar"}
    core_uncertain = any(confidence.get(role) in uncertain for role in ("umsatz", "kategorie"))
    no_reliable_profit_basis = (
        confidence.get("gewinn") in uncertain and confidence.get("kosten") in uncertain
    )
    return core_uncertain or no_reliable_profit_basis


def _top_categories_with_other(category_data: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    """Begrenzt unruhige Diagramme, ohne den Rest der Daten zu verschweigen."""
    sorted_data = category_data.sort_values("Umsatz_Clean", ascending=False).copy()
    if len(sorted_data) <= limit:
        return sorted_data
    top = sorted_data.head(limit).copy()
    remainder = sorted_data.iloc[limit:]
    other_revenue = float(remainder["Umsatz_Clean"].sum())
    other_profit = float(remainder["Gewinn_Clean"].sum(min_count=1))
    other_margin = (
        other_profit / other_revenue * 100
        if other_revenue and other_profit == other_profit else float("nan")
    )
    other = pd.DataFrame([{
        "Kategorie_Clean": "Weitere",
        "Umsatz_Clean": other_revenue,
        "Gewinn_Clean": other_profit,
        "Datensaetze": int(remainder["Datensaetze"].sum()),
        "Marge": other_margin,
    }])
    return pd.concat([top, other], ignore_index=True)


def _render_column_mapping_controls(
    df_raw: pd.DataFrame,
    warnings: dict | None = None,
    *,
    embedded: bool = False,
) -> None:
    columns = list(df_raw.columns)
    mapping = st.session_state.get("column_mapping") or {}
    review_required = _mapping_requires_review(warnings)

    label = "Spaltenzuordnung prüfen" if review_required else "Spaltenzuordnung"
    context = nullcontext() if embedded else st.expander(label, expanded=False)
    with context:
        if embedded:
            st.markdown(f"**{label}**")
        if warnings:
            if review_required:
                st.warning(
                    "Bitte Zuordnung bestätigen: Ist die vorgeschlagene Spalte wirklich Umsatz, "
                    "Kosten/Gewinn, Segment oder Zeitraum? DataDeck rechnet erst mit den hier gezeigten Spalten."
                )
            labels = {"umsatz": "Umsatz", "gewinn": "Gewinn", "kosten": "Kosten", "kategorie": "Kategorie", "datum": "Datum"}
            sources = {
                "umsatz": warnings.get("umsatz_source"),
                "gewinn": warnings.get("gewinn_source"),
                "kosten": warnings.get("kosten_source"),
                "kategorie": warnings.get("kategorie_source"),
                "datum": warnings.get("datum_source"),
            }
            confidence_labels = {
                "hoch": "hoch", "mittel": "mittel", "niedrig": "niedrig",
                "bestaetigt": "manuell bestätigt", "nicht_verfuegbar": "nicht erkannt",
            }
            for key, label in labels.items():
                role_confidence = warnings.get("mapping_confidence", {}).get(key, "nicht_verfuegbar")
                source = sources.get(key) or "—"
                if role_confidence in {"mittel", "niedrig"} and source != "—":
                    st.markdown(f"**Ist diese Spalte {label}?** `{escape_html(source)}`")
                st.markdown(
                    f"**{label}:** {escape_html(source)}  "
                    f"\nSicherheit: {confidence_labels.get(role_confidence, role_confidence)}"
                )
        st.caption("Ändern Sie die Zuordnung, wenn die automatische Erkennung nicht zur Datei passt. Für Gewinn kann alternativ Kosten gewählt werden; DataDeck berechnet Gewinn dann als Umsatz minus Kosten.")
        with st.form("column_mapping_form"):
            c1, c2 = st.columns(2)
            auto_options = ["__auto__"] + columns
            optional_options = ["__auto__", "__none__"] + columns
            with c1:
                umsatz = st.selectbox(
                    "Umsatz-Spalte",
                    auto_options,
                    index=_option_index(auto_options, mapping.get("umsatz", "__auto__")),
                    format_func=_mapping_option_label,
                    key="mapping_umsatz_select",
                )
                gewinn = st.selectbox(
                    "Gewinn-Spalte",
                    optional_options,
                    index=_option_index(optional_options, mapping.get("gewinn", "__auto__")),
                    format_func=_mapping_option_label,
                    key="mapping_gewinn_select",
                )
            with c2:
                kosten = st.selectbox(
                    "Kosten-Spalte",
                    optional_options,
                    index=_option_index(optional_options, mapping.get("kosten", "__auto__")),
                    format_func=_mapping_option_label,
                    key="mapping_kosten_select",
                )
                kategorie = st.selectbox(
                    "Kategorie/Segment",
                    optional_options,
                    index=_option_index(optional_options, mapping.get("kategorie", "__auto__")),
                    format_func=_mapping_option_label,
                    key="mapping_kategorie_select",
                )
                datum = st.selectbox(
                    "Datum/Zeitraum",
                    optional_options,
                    index=_option_index(optional_options, mapping.get("datum", "__auto__")),
                    format_func=_mapping_option_label,
                    key="mapping_datum_select",
                )
            normalize_categories = st.checkbox(
                "Groß-/Kleinschreibung in Kategorien zusammenführen",
                value=bool(mapping.get("normalize_categories", False)),
                key="mapping_normalize_categories",
                help="Enterprise, enterprise und ENTERPRISE werden gemeinsam ausgewertet; Originalwerte bleiben erhalten.",
            )

            if st.form_submit_button("Zuordnung übernehmen", width="stretch"):
                st.session_state.column_mapping = {
                    "umsatz": umsatz,
                    "gewinn": gewinn,
                    "kosten": kosten,
                    "kategorie": kategorie,
                    "datum": datum,
                    "normalize_categories": normalize_categories,
                }
                _reset_filters()
                _reset_analysis_outputs()
                st.rerun()


def main() -> None:
    _init_session_state()
    if _render_public_beta_page():
        return
    auth_identity = _auth_gate()
    if auth_identity is None:
        return
    is_production = app_environment() == "production"
    billing_active = billing_enabled()
    billing_identity = _billing_identity(auth_identity)
    billing_service = None
    billing_user = None
    if billing_active:
        try:
            billing_service = BillingService(BillingConfig.from_env())
            billing_user = billing_service.register_user(billing_identity)
            billing_return = str(getattr(st, "query_params", {}).get("billing", ""))
            if billing_return == "returned" and not st.session_state.billing_return_synced:
                billing_user = billing_service.sync_user(billing_identity)
                st.session_state.billing_return_synced = True
        except Exception as error:
            _log_event("BILLING_UNAVAILABLE", logging.ERROR, error_type=safe_exception_name(error))
    consulting_store = None
    workspace_context = None
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith(("postgresql://", "postgres://")):
        try:
            consulting_store = _consulting_store(database_url)
            workspace_context = consulting_store.ensure_personal_workspace(billing_identity.user_id)
            if not st.session_state.workspace_audit_logged:
                _record_workspace_event(consulting_store, billing_identity.user_id, "LOGIN", "session")
                st.session_state.workspace_audit_logged = True
        except Exception as error:
            consulting_store = None
            _log_event("WORKSPACE_UNAVAILABLE", logging.ERROR, error_type=safe_exception_name(error))
    selected_client = None
    theme = get_theme(st.session_state.theme)  # Vorlaeufig fuer die Sidebar; nach dem Theme-Toggle unten neu berechnet.

    with st.sidebar:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px;">'
            f'<span style="width:10px;height:10px;border-radius:3px;background:{theme["accent"]};'
            'display:inline-block;"></span>'
            '<span style="font-weight:800;font-size:1.15rem;letter-spacing:-0.01em;">DataDeck</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="dd-muted">Analyse für Berater &amp; Kanzleien</div>', unsafe_allow_html=True)
        st.caption(f"Beta · {APP_VERSION}")
        st.markdown('<hr class="dd-divider" style="margin:14px 0;">', unsafe_allow_html=True)

        dark_mode = st.toggle(
            "Dark Mode", value=(st.session_state.theme == "dark"), key="theme_toggle",
        )
        st.session_state.theme = "dark" if dark_mode else "light"

        st.markdown('<hr class="dd-divider" style="margin:14px 0;">', unsafe_allow_html=True)
        st.caption("BRANCHE")
        niche = st.selectbox("Branchen-Fokus", NISCHEN, key="niche_select", label_visibility="collapsed")

        if consulting_store is not None:
            st.markdown('<hr class="dd-divider" style="margin:14px 0;">', unsafe_allow_html=True)
            st.caption("MANDANT")
            try:
                clients = _consulting_clients(
                    database_url,
                    billing_identity.user_id,
                    st.session_state.consulting_cache_version,
                )
                client_options = ["__quick__"] + [client.client_id for client in clients]
                client_by_id = {client.client_id: client for client in clients}
                selected_client_id = st.selectbox(
                    "Analysekontext",
                    client_options,
                    format_func=lambda value: "Einmalige Schnellanalyse" if value == "__quick__" else client_by_id[value].name,
                    key="consulting_client_select",
                    label_visibility="collapsed",
                )
                selected_client = client_by_id.get(selected_client_id)
                with st.expander("Mandant anlegen", expanded=False):
                    with st.form("create_client_form"):
                        new_client_name = st.text_input("Mandantenname", max_chars=160)
                        new_client_reference = st.text_input("Interne Referenz (optional)", max_chars=120)
                        if st.form_submit_button("Mandant speichern", width="stretch"):
                            try:
                                with _operation_guard("client_write"):
                                    consulting_store.create_client(
                                        billing_identity.user_id, new_client_name, new_client_reference
                                    )
                                st.session_state.consulting_cache_version += 1
                                st.rerun()
                            except SecurityLimitError as error:
                                _show_security_limit("client_write", error)
                if selected_client is not None:
                    with st.expander("Mandant verwalten", expanded=False):
                        st.caption("Beim Löschen werden Analysen und Report-Metadaten dieses Mandanten entfernt.")
                        delete_confirmed = st.checkbox(
                            f"Löschen von {selected_client.name} bestätigen",
                            key="delete_client_confirmed",
                        )
                        if st.button(
                            "Mandant löschen", key="delete_client_btn",
                            disabled=not delete_confirmed, width="stretch",
                        ):
                            try:
                                with _operation_guard("client_write"):
                                    consulting_store.delete_client(
                                        billing_identity.user_id, selected_client.client_id
                                    )
                                st.session_state.consulting_cache_version += 1
                                st.rerun()
                            except SecurityLimitError as error:
                                _show_security_limit("client_write", error)
            except Exception as error:
                _log_event("CONSULTING_STORE_UNAVAILABLE", logging.ERROR, error_type=safe_exception_name(error))
                st.caption("Mandantenhistorie ist momentan nicht verfügbar.")

            if workspace_context is not None and workspace_context.role.value in {"OWNER", "PARTNER"}:
                with st.expander("Aktivität", expanded=False):
                    try:
                        events = consulting_store.list_audit_events(billing_identity.user_id, limit=8)
                        if not events:
                            st.caption("Noch keine Aktivitäten protokolliert.")
                        for event in events:
                            timestamp = event.created_at.strftime("%d.%m. %H:%M") if event.created_at else ""
                            st.caption(f"{timestamp} · {_ACTIVITY_LABELS.get(event.event_type, 'Aktivität erfasst')}")
                    except (PermissionError, ValueError):
                        st.caption("Aktivitäten sind für diese Rolle nicht verfügbar.")

        if is_production:
            is_premium = premium_feature_access(
                billing_active=billing_active,
                user=billing_user,
            )
        else:
            is_premium = st.toggle(
                "Demo: Premium-Funktionen", value=False, key="premium_toggle",
                help="Aktiviert in dieser lokalen Demo höhere Limits und PDF-Export. Kein echtes Abo, keine Zahlung.",
            )

        if billing_active:
            st.markdown('<hr class="dd-divider" style="margin:14px 0;">', unsafe_allow_html=True)
            st.caption("ACCOUNT & BILLING")
            if billing_user is None or billing_service is None:
                st.warning("Der Abrechnungsdienst ist momentan nicht erreichbar. Ihre Beta-Analyse bleibt verfügbar.")
            else:
                access = entitlement_for(billing_user)
                st.markdown(f"**Aktueller Plan:** DataDeck {access.plan.title()}")
                st.caption(_billing_status_label(billing_user.subscription_status, billing_user.cancel_at_period_end))
                if billing_user.current_period_end and billing_user.cancel_at_period_end:
                    st.caption(f"Zugriff bis {billing_user.current_period_end:%d.%m.%Y}")
                if access.has_active_pro:
                    try:
                        if st.button("Abo verwalten", key="billing_portal_btn", width="stretch"):
                            with _operation_guard("portal"):
                                st.session_state.billing_checkout_url = billing_service.create_portal_url(billing_identity)
                            _log_event("PORTAL_CREATED")
                    except SecurityLimitError as error:
                        _show_security_limit("portal", error)
                    except Exception as error:
                        _log_event("PORTAL_ERROR", logging.ERROR, error_type=safe_exception_name(error))
                        st.error("Der Abrechnungsdienst ist momentan nicht erreichbar.")
                else:
                    try:
                        if st.button("DataDeck Pro abonnieren", key="billing_checkout_btn", width="stretch"):
                            with _operation_guard("checkout"):
                                st.session_state.billing_checkout_url = billing_service.create_checkout_url(billing_identity)
                            _log_event("CHECKOUT_CREATED")
                    except SecurityLimitError as error:
                        _show_security_limit("checkout", error)
                    except Exception as error:
                        _log_event("CHECKOUT_ERROR", logging.ERROR, error_type=safe_exception_name(error))
                        st.error("Der Abrechnungsdienst ist momentan nicht erreichbar.")
                if st.session_state.billing_checkout_url:
                    st.link_button("Sicher zu Stripe", st.session_state.billing_checkout_url, width="stretch")
                billing_return = str(getattr(st, "query_params", {}).get("billing", ""))
                if billing_return == "confirming":
                    st.info("Zahlung wird serverseitig bestätigt. Der Redirect allein schaltet Pro nicht frei.")

        st.caption("ZIEL-MARGE")
        target_disabled = bool(st.session_state.get("revenue_only_mode"))
        ziel_marge = st.number_input(
            "Ziel-Marge (%)", min_value=0.0, max_value=100.0, value=20.0, step=1.0,
            key="ziel_marge_input", label_visibility="collapsed", disabled=target_disabled,
        )
        if target_disabled:
            st.caption("Nicht verfügbar: Gewinn- oder Kostenbasis fehlt.")

        st.markdown('<hr class="dd-divider" style="margin:14px 0;">', unsafe_allow_html=True)
        st.caption("DATEN")

        uploaded_file = st.file_uploader(
            "CSV oder Excel hochladen", type=["csv", "xlsx"], key="file_uploader",
            label_visibility="collapsed",
        )
        st.markdown('<div class="dd-muted" style="margin-top:-8px;">CSV oder XLSX · bis zu 100.000 Zeilen</div>', unsafe_allow_html=True)

        if st.button("Demo mit Beispieldaten starten", key="demo_btn", width="stretch"):
            _start_demo_analysis(is_premium)
            st.rerun()

        st.markdown('<hr class="dd-divider" style="margin:14px 0;">', unsafe_allow_html=True)
        if is_production and hasattr(st, "link_button"):
            st.link_button("Feedback geben", os.environ["BETA_FEEDBACK_URL"], width="stretch")
            st.link_button("Impressum", os.environ["LEGAL_IMPRINT_URL"], width="stretch")
            st.link_button("Datenschutz", os.environ["LEGAL_PRIVACY_URL"], width="stretch")
            st.link_button("Nutzungsbedingungen", os.environ["LEGAL_TERMS_URL"], width="stretch")
        elif hasattr(st, "expander"):
            with st.expander("Rechtliche Hinweise", expanded=False):
                st.caption("Impressum: Vor öffentlichem Launch vervollständigen.")
                st.caption("Datenschutz: Technische Verarbeitung ist in SECURITY_NOTES.md dokumentiert.")
                st.caption("Nutzungsbedingungen: Vor öffentlichem Launch vervollständigen.")
        if auth_required() and st.button("Abmelden", key="logout_btn", width="stretch"):
            _log_event("USER_LOGOUT")
            clear_sensitive_session(st.session_state)
            st.logout()

    theme = get_theme(st.session_state.theme)
    st.markdown(inject_theme_css(theme), unsafe_allow_html=True)
    if uploaded_file is None:
        uploaded_file = st.session_state.get("empty_file_uploader")

    # --- Datei prüfen und Analyse bewusst bestätigen ---
    if uploaded_file is not None:
        upload_size = int(getattr(uploaded_file, "size", 0))
        if uploaded_file.name.lower().endswith(".xlsx") and upload_size >= LARGE_XLSX_HINT_BYTES:
            st.info("Für maximale Geschwindigkeit empfehlen wir CSV.")
        signature = (
            uploaded_file.name,
            upload_size,
            str(getattr(uploaded_file, "file_id", "")),
            is_premium,
        )
        if st.session_state.last_upload_signature != signature:
            file_bytes = uploaded_file.getvalue()
            content_hash = dataset_hash(file_bytes)
            _log_event("UPLOAD_STARTED", bytes=len(file_bytes), dataset=content_hash[:12])
            try:
                inspection_started = time.perf_counter()
                with _operation_guard("upload"):
                    st.session_state.import_inspection = inspect_file_structure(file_bytes, uploaded_file.name)
                st.session_state.import_review_signature = signature
                st.session_state.pending_upload_hash = content_hash
                st.session_state.raw_df = None
                _reset_data_caches()
                _reset_filters()
                st.session_state.data_source = None
                st.session_state.data_signature = None
                st.session_state.dataset_fingerprint = None
                st.session_state.column_mapping = {}
                _reset_analysis_outputs()
                _record_performance_timing("import_inspection", inspection_started)
            except SecurityLimitError as error:
                _show_security_limit("upload", error)
                st.session_state.raw_df = None
                _reset_data_caches()
                return
            except ValueError as e:
                st.error(
                    "Die Datei konnte noch nicht geprüft werden. Bitte nutzen Sie eine CSV- oder XLSX-Datei "
                    f"mit klarer Tabellenstruktur. Detail: {e}"
                )
                st.info("Tipp: Wenn Sie DataDeck nur testen möchten, starten Sie zuerst die Demo mit Beispieldaten.")
                _log_event("UPLOAD_REJECTED", logging.WARNING, error_type=safe_exception_name(e))
                st.session_state.raw_df = None
                _reset_data_caches()
            except Exception as e:
                _show_unexpected_error("upload")
                _log_event("UPLOAD_ERROR", logging.ERROR, error_type=safe_exception_name(e))
                st.session_state.raw_df = None
                _reset_data_caches()
            st.session_state.last_upload_signature = signature

        inspection = st.session_state.import_inspection
        if st.session_state.raw_df is None and inspection:
            st.markdown('<div class="dd-eyebrow">IMPORT PRÜFEN</div>', unsafe_allow_html=True)
            st.title("Daten prüfen")
            st.write("Bestätigen Sie Tabellenblatt und Kopfzeile, bevor DataDeck Kennzahlen berechnet.")
            _assistant_card(
                "Prüfen Sie kurz, wo die echten Spaltenüberschriften stehen.",
                "Wenn Blatt und Kopfzeile stimmen, startet DataDeck danach automatisch mit Spaltenerkennung, Kennzahlen und Datenqualität.",
                ["Tabellenblatt auswählen", "Zeile mit Spaltenüberschriften prüfen", "Analyse starten"],
            )
            sheets = inspection["sheets"]
            sheet_names = [sheet["name"] for sheet in sheets]
            suggested_sheet = inspection.get("suggested_sheet") or sheet_names[0]
            selected_sheet = st.selectbox(
                "Tabellenblatt",
                sheet_names,
                index=sheet_names.index(suggested_sheet) if suggested_sheet in sheet_names else 0,
                key="import_sheet_select",
            )
            sheet_info = next(sheet for sheet in sheets if sheet["name"] == selected_sheet)
            candidates = sheet_info.get("header_candidates") or [{"row": 0, "values": []}]
            preview_count = max(1, int(sheet_info.get("preview_row_count", len(sheet_info.get("preview", [])))))
            candidate_rows = list(range(min(10, preview_count)))
            suggested_header_row = int(sheet_info.get("suggested_header_row", 0))
            if suggested_header_row not in candidate_rows:
                candidate_rows.append(suggested_header_row)
                candidate_rows.sort()
            selected_header = st.selectbox(
                "Zeile mit Spaltenüberschriften",
                candidate_rows,
                index=candidate_rows.index(suggested_header_row),
                format_func=lambda row: f"Zeile {row + 1}",
                key="import_header_select",
            )
            confidence_label = {
                "hoch": "Hoch", "mittel": "Mittel – bitte prüfen", "niedrig": "Niedrig – Bestätigung erforderlich",
            }.get(sheet_info.get("header_confidence"), "Bitte prüfen")
            preview_rows = sheet_info.get("preview", [])
            selected_columns = (
                [value for value in preview_rows[selected_header] if value]
                if selected_header < len(preview_rows) else []
            )
            column_preview = ", ".join(selected_columns[:8])
            _card(
                f'<div class="dd-eyebrow">DATEISTRUKTUR</div>'
                f'<b>{format_de_number(sheet_info.get("rows", 0), 0)} Datenzeilen · '
                f'{format_de_number(sheet_info.get("columns", 0), 0)} Spalten</b><br>'
                f'<span class="dd-muted">Header-Sicherheit: {escape_html(confidence_label)} · '
                f'Sheet: {escape_html(selected_sheet)}</span>'
                + (
                    f'<br><span class="dd-muted">Erkannte Überschriften: '
                    f'{escape_html(column_preview)}</span>'
                    if column_preview else ""
                )
            )
            preview_rows = preview_rows[:5]
            if preview_rows:
                with st.expander("Dateivorschau", expanded=sheet_info.get("header_confidence") != "hoch"):
                    st.code("\n".join(" | ".join(row) for row in preview_rows), language=None)
            if st.button("Analyse starten", type="primary", key="import_review_start", width="stretch"):
                try:
                    st.session_state.performance_flow_started = time.perf_counter()
                    st.session_state.performance_total_key = None
                    import_started = time.perf_counter()
                    file_bytes = uploaded_file.getvalue()
                    content_hash = st.session_state.pending_upload_hash or dataset_hash(file_bytes)
                    import_cache_key = (
                        content_hash,
                        bool(is_premium),
                        None if inspection["kind"] == "csv" else selected_sheet,
                        int(selected_header),
                    )
                    if (
                        st.session_state.import_cache_key == import_cache_key
                        and st.session_state.import_cache_df is not None
                    ):
                        df_loaded = st.session_state.import_cache_df
                        was_truncated = st.session_state.import_cache_truncated
                        max_rows = st.session_state.import_cache_max_rows
                        _log_event("PERFORMANCE_CACHE_HIT", stage="import")
                    else:
                        with _operation_guard("analysis"):
                            df_loaded, was_truncated, max_rows = load_and_validate_file(
                                file_bytes,
                                uploaded_file.name,
                                is_premium,
                                sheet_name=None if inspection["kind"] == "csv" else selected_sheet,
                                header_row=int(selected_header),
                            )
                        st.session_state.import_cache_key = import_cache_key
                        st.session_state.import_cache_df = df_loaded
                        st.session_state.import_cache_truncated = was_truncated
                        st.session_state.import_cache_max_rows = max_rows
                    _record_performance_timing("import", import_started, rows=len(df_loaded))
                    _log_event(
                        "UPLOAD_SUCCESS", bytes=len(file_bytes), rows=len(df_loaded),
                        columns=len(df_loaded.columns), truncated=was_truncated,
                        dataset=content_hash[:12],
                    )
                    st.session_state.raw_df = df_loaded
                    st.session_state.upload_truncated = was_truncated
                    st.session_state.upload_max_rows = max_rows
                    st.session_state.data_source = "upload"
                    st.session_state.data_signature = f"{content_hash}_{is_premium}_{selected_sheet}_{selected_header}"
                    st.session_state.dataset_fingerprint = content_hash
                    st.rerun()
                except SecurityLimitError as error:
                    _show_security_limit("analysis", error)
                except ValueError as error:
                    st.error(
                        "DataDeck konnte diese Auswahl noch nicht verarbeiten. Bitte prüfen Sie Tabellenblatt "
                        f"und Kopfzeile oder wählen Sie eine andere Kopfzeile. Detail: {error}"
                    )
                    _log_event("UPLOAD_REJECTED", logging.WARNING, error_type=safe_exception_name(error))
            return
    elif st.session_state.last_upload_signature is not None:
        if st.session_state.data_source == "upload":
            st.session_state.raw_df = None
            _reset_data_caches()
            st.session_state.data_source = None
            st.session_state.data_signature = None
            st.session_state.dataset_fingerprint = None
            st.session_state.column_mapping = {}
            _reset_analysis_outputs()
            _reset_filters()
        _reset_import_review()
        st.session_state.last_upload_signature = None

    # --- Empty State ---
    if st.session_state.raw_df is None:
        st.markdown('<div class="dd-eyebrow">DATADECK FÜR BERATER</div>', unsafe_allow_html=True)
        st.markdown(
            '<h1 style="margin-top:0;max-width:900px;">CSV- oder Excel-Datei hochladen, '
            'Kennzahlen automatisch erkennen und daraus Management-Report und PowerPoint erstellen.</h1>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="dd-muted" style="font-size:1.05rem;max-width:700px;margin-bottom:24px;">'
            "Für Unternehmensberater, schnelle Erstanalysen, Monatsreviews und Kundentermine.</p>",
            unsafe_allow_html=True,
        )
        upload_col, demo_col = st.columns(2)
        with upload_col:
            st.file_uploader(
                "Datei hochladen",
                type=["csv", "xlsx"],
                key="empty_file_uploader",
                help="CSV oder Excel. DataDeck prüft zuerst Tabellenblatt und Kopfzeile.",
            )
        with demo_col:
            if st.button("Demo mit Beispieldaten starten", type="primary", key="empty_demo_btn", width="stretch"):
                _start_demo_analysis(is_premium)
                st.rerun()
            st.caption("Kein Kundendatensatz nötig. Die Demo läuft durch denselben Analyse- und Exportfluss.")
        background_text = (
            "DataDeck erkennt Umsatz, Kosten oder Gewinn, Segment und Zeitraum. "
            "Finanzkennzahlen werden deterministisch berechnet. Die KI erstellt nur Einordnung "
            "und Handlungsempfehlungen auf Basis aggregierter Kennzahlen."
        )
        if hasattr(st, "expander"):
            with st.expander("Was macht DataDeck im Hintergrund?", expanded=False):
                st.write(background_text)
                st.caption("Rohdaten werden nicht an Gemini übertragen.")
        else:
            st.caption(background_text)
        return

    df_raw = st.session_state.raw_df
    if st.session_state.upload_truncated:
        st.warning(
            f"Zeilenlimit erreicht: Es werden maximal "
            f"{format_de_number(st.session_state.upload_max_rows, 0)} Zeilen verarbeitet."
        )
    data_key = st.session_state.data_signature or f"session-{id(df_raw)}"

    if st.session_state.pii_cache_key != data_key or st.session_state.pii_scan_cache is None:
        try:
            privacy_started = time.perf_counter()
            with _operation_guard("analysis"):
                st.session_state.pii_scan_cache = scan_dataframe_for_pii(df_raw)
            st.session_state.pii_cache_key = data_key
            _record_performance_timing("privacy_scan", privacy_started)
        except SecurityLimitError as error:
            _show_security_limit("analysis", error)
            return
    pii_scan = st.session_state.pii_scan_cache

    effective_mapping = _effective_column_mapping()
    prepared_key = (data_key, _stable_mapping_key(effective_mapping))
    prepared_cache_valid = (
        st.session_state.prepared_cache_key == prepared_key
        and st.session_state.prepared_df_cache is not None
        and st.session_state.prepared_warnings_cache is not None
        and st.session_state.prepared_quality_cache is not None
    )
    revenue_mode_changed = False
    if prepared_cache_valid:
        df_clean = st.session_state.prepared_df_cache
        warnings = st.session_state.prepared_warnings_cache
        data_quality = st.session_state.prepared_quality_cache
        _log_event("PERFORMANCE_CACHE_HIT", stage="mapping")
    else:
        clean_started = time.perf_counter()
        try:
            with _operation_guard("analysis"):
                df_clean, warnings = clean_and_prepare_data(df_raw, effective_mapping)
            new_revenue_only_mode = bool(warnings.get("revenue_only_mode"))
            revenue_mode_changed = st.session_state.revenue_only_mode != new_revenue_only_mode
            st.session_state.revenue_only_mode = new_revenue_only_mode
            data_quality = assess_data_quality(df_raw, df_clean, warnings)
            st.session_state.prepared_cache_key = prepared_key
            st.session_state.prepared_df_cache = df_clean
            st.session_state.prepared_warnings_cache = warnings
            st.session_state.prepared_quality_cache = data_quality
            st.session_state.kpi_cache_key = None
            st.session_state.kpi_cache = None
            _log_event(
                "DATA_PREPARED", rows=len(df_clean), columns=len(df_clean.columns),
                mapping=";".join(
                    f"{key}:{value}"
                    for key, value in sorted(warnings.get("mapping_confidence", {}).items())
                ),
                duration_ms=round((time.perf_counter() - clean_started) * 1000),
            )
            _record_performance_timing("mapping", clean_started, rows=len(df_clean))
        except SecurityLimitError as error:
            _show_security_limit("analysis", error)
            return
        except ValueError as e:
            st.error(
                "DataDeck konnte aus dieser Datei noch keine belastbare Analyse erstellen. "
                "Bitte prüfen Sie die Spaltenzuordnung oder wählen Sie eine Datei mit Umsatz- "
                f"und Gewinn- oder Kostenspalten. Detail: {e}"
            )
            st.info("Für einen schnellen Test können Sie jederzeit die Demo mit Beispieldaten starten.")
            _log_event("DATA_PREPARATION_REJECTED", logging.WARNING, error_type=safe_exception_name(e))
            return
        except Exception as e:
            _show_unexpected_error("data_preparation")
            _log_event("DATA_PREPARATION_ERROR", logging.ERROR, error_type=safe_exception_name(e))
            return

    if revenue_mode_changed:
        st.rerun()

    # --- Optionale Import-/Datenschutz-Details ---
    demo_badge = '<span class="dd-badge dd-badge-demo">DEMO-DATEN</span> ' if st.session_state.data_source == "demo" else ""
    st.markdown(
        f'<div class="dd-muted" style="margin:4px 0 18px;">{demo_badge}'
        f'{format_de_number(len(df_raw), 0)} Datensätze geladen · '
        f'{len(df_raw.columns)} Spalten erkannt</div>',
        unsafe_allow_html=True,
    )

    import_status = (
        f'<div class="dd-eyebrow">IMPORT</div>'
        f'<b>{format_de_number(len(df_raw), 0)} Datensätze erfolgreich geladen</b><br>'
        f'<span class="dd-muted">{len(df_raw.columns)} Spalten erkannt · '
        f'{warnings["duplicate_rows"]} Duplikate gefunden (nicht entfernt)</span><br>'
        f'<span class="dd-muted">Umsatz: {escape_html(warnings.get("umsatz_source") or "Nicht verfügbar")} · '
        f'Gewinn: {escape_html(warnings.get("gewinn_source") or "Nicht verfügbar")}</span>'
        + (
            f'<br><span class="dd-muted">Tabellenblatt: {escape_html(warnings.get("source_sheet"))}</span>'
            if warnings.get("source_sheet") else ""
        )
        + (
            f'<br><span class="dd-muted">{len(warnings.get("sheet_names", []))} Tabellenblätter erkannt.</span>'
            if len(warnings.get("sheet_names", [])) > 1 else ""
        )
        + (
            '<br><span class="dd-muted">Metadatenzeile automatisch übersprungen.</span>'
            if warnings.get("header_promoted") else ""
        )
    )

    pii_type_labels = {
        "email": "E-Mail", "person_name": "Name", "phone": "Telefon",
        "iban": "IBAN", "credit_card": "Kreditkarte", "address": "Adresse",
        "birth_date": "Geburtsdatum", "tax_id": "Steuer-ID", "ip": "IP-Adresse",
    }
    pii_types = ", ".join(
        pii_type_labels.get(item, item.replace("_", " ").title())
        for item in pii_scan.get("typen", [])
    ) or "Muster"
    privacy_status = (
        '<div class="dd-eyebrow">DATENSCHUTZSTATUS</div>'
        '<span class="dd-badge dd-badge-warning">⚠ Überprüfung empfohlen</span><br>'
        f'<span class="dd-muted">{pii_scan["treffer_gesamt"]} mögliche personenbezogene Muster in '
        f'{escape_html(", ".join(pii_scan["spalten_mit_treffern"]))}.</span><br>'
        f'<span class="dd-muted">{escape_html(pii_types)} · Details unten</span>'
        if pii_scan["treffer_gesamt"] > 0 else
        '<div class="dd-eyebrow">DATENSCHUTZSTATUS</div>'
        '<span class="dd-badge dd-badge-success">✓ Keine sensiblen Muster erkannt</span>'
    )

    quality_labels = {
        "hoch": ("dd-badge-success", "✓ Hoch"),
        "mittel": ("dd-badge-warning", "Mittel"),
        "eingeschraenkt": ("dd-badge-warning", "Eingeschränkt"),
        "nicht_ausreichend": ("dd-badge-warning", "Nicht ausreichend"),
    }
    quality_class, quality_label = quality_labels[data_quality["level"]]
    quality_status = (
        '<div class="dd-eyebrow">ANALYSEQUALITÄT</div>'
        f'<span class="dd-badge {quality_class}">{quality_label}</span><br>'
        f'<span class="dd-muted">{data_quality["completeness"]:.0%} vollständig · '
        f'{data_quality["missing_cells"]} fehlende Zellen · '
        f'{data_quality["invalid_numeric"]} ungültige Finanzwerte · '
        f'{data_quality["outlier_count"]} mögliche Ausreißer</span>'
    )
    if "Datum_Clean" in df_clean.columns and df_clean["Datum_Clean"].notna().any():
        period_status = (
            '<div class="dd-eyebrow">ZEITRAUM & SPALTEN</div>'
            f'<b>{format_de_date(df_clean["Datum_Clean"].min())} bis {format_de_date(df_clean["Datum_Clean"].max())}</b><br>'
            f'<span class="dd-muted">Umsatz: {escape_html(warnings.get("umsatz_source") or "—")} · '
            f'Kosten: {escape_html(warnings.get("kosten_source") or "—")} · '
            f'Gewinn: {escape_html(warnings.get("gewinn_source") or "—")} · '
            f'Segment: {escape_html(warnings.get("kategorie_source") or "—")}</span>'
        )
    else:
        period_status = (
            '<div class="dd-eyebrow">ZEITRAUM & SPALTEN</div>'
            '<b>Kein belastbarer Zeitraum erkannt</b><br>'
            f'<span class="dd-muted">Umsatz: {escape_html(warnings.get("umsatz_source") or "—")} · '
            f'Kosten: {escape_html(warnings.get("kosten_source") or "—")} · '
            f'Gewinn: {escape_html(warnings.get("gewinn_source") or "—")} · '
            f'Segment: {escape_html(warnings.get("kategorie_source") or "—")}</span>'
        )
    ai_trust_status = (
        '<div class="dd-eyebrow">KI-VERTRAUEN</div>'
        '<b>Kennzahlen werden deterministisch berechnet.</b><br>'
        '<span class="dd-muted">Die KI erstellt nur Einordnung und Handlungsempfehlungen auf Basis '
        'aggregierter Kennzahlen. Rohdaten werden nicht an die KI übertragen.</span>'
    )
    details_expanded = False
    if _mapping_requires_review(warnings):
        st.warning(
            "Die Spaltenzuordnung ist nicht eindeutig. Bitte prüfen Sie sie unter „Details & Prüfung“."
        )

    with st.expander("Details & Prüfung", expanded=details_expanded):
        st.markdown(
            '<div class="dd-status-grid dd-status-grid-compact">'
            f'{_card_html(import_status)}{_card_html(privacy_status)}{_card_html(quality_status)}'
            f'{_card_html(period_status)}{_card_html(ai_trust_status)}'
            '</div>',
            unsafe_allow_html=True,
        )

        if pii_scan["treffer_gesamt"] > 0:
            st.write(
                "Die Erkennung ist ein automatischer Hinweis und keine vollständige "
                "DSGVO-Anonymisierung. Personenbezogene Muster werden in der Vorschau maskiert."
            )
            if pii_scan.get("sampled"):
                st.caption(
                    f"Ressourcenschonende Stichprobe: {format_de_number(pii_scan.get('scanned_cells', 0), 0)} "
                    "Textzellen wurden geprüft."
                )
            st.caption("An Gemini werden ausschließlich aggregierte Kennzahlen übertragen, niemals Rohzeilen.")

        if data_quality["issues"]:
            for issue in data_quality["issues"]:
                st.markdown(f"**{issue['title']}**  \n{issue['detail']}")

        st.caption(
            "Methodik: Finanzkennzahlen werden deterministisch berechnet. "
            "KI-Texte basieren ausschließlich auf aggregierten Ergebnissen."
        )
        _render_column_mapping_controls(df_raw, warnings, embedded=True)

    if data_quality["level"] == "nicht_ausreichend":
        st.error("Die Datenbasis reicht für eine belastbare Gesamtanalyse noch nicht aus. Bitte öffnen Sie „Details & Prüfung“.")

    min_gewinn, min_marge, suchbegriff = _active_filter_values(df_clean, warnings)
    df_filtered = filter_data(df_clean, min_gewinn=min_gewinn, min_marge=min_marge)
    if suchbegriff.strip():
        df_filtered = df_filtered[
            df_filtered["Kategorie_Clean"].str.contains(suchbegriff.strip(), case=False, na=False, regex=False)
        ].copy()
        st.caption(f"{len(df_filtered)} Treffer für „{suchbegriff.strip()}“")
    if df_filtered.empty:
        st.warning("Keine Daten entsprechen den aktuellen Filtereinstellungen. Bitte Filter anpassen.")
        if st.button("Filter zurücksetzen", key="reset_empty_filters_btn"):
            _reset_filters()
            st.rerun()
        return

    analysis_context = {**warnings, "data_quality": data_quality}
    kpi_key = (
        prepared_key,
        float(min_gewinn),
        float(min_marge),
        suchbegriff.strip().casefold(),
    )
    if st.session_state.kpi_cache_key == kpi_key and st.session_state.kpi_cache is not None:
        kpis = st.session_state.kpi_cache
        _log_event("PERFORMANCE_CACHE_HIT", stage="analysis")
    else:
        analysis_started = time.perf_counter()
        try:
            with _operation_guard("analysis"):
                kpis = calculate_kpis(df_filtered, analysis_context)
        except SecurityLimitError as error:
            _show_security_limit("analysis", error)
            return
        st.session_state.kpi_cache_key = kpi_key
        st.session_state.kpi_cache = kpis
        _log_event(
            "ANALYSIS_COMPLETED", rows=kpis["anzahl_zeilen"],
            categories=kpis["anzahl_kategorien"],
            duration_ms=round((time.perf_counter() - analysis_started) * 1000),
        )
        _record_performance_timing("analysis", analysis_started, rows=kpis["anzahl_zeilen"])
    if (
        st.session_state.performance_flow_started is not None
        and st.session_state.performance_total_key != kpi_key
    ):
        _record_performance_timing("total", st.session_state.performance_flow_started)
        st.session_state.performance_total_key = kpi_key
    if (
        consulting_store is not None
        and st.session_state.audit_dataset_fingerprint != st.session_state.dataset_fingerprint
    ):
        _record_workspace_event(
            consulting_store, billing_identity.user_id, "IMPORT_COMPLETED", "dataset",
            metadata={"rows_processed": int(kpis["anzahl_zeilen"]), "columns_detected": int(len(df_filtered.columns))},
        )
        st.session_state.audit_dataset_fingerprint = st.session_state.dataset_fingerprint
    financial_available = kpis.get("financial_aggregation_available", True)
    effective_target = ziel_marge if kpis["profit_available"] and financial_available else None

    # --- KPI-Übersicht ---
    _section_header("Kennzahlen", "Die wichtigsten Werte des aktuellen Filterstands.")
    marge_ist_nan = kpis["aktuelle_marge"] != kpis["aktuelle_marge"]
    if not financial_available:
        marge_delta, marge_kind = "Nicht aggregierbar", "na"
    elif marge_ist_nan:
        marge_delta, marge_kind = "Nicht verfügbar", "na"
    else:
        diff = kpis["aktuelle_marge"] - effective_target
        marge_delta = f"{format_de_number(diff, 1)} Pkt. vs. Ziel"
        if diff >= 0:
            marge_delta = "+" + marge_delta
        marge_kind = "pos" if diff >= 0 else "neg"

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(_kpi_card("Umsatz", "—" if not financial_available else f"{format_compact_number(kpis['gesamt_umsatz'])} €", subtext=kpis["metrics"]["umsatz"]["reason"], exact_value="" if not financial_available else f"{format_de_number(kpis['gesamt_umsatz'])} €"), unsafe_allow_html=True)
    with k2: st.markdown(_kpi_card("Gewinn", "—" if not kpis["profit_available"] or not financial_available else f"{format_compact_number(kpis['gesamt_gewinn'])} €", subtext=kpis["metrics"]["gewinn"]["reason"], exact_value="" if not kpis["profit_available"] or not financial_available else f"{format_de_number(kpis['gesamt_gewinn'])} €"), unsafe_allow_html=True)
    with k3: st.markdown(_kpi_card("Marge", "—" if not kpis["profit_available"] or not financial_available else ("—" if marge_ist_nan else f"{format_de_number(kpis['aktuelle_marge'], 1)} %"), marge_delta, marge_kind, kpis["metrics"]["marge"]["reason"]), unsafe_allow_html=True)
    with k4: st.markdown(_kpi_card("Datensätze", format_de_number(kpis['anzahl_zeilen'], 0)), unsafe_allow_html=True)

    if kpis["top_performer"]:
        tp1, tp2 = st.columns(2)
        top, flop = kpis["top_performer"][0], kpis["flop_performer"][0]
        ranking_column = kpis["ranking_metric"]
        ranking_label = kpis["ranking_label"]
        with tp1:
            _card(f'<div class="dd-eyebrow">{"GEWINNSTÄRKSTES SEGMENT" if kpis["profit_available"] else "UMSATZSTÄRKSTES SEGMENT"}</div><b>{escape_html(top["Kategorie_Clean"])}</b><br>'
                  f'<span class="dd-muted">{format_compact_number(top[ranking_column])} € {ranking_label}</span>')
        with tp2:
            _card(f'<div class="dd-eyebrow">{"GEWINNSCHWÄCHSTES SEGMENT" if kpis["profit_available"] else "UMSATZSCHWÄCHSTES SEGMENT"}</div><b>{escape_html(flop["Kategorie_Clean"])}</b><br>'
                  f'<span class="dd-muted">{format_compact_number(flop[ranking_column])} € {ranking_label}</span>')

    # --- AI Insights ---
    report_language = normalize_report_language(st.session_state.report_settings.get("language"))
    insight_key = _compute_insight_key(kpis, effective_target, niche, is_premium, report_language)
    ist_veraltet = st.session_state.ai_insights is not None and st.session_state.ai_insights_key != insight_key
    report_client_name = _report_client_name(selected_client)
    report_context = (
        insight_key,
        st.session_state.ai_insights_key if not ist_veraltet else None,
        report_client_name,
        _report_presentation_key(),
    )
    if st.session_state.pdf_bytes and st.session_state.pdf_context_key != report_context:
        st.session_state.pdf_bytes = None
        st.session_state.pdf_filename = None
        st.session_state.pdf_context_key = None
    if st.session_state.pptx_bytes and st.session_state.pptx_context_key != report_context:
        st.session_state.pptx_bytes = None
        st.session_state.pptx_filename = None
        st.session_state.pptx_context_key = None

    _section_header("KI-Insights", "Einordnung ausschließlich auf Basis berechneter, aggregierter Kennzahlen.")

    gemini_configured = bool(os.getenv("GEMINI_API_KEY"))

    label = "Analyse aktualisieren" if st.session_state.ai_insights else "KI-Analyse starten"
    ai_clicked = st.button(
        label,
        type="primary",
        key="generate_ai_btn",
        disabled=bool(st.session_state.ai_in_progress) or not financial_available,
    )
    same_successful_analysis = (
        st.session_state.ai_insights is not None
        and st.session_state.ai_insights_key == insight_key
        and st.session_state.ai_insights_source == "gemini"
    )
    if ai_clicked and same_successful_analysis:
        st.info("Die KI-Analyse ist für diesen Datenstand bereits aktuell.")
    elif (
        ai_clicked
        and st.session_state.last_ai_context == insight_key
        and not action_allowed(st.session_state.last_ai_started, 10.0)
    ):
        st.warning("Bitte warten Sie kurz, bevor Sie eine weitere KI-Analyse starten.")
        _log_event("AI_RATE_LIMITED", logging.WARNING)
    elif ai_clicked:
        st.session_state.ai_in_progress = True
        st.session_state.last_ai_started = time.monotonic()
        st.session_state.last_ai_context = insight_key
        ai_started = time.perf_counter()
        _log_event("AI_REQUEST_STARTED")
        preserve_current_gemini = (
            st.session_state.ai_insights is not None
            and st.session_state.ai_insights_key == insight_key
            and st.session_state.ai_insights_source == "gemini"
        )
        try:
            with _operation_guard("ai"):
                with st.spinner("Analysiere Unternehmensdaten …"):
                    if not gemini_configured:
                        st.session_state.ai_insights = generate_local_summary(kpis, effective_target, report_language)
                        st.session_state.ai_insights_source = "local"
                        st.session_state.ai_insights_key = insight_key
                        st.session_state.ai_insights_created_at = datetime.datetime.now()
                        st.success("Lokale KPI-Analyse erstellt.")
                        _log_event("AI_LOCAL_SUCCESS", duration_ms=round((time.perf_counter() - ai_started) * 1000))
                        _record_workspace_event(
                            consulting_store, billing_identity.user_id, "INSIGHT_GENERATED", "analysis",
                            metadata={"provider": "local"},
                        )
                    else:
                        try:
                            st.session_state.ai_insights = generate_ai_summary(
                                kpis, effective_target, is_premium, niche, report_language
                            )
                            st.session_state.ai_insights_source = "gemini"
                            st.session_state.ai_insights_key = insight_key
                            st.session_state.ai_insights_created_at = datetime.datetime.now()
                            st.session_state.pdf_bytes = None
                            st.session_state.pdf_filename = None
                            st.session_state.pdf_context_key = None
                            st.success("Analyse abgeschlossen.")
                            _log_event("AI_PROVIDER_SUCCESS", duration_ms=round((time.perf_counter() - ai_started) * 1000))
                            _record_workspace_event(
                                consulting_store, billing_identity.user_id, "INSIGHT_GENERATED", "analysis",
                                metadata={"provider": "gemini"},
                            )
                        except (AIConfigError, AIRateLimitError, AIInsightError) as e:
                            if not preserve_current_gemini:
                                st.session_state.ai_insights = generate_local_summary(kpis, effective_target, report_language)
                                st.session_state.ai_insights_source = "local"
                                st.session_state.ai_insights_key = insight_key
                                st.session_state.ai_insights_created_at = datetime.datetime.now()
                            st.session_state.pdf_bytes = None
                            st.session_state.pdf_filename = None
                            st.session_state.pdf_context_key = None
                            fallback_text = (
                                "Die letzte erfolgreiche Gemini-Analyse bleibt sichtbar."
                                if preserve_current_gemini else
                                "DataDeck zeigt deshalb eine lokale KPI-Analyse."
                            )
                            st.warning(
                                "KI-Analyse momentan nicht verfügbar. Die berechneten Kennzahlen "
                                f"und der Bericht bleiben verfügbar. {fallback_text}"
                            )
                            _log_event("AI_PROVIDER_ERROR", logging.WARNING, error_type=safe_exception_name(e))
                        except Exception as e:
                            if not preserve_current_gemini:
                                st.session_state.ai_insights = generate_local_summary(kpis, effective_target, report_language)
                                st.session_state.ai_insights_source = "local"
                                st.session_state.ai_insights_key = insight_key
                                st.session_state.ai_insights_created_at = datetime.datetime.now()
                            st.warning(
                                "Gemini war nicht verfügbar. "
                                + ("Die letzte erfolgreiche Analyse bleibt sichtbar." if preserve_current_gemini else "DataDeck zeigt eine lokale KPI-Analyse.")
                            )
                            _log_event("AI_UNEXPECTED_ERROR", logging.ERROR, error_type=safe_exception_name(e))
        except SecurityLimitError as error:
            _show_security_limit("ai", error)
        finally:
            _record_performance_timing("ai", ai_started)
            st.session_state.ai_in_progress = False

    # Der Klick wird im selben Streamlit-Lauf verarbeitet. Den Status danach
    # neu bestimmen, damit kein alter Start- oder Aktualisierungshinweis neben
    # einer gerade erzeugten Analyse stehen bleibt.
    ist_veraltet = (
        st.session_state.ai_insights is not None
        and st.session_state.ai_insights_key != insight_key
    )
    if ist_veraltet:
        st.warning("Diese Analyse basiert auf einem vorherigen Filterstand. Bitte aktualisieren.")
    elif st.session_state.ai_insights is None:
        _assistant_card(
            "Nächster Schritt: KI-Analyse starten.",
            "Die Finanzkennzahlen sind bereits berechnet. Die KI bekommt nur aggregierte Kennzahlen und schreibt daraus Kurzfassung, Bedeutung und Handlungsmöglichkeiten.",
            ["KI-Analyse starten", "Einordnung prüfen", "Bei Bedarf Text für den Bericht bearbeiten"],
        )

    if not gemini_configured and not st.session_state.ai_insights:
        st.info("Gemini ist nicht eingerichtet. DataDeck kann stattdessen eine lokale KPI-Analyse erstellen.")

    if st.session_state.ai_insights:
        ai = st.session_state.ai_insights
        source_label = {
            "gemini": "Gemini", "edited": "Vom Berater bearbeitet", "local": "Lokale KPI-Analyse",
        }.get(st.session_state.ai_insights_source, "Lokale KPI-Analyse")
        source_note = (
            "Es wurden keine Rohzeilen an Gemini übertragen."
            if st.session_state.ai_insights_source in {"gemini", "edited"}
            else "Die Auswertung erfolgte lokal; es wurden keine Daten an einen KI-Dienst übertragen."
        )
        st.caption(f"Quelle: {source_label}. {source_note}")
        status_kind = "risk" if (effective_target is not None and not marge_ist_nan and kpis["aktuelle_marge"] < effective_target) else "recommend"
        st.markdown(
            '<div class="dd-insight-card">'
            '<span class="dd-insight-tag">KURZFASSUNG</span>'
            f'<div class="dd-insight-text">{escape_html(ai.get("zusammenfassung", ""))}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="dd-insight-card {status_kind}">'
            '<span class="dd-insight-tag">BEDEUTUNG</span>'
            f'<div class="dd-insight-text">{escape_html(ai.get("ziel_analyse", ""))}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        for item in ai.get("action_plan", []):
            st.markdown(
                '<div class="dd-insight-card recommend">'
                '<span class="dd-insight-tag">HANDLUNGSOPTION</span>'
                f'<div class="dd-insight-text">{escape_html(item)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
        evidence = ai.get("datengrundlage") or (
            f"{format_de_number(kpis['anzahl_zeilen'], 0)} Datensätze, "
            f"{format_de_number(kpis['anzahl_kategorien'], 0)} Kategorien; "
            f"Ranking nach {kpis['ranking_label']}."
        )
        with st.expander("Einordnung prüfen & bearbeiten", expanded=False):
            st.caption(f"Datengrundlage: {evidence}")
            with st.form("insight_editor_form"):
                edited_summary = st.text_area(
                    "Executive Summary", value=ai.get("zusammenfassung", ""), max_chars=2_000,
                )
                edited_meaning = st.text_area(
                    "Bedeutung", value=ai.get("ziel_analyse", ""), max_chars=2_000,
                )
                edited_actions = st.text_area(
                    "Handlungsoptionen (eine pro Zeile)",
                    value="\n".join(ai.get("action_plan", [])), max_chars=4_000,
                )
                consultant_comment = st.text_area(
                    "Beraterkommentar", value=st.session_state.consultant_comment, max_chars=2_000,
                )
                if st.form_submit_button("Berichtsinhalte übernehmen", width="stretch"):
                    st.session_state.ai_insights = {
                        **ai,
                        "zusammenfassung": edited_summary.strip(),
                        "ziel_analyse": edited_meaning.strip(),
                        "action_plan": [line.strip() for line in edited_actions.splitlines() if line.strip()],
                        "status": "bearbeitet",
                    }
                    st.session_state.ai_insights_source = "edited"
                    st.session_state.consultant_comment = consultant_comment.strip()
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_context_key = None
                    st.session_state.pptx_bytes = None
                    st.session_state.pptx_context_key = None
                    _record_workspace_event(
                        consulting_store, billing_identity.user_id, "INSIGHT_EDITED", "analysis",
                        resource_id=st.session_state.saved_analysis_id,
                    )
                    st.success("Berichtsinhalte aktualisiert.")

    _section_header("Wichtige Grafiken", "Entwicklung und Segmente auf einen Blick.")
    with st.container():
        layout = plotly_layout_colors(theme)
        if not financial_available:
            st.warning(
                "Mehrere Währungen wurden erkannt. Ohne hinterlegte Wechselkurse zeigt "
                "DataDeck keine Finanzsummen, Rankings, Charts oder KI-Bewertung."
            )
        # --- Entwicklung ---
        time_analysis = kpis.get("time_analysis", {})
        if financial_available and time_analysis.get("available"):
            _section_header("Entwicklung", "Zeitliche Veränderung und vergleichbare Zeiträume.")
            if time_analysis.get("comparison_available"):
                change = time_analysis["revenue_change_pct"]
                change_text = "Nicht verfügbar" if change != change else f"{change:+.1f} %"
                comparison_heading = (
                    "TEILMONAT VS. GLEICHER VORMONATSZEITRAUM"
                    if time_analysis.get("current_is_partial") else
                    "VOLLSTÄNDIGER MONAT VS. VORMONAT"
                )
                _card(
                    f'<div class="dd-eyebrow">{comparison_heading}</div>'
                    f'<b>Umsatz {escape_html(change_text)}</b><br>'
                    f'<span class="dd-muted">{escape_html(time_analysis.get("comparison_label", "Vergleichbarer Zeitraum"))}</span>'
                )
            else:
                st.caption(time_analysis.get("reason", "Für einen Vergleich fehlen Zeiträume."))

            time_series = time_analysis["series"]
            time_fig = go.Figure()
            complete_series = time_series.loc[~time_series["Ist_Teilmonat"]]
            time_fig.add_trace(go.Scatter(
                x=complete_series["Zeitraum"], y=complete_series["Umsatz_Clean"],
                mode="lines", name="Umsatz",
                line=dict(color=theme["accent"], width=3),
                hovertemplate="%{x|%b %Y}<br>Umsatz: %{y:,.0f} €<extra></extra>",
            ))
            partial_series = time_series.loc[time_series["Ist_Teilmonat"]]
            if not partial_series.empty:
                time_fig.add_trace(go.Scatter(
                    x=partial_series["Zeitraum"], y=partial_series["Umsatz_Clean"],
                    mode="markers", name="Umsatz (Teilmonat)",
                    marker=dict(color=theme["accent"], symbol="diamond-open", size=10),
                ))
            if kpis["profit_available"]:
                time_fig.add_trace(go.Scatter(
                    x=complete_series["Zeitraum"], y=complete_series["Gewinn_Clean"],
                    mode="lines", name="Gewinn",
                    line=dict(color=theme["success"], width=3),
                    hovertemplate="%{x|%b %Y}<br>Gewinn: %{y:,.0f} €<extra></extra>",
                ))
            time_fig.update_layout(
                title="Monatliche Entwicklung (€)", height=300,
                margin=dict(t=40, b=20, l=10, r=10), hovermode="x unified", **layout,
            )
            tick_values, tick_labels = _monthly_chart_ticks(time_series["Zeitraum"])
            time_fig.update_xaxes(tickmode="array", tickvals=tick_values, ticktext=tick_labels, tickangle=0)
            st.plotly_chart(time_fig, width="stretch")
            if not partial_series.empty:
                st.caption("Offene Markierungen zeigen unvollständige Monate und werden nicht als voller Monatswert fortgeschrieben.")

        # --- Charts ---
        if financial_available:
            _section_header("Segmente", "Stärkste und schwächste Kategorien im Vergleich.")
            cat_data = _top_categories_with_other(kpis["kategorien_daten"], limit=10)
            cat_data = cat_data.sort_values(kpis["ranking_metric"], ascending=False)

            chart_columns = st.columns(2) if kpis["profit_available"] else [st.container()]
            cc1 = chart_columns[0]
            with cc1:
                chart_metric = kpis["ranking_metric"]
                fig1 = go.Figure(data=[go.Bar(
                    x=cat_data["Kategorie_Clean"], y=cat_data[chart_metric], marker_color=theme["accent"],
                    hovertemplate="%{x}<br>%{y:,.2f} €<extra></extra>",
                )])
                fig1.update_layout(title=f'{kpis["ranking_label"]} nach Kategorie (€)', height=300, margin=dict(t=40, b=20, l=10, r=10), **layout)
                st.plotly_chart(fig1, width="stretch")
            if kpis["profit_available"]:
                with chart_columns[1]:
                    fig2 = go.Figure(data=[go.Bar(
                        x=cat_data["Kategorie_Clean"], y=cat_data["Marge"], marker_color=theme["success"],
                        hovertemplate="%{x}<br>%{y:.1f} %<extra></extra>",
                    )])
                    fig2.update_layout(title="Marge nach Kategorie (%)", height=300, margin=dict(t=40, b=20, l=10, r=10), **layout)
                    st.plotly_chart(fig2, width="stretch")

        marge_werte = kpis["kategorien_daten"]["Marge"].dropna() if financial_available else pd.Series(dtype=float)
        if not marge_werte.empty:
            fig3 = go.Figure(data=[go.Histogram(x=marge_werte, marker_color=theme["accent"], nbinsx=15)])
            fig3.update_layout(title="Verteilung der Margen", height=240, margin=dict(t=40, b=20, l=10, r=10), **layout)
            st.plotly_chart(fig3, width="stretch")

    if consulting_store is not None and selected_client is not None:
        _section_header("Mandantenhistorie", f"Aggregierte Analyseverläufe für {selected_client.name}.")
        try:
            history = _consulting_history(
                database_url,
                billing_identity.user_id,
                selected_client.client_id,
                st.session_state.consulting_cache_version,
            )
            if history:
                latest = history[0]
                st.caption(
                    f"{len(history)} gespeicherte Analyseperioden · zuletzt "
                    f"{format_de_date(latest.period_start)} bis {format_de_date(latest.period_end)}"
                )
                today = datetime.date.today()
                current_period_start = _as_date(kpis.get("date_range", {}).get("start"), today)
                current_period_end = _as_date(kpis.get("date_range", {}).get("end"), today)
                best = find_best_comparison(
                    AnalysisSnapshot(
                        analysis_id="current", owner_user_id=billing_identity.user_id,
                        client_id=selected_client.client_id,
                        dataset_hash=st.session_state.dataset_fingerprint or "0" * 64,
                        period_start=current_period_start,
                        period_end=current_period_end,
                        mapping={}, result=aggregate_result(kpis), quality_status=data_quality["level"],
                    ),
                    history,
                )
                if best:
                    label, previous = best
                    current_snapshot = AnalysisSnapshot(
                        analysis_id="current", owner_user_id=billing_identity.user_id,
                        client_id=selected_client.client_id,
                        dataset_hash=st.session_state.dataset_fingerprint or "0" * 64,
                        period_start=current_period_start,
                        period_end=current_period_end,
                        mapping={}, result=aggregate_result(kpis), quality_status=data_quality["level"],
                    )
                    change = compare_snapshots(current_snapshot, previous)
                    revenue_change = change.get("revenue_change_pct")
                    margin_change = change.get("margin_change_pp")
                    _card(
                        f'<div class="dd-eyebrow">{escape_html(label)} VERGLEICH</div>'
                        f'<b>Umsatz {"—" if revenue_change is None else f"{revenue_change:+.1f} %"}</b><br>'
                        f'<span class="dd-muted">Marge {"—" if margin_change is None else f"{margin_change:+.1f} Prozentpunkte"}</span>'
                    )
                for trend in detect_trends(history):
                    st.caption(f"{trend['label']}: drei Perioden in Folge {trend['direction']}.")
                current_for_monitoring = AnalysisSnapshot(
                    analysis_id="current-monitoring", owner_user_id=billing_identity.user_id,
                    client_id=selected_client.client_id,
                    dataset_hash=st.session_state.dataset_fingerprint or "0" * 64,
                    period_start=current_period_start, period_end=current_period_end,
                    mapping={}, result=aggregate_result(kpis), quality_status=data_quality["level"],
                )
                monitoring_history = list(history)
                if not monitoring_history or monitoring_history[0].dataset_hash != current_for_monitoring.dataset_hash:
                    monitoring_history.append(current_for_monitoring)
                signals = evaluate_monitoring(monitoring_history)
                with st.expander(f"Monitoring ({len(signals)})", expanded=any(item.severity == "IMPORTANT" for item in signals)):
                    if not signals:
                        st.caption("Keine regelbasierten Auffälligkeiten im verfügbaren Verlauf.")
                    for signal in signals:
                        if signal.severity == "IMPORTANT":
                            st.error(f"{signal.title}: {signal.detail}")
                        elif signal.severity == "NOTICE":
                            st.warning(f"{signal.title}: {signal.detail}")
                        else:
                            st.info(f"{signal.title}: {signal.detail}")

            date_start = kpis.get("date_range", {}).get("start")
            date_end = kpis.get("date_range", {}).get("end")
            default_start = _as_date(date_start, datetime.date.today().replace(day=1))
            default_end = _as_date(date_end, datetime.date.today())
            with st.form("save_analysis_form"):
                pc1, pc2 = st.columns(2)
                with pc1:
                    period_start = st.date_input("Zeitraum von", value=default_start)
                with pc2:
                    period_end = st.date_input("Zeitraum bis", value=default_end)
                if st.form_submit_button("Analyse beim Mandanten speichern", width="stretch"):
                    current_ai = st.session_state.ai_insights or {}
                    snapshot = AnalysisSnapshot(
                        analysis_id=str(uuid.uuid4()), owner_user_id=billing_identity.user_id,
                        client_id=selected_client.client_id,
                        dataset_hash=st.session_state.dataset_fingerprint or hashlib.sha256(
                            repr(aggregate_result(kpis)).encode("utf-8")
                        ).hexdigest(),
                        period_start=period_start, period_end=period_end,
                        mapping=kpis.get("column_mapping", {}), result=aggregate_result(kpis),
                        quality_status=data_quality["level"],
                        insights=[
                            {"text": item, "status": current_ai.get("status", "KI erzeugt")}
                            for item in current_ai.get("action_plan", [])
                        ],
                        executive_summary=current_ai.get("zusammenfassung", ""),
                        consultant_comment=st.session_state.consultant_comment,
                        analysis_version=APP_VERSION,
                        analysis_engine_version=APP_VERSION,
                        analysis_schema_version=1,
                    )
                    try:
                        with _operation_guard("client_write"):
                            saved_snapshot = consulting_store.save_analysis(snapshot)
                        st.session_state.saved_analysis_id = saved_snapshot.analysis_id
                        st.session_state.saved_analysis_client_id = saved_snapshot.client_id
                        persisted_history = [item for item in history if item.analysis_id != saved_snapshot.analysis_id]
                        consulting_store.sync_monitoring_findings(
                            billing_identity.user_id, selected_client.client_id,
                            evaluate_monitoring(persisted_history + [saved_snapshot]),
                        )
                        st.session_state.consulting_cache_version += 1
                        st.success("Analyse ohne Rohdatei in der Mandantenhistorie gespeichert.")
                    except SecurityLimitError as error:
                        _show_security_limit("client_write", error)
        except (ValueError, PermissionError) as error:
            st.warning(str(error))
        except Exception as error:
            _log_event("CONSULTING_HISTORY_ERROR", logging.ERROR, error_type=safe_exception_name(error))
            st.warning("Mandantenhistorie ist momentan nicht erreichbar. Die aktuelle Analyse bleibt verfügbar.")

    # --- Report Export ---
    _section_header("Export", "Analyse als Report oder editierbare Präsentation ausgeben.")
    export_meta = []
    if report_client_name:
        export_meta.append(f"Erstellt für: {report_client_name}")
    period_label = _report_period_label(kpis)
    if period_label:
        export_meta.append(f"Zeitraum: {period_label}")
    if export_meta:
        st.caption(" · ".join(export_meta))
    if not is_premium:
        st.info("Aktivieren Sie links die Demo-Premiumfunktionen, um PDF und PowerPoint zu testen.")
    else:
        with st.expander("Report konfigurieren", expanded=False):
            settings = st.session_state.report_settings
            with st.form("report_settings_form"):
                rs1, rs2 = st.columns(2)
                with rs1:
                    company_name = st.text_input("Beratungsunternehmen", value=settings.get("company_name", ""), max_chars=160)
                    client_name = st.text_input(
                        "Erstellt für / Kunde",
                        value=settings.get("client_name", "") or (selected_client.name if selected_client is not None else ""),
                        max_chars=160,
                        help="Erscheint auf dem PDF- und PowerPoint-Cover.",
                    )
                    accent_color = st.text_input("Akzentfarbe (Hex)", value=settings.get("accent_color", "#4F46E5"), max_chars=7)
                    contact_name = st.text_input("Ansprechpartner", value=settings.get("contact_name", ""), max_chars=120)
                with rs2:
                    report_language = st.selectbox(
                        "Report-Sprache",
                        options=["de", "en"],
                        index=0 if normalize_report_language(settings.get("language")) == "de" else 1,
                        format_func=report_language_name,
                        help="Steuert PDF, PowerPoint und KI-Texte im Report. Die App selbst bleibt deutsch.",
                    )
                    contact_email = st.text_input("Kontakt-E-Mail", value=settings.get("contact_email", ""), max_chars=200)
                    footer_text = st.text_input("Fußzeile", value=settings.get("footer_text", ""), max_chars=300)
                show_summary = st.checkbox("Executive Summary", value=settings.get("show_summary", True))
                show_ai_insights = st.checkbox("KI-Insights", value=settings.get("show_ai_insights", True))
                show_kpis = st.checkbox("Kennzahlen", value=settings.get("show_kpis", True))
                show_segments = st.checkbox("Segmente", value=settings.get("show_segments", True))
                show_time_series = st.checkbox("Zeitentwicklung", value=settings.get("show_time_series", True))
                show_methodology = st.checkbox("Methodik", value=settings.get("show_methodology", True))
                st.markdown("**PowerPoint-Konfiguration**")
                ppt1, ppt2 = st.columns(2)
                with ppt1:
                    ppt_deck_style = st.selectbox(
                        "PowerPoint-Deck",
                        options=["full", "short"],
                        index=0 if settings.get("ppt_deck_style", "full") != "short" else 1,
                        format_func=lambda value: {
                            "full": "Vollständiges Analyse-Deck",
                            "short": "Kurzdeck für Kundentermin",
                        }.get(value, value),
                        help="Kurzdeck konzentriert sich auf Cover, Summary, Kennzahlen, Segmente, Empfehlungen und Methodik.",
                    )
                with ppt2:
                    ppt_audience = st.selectbox(
                        "Zielgruppe",
                        options=["management", "finance", "growth"],
                        index={"management": 0, "finance": 1, "growth": 2}.get(settings.get("ppt_audience", "management"), 0),
                        format_func=lambda value: {
                            "management": "Management",
                            "finance": "Finanzen",
                            "growth": "Vertrieb / Wachstum",
                        }.get(value, value),
                        help="Steuert Fokus und Prioritäten im PowerPoint-Deck.",
                    )
                ppt_speaker_notes = st.checkbox(
                    "Sprechernotizen hinzufügen",
                    value=bool(settings.get("ppt_speaker_notes", False)),
                    help="Fügt kurze Presenter-Notizen in die PowerPoint ein.",
                )
                if st.form_submit_button("Report-Einstellungen speichern", width="stretch"):
                    st.session_state.report_settings = {
                        "company_name": company_name, "client_name": client_name, "accent_color": accent_color,
                        "contact_name": contact_name, "contact_email": contact_email,
                        "footer_text": footer_text, "language": report_language, "show_summary": show_summary,
                        "show_ai_insights": show_ai_insights, "show_kpis": show_kpis,
                        "show_segments": show_segments, "show_time_series": show_time_series,
                        "show_methodology": show_methodology,
                        "ppt_deck_style": ppt_deck_style, "ppt_audience": ppt_audience,
                        "ppt_speaker_notes": ppt_speaker_notes,
                    }
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_context_key = None
                    st.session_state.pptx_bytes = None
                    st.session_state.pptx_context_key = None
                    _record_workspace_event(
                        consulting_store, billing_identity.user_id, "BRANDING_CHANGED", "workspace",
                        resource_id=workspace_context.workspace_id if workspace_context else None,
                    )
                    st.success("Report-Einstellungen gespeichert.")
            logo_file = st.file_uploader(
                "Logo (PNG oder JPEG, maximal 1 MB)", type=["png", "jpg", "jpeg"], key="report_logo_upload",
            )
            if logo_file is not None:
                logo_content = logo_file.getvalue()
                if len(logo_content) <= 1_000_000:
                    try:
                        validated_logo_data_uri(logo_content)
                        if st.session_state.report_logo_bytes != logo_content:
                            st.session_state.report_logo_bytes = logo_content
                            st.session_state.pdf_bytes = None
                            st.session_state.pdf_context_key = None
                            st.session_state.pptx_bytes = None
                            st.session_state.pptx_context_key = None
                    except ValueError as error:
                        st.error(str(error))
                else:
                    st.error("Logo darf maximal 1 MB groß sein.")

        export_choice = st.segmented_control(
            "Was möchten Sie erstellen?",
            options=["PDF-Report", "PowerPoint-Präsentation", "Beide erstellen"],
            default="PDF-Report",
            key="report_export_choice",
            width="stretch",
        )
        if export_choice in {"PowerPoint-Präsentation", "Beide erstellen"}:
            st.caption("PowerPoint-Dateien sind editierbar und können in Keynote geöffnet oder importiert werden.")
        export_button_labels = {
            "PDF-Report": "PDF-Report erstellen",
            "PowerPoint-Präsentation": "PowerPoint erstellen",
            "Beide erstellen": "PDF & PowerPoint erstellen",
        }
        export_clicked = st.button(
            export_button_labels.get(export_choice, "Export erstellen"),
            type="primary",
            key="generate_export_btn",
            disabled=bool(st.session_state.pdf_in_progress or st.session_state.pptx_in_progress),
            width="stretch",
        )
        pdf_clicked = export_clicked and export_choice in {"PDF-Report", "Beide erstellen"}
        if pdf_clicked and st.session_state.pdf_bytes and st.session_state.pdf_context_key == report_context:
            st.info("Der PDF-Report ist für diesen Datenstand bereits erstellt.")
        elif (
            pdf_clicked
            and st.session_state.last_pdf_context == report_context
            and not action_allowed(st.session_state.last_pdf_started, 3.0)
        ):
            st.warning("Bitte warten Sie kurz, bevor Sie einen weiteren Report erstellen.")
            _log_event("PDF_RATE_LIMITED", logging.WARNING)
        elif pdf_clicked:
            st.session_state.pdf_in_progress = True
            st.session_state.last_pdf_started = time.monotonic()
            st.session_state.last_pdf_context = report_context
            with st.spinner("Report wird erstellt …"):
                pdf_started = time.perf_counter()
                _log_event("PDF_STARTED")
                try:
                    current_ai = None if ist_veraltet else st.session_state.ai_insights
                    report_version = st.session_state.report_version
                    can_version_report = (
                        consulting_store is not None
                        and selected_client is not None
                        and st.session_state.saved_analysis_id is not None
                        and st.session_state.saved_analysis_client_id == selected_client.client_id
                    )
                    if can_version_report:
                        report_version = consulting_store.next_report_version(
                            billing_identity.user_id,
                            selected_client.client_id,
                            st.session_state.saved_analysis_id,
                        )
                    with _operation_guard("pdf"):
                        st.session_state.pdf_bytes = generate_pdf(
                            kpis,
                            current_ai,
                            niche,
                            revenue_only=st.session_state.revenue_only_mode,
                            data_quality=data_quality,
                            report_settings=st.session_state.report_settings,
                            consultant_comment=st.session_state.consultant_comment,
                            report_version=report_version,
                            logo_bytes=st.session_state.report_logo_bytes,
                            client_name=report_client_name,
                            period_label=period_label,
                        )
                    st.session_state.pdf_filename = f"DataDeck_Analyse_{datetime.date.today():%Y-%m}.pdf"
                    st.session_state.pdf_context_key = report_context
                    if can_version_report:
                        report_metadata = consulting_store.save_report_metadata(
                            billing_identity.user_id,
                            selected_client.client_id,
                            st.session_state.saved_analysis_id,
                            st.session_state.report_settings,
                            hashlib.sha256(st.session_state.pdf_bytes).hexdigest(),
                        )
                        st.session_state.report_version = report_metadata.report_version + 1
                        st.session_state.last_report_id = report_metadata.report_id
                    else:
                        _record_workspace_event(
                            consulting_store, billing_identity.user_id, "REPORT_EXPORTED", "report",
                            metadata={"format": "PDF"},
                        )
                    _log_event(
                        "PDF_SUCCESS", bytes=len(st.session_state.pdf_bytes),
                        duration_ms=round((time.perf_counter() - pdf_started) * 1000),
                    )
                except SecurityLimitError as error:
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_filename = None
                    st.session_state.pdf_context_key = None
                    _show_security_limit("pdf", error)
                except Exception as e:
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_filename = None
                    st.session_state.pdf_context_key = None
                    st.error(
                        "Der PDF-Report konnte nicht erstellt werden. Bitte versuchen Sie es erneut. "
                        f"Fehler-ID: {st.session_state.correlation_id}"
                    )
                    _log_event("PDF_ERROR", logging.ERROR, error_type=safe_exception_name(e))
                finally:
                    _record_performance_timing("export_pdf", pdf_started)
            st.session_state.pdf_in_progress = False

        if st.session_state.pdf_bytes:
            if ist_veraltet:
                st.caption("Der Report enthält die aktuellen Kennzahlen ohne die veraltete KI-Analyse.")
            _card(
                '<div class="dd-eyebrow">REPORT BEREIT</div>'
                f'<b>{st.session_state.pdf_filename}</b>'
            )
            st.download_button(
                "PDF herunterladen", data=st.session_state.pdf_bytes,
                file_name=st.session_state.pdf_filename, mime="application/pdf", key="download_pdf_btn",
            )

        pptx_clicked = export_clicked and export_choice in {"PowerPoint-Präsentation", "Beide erstellen"}
        if pptx_clicked and st.session_state.pptx_bytes and st.session_state.pptx_context_key == report_context:
            st.info("Die PowerPoint-Datei ist für diesen Datenstand bereits erstellt.")
        elif pptx_clicked:
            st.session_state.pptx_in_progress = True
            with st.spinner("Editierbare Präsentation wird erstellt …"):
                pptx_started = time.perf_counter()
                try:
                    current_ai = None if ist_veraltet else st.session_state.ai_insights
                    report_version = st.session_state.report_version
                    can_version_report = (
                        consulting_store is not None and selected_client is not None
                        and st.session_state.saved_analysis_id is not None
                        and st.session_state.saved_analysis_client_id == selected_client.client_id
                    )
                    if can_version_report:
                        report_version = consulting_store.next_report_version(
                            billing_identity.user_id, selected_client.client_id,
                            st.session_state.saved_analysis_id,
                        )
                    with _operation_guard("pdf"):
                        st.session_state.pptx_bytes = generate_pptx(
                            kpis, current_ai, niche,
                            revenue_only=st.session_state.revenue_only_mode,
                            data_quality=data_quality,
                            column_mapping=kpis.get("column_mapping", {}),
                            report_settings=st.session_state.report_settings,
                            consultant_comment=st.session_state.consultant_comment,
                            client_name=report_client_name,
                            period_label=period_label, report_version=report_version,
                            logo_bytes=st.session_state.report_logo_bytes,
                        )
                    st.session_state.pptx_filename = f"DataDeck_Analyse_{datetime.date.today():%Y-%m}.pptx"
                    st.session_state.pptx_context_key = report_context
                    if can_version_report:
                        settings_with_format = {**st.session_state.report_settings, "format": "PPTX"}
                        metadata = consulting_store.save_report_metadata(
                            billing_identity.user_id, selected_client.client_id,
                            st.session_state.saved_analysis_id, settings_with_format,
                            hashlib.sha256(st.session_state.pptx_bytes).hexdigest(),
                        )
                        st.session_state.report_version = metadata.report_version + 1
                        st.session_state.last_report_id = metadata.report_id
                    else:
                        _record_workspace_event(
                            consulting_store, billing_identity.user_id, "REPORT_EXPORTED", "report",
                            metadata={"format": "PPTX"},
                        )
                    _log_event("PPTX_SUCCESS", bytes=len(st.session_state.pptx_bytes),
                               duration_ms=round((time.perf_counter() - pptx_started) * 1000))
                except SecurityLimitError as error:
                    st.session_state.pptx_bytes = None
                    _show_security_limit("pdf", error)
                except Exception as error:
                    st.session_state.pptx_bytes = None
                    st.error(f"Die PowerPoint-Datei konnte nicht erstellt werden. Fehler-ID: {st.session_state.correlation_id}")
                    _log_event("PPTX_ERROR", logging.ERROR, error_type=safe_exception_name(error))
                finally:
                    _record_performance_timing("export_pptx", pptx_started)
            st.session_state.pptx_in_progress = False

        if st.session_state.pptx_bytes:
            _card('<div class="dd-eyebrow">POWERPOINT BEREIT</div>'
                  f'<b>{escape_html(st.session_state.pptx_filename)}</b><br>'
                  '<span class="dd-muted">Diagramme, Tabellen und Texte bleiben editierbar.</span>')
            st.download_button(
                "PowerPoint herunterladen", data=st.session_state.pptx_bytes,
                file_name=st.session_state.pptx_filename,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key="download_pptx_btn",
            )

        if st.session_state.last_report_id and workspace_context is not None and workspace_context.role.value in {"OWNER", "PARTNER"}:
            if st.button("Letzten Report freigeben", key="approve_last_report_btn"):
                try:
                    consulting_store.approve_report(billing_identity.user_id, st.session_state.last_report_id)
                    st.success("Report freigegeben und im Audit-Log dokumentiert.")
                except (PermissionError, ValueError) as error:
                    st.warning(str(error))

        st.caption(
            "DataDeck unterstützt die Entscheidungsfindung. Empfehlungen sollten im jeweiligen "
            "Unternehmenskontext bewertet werden."
        )

    _render_advanced_options(df_clean, df_filtered, warnings, kpis, financial_available)
    st.caption("Beta-Feedback: Was war hilfreich, was fehlte für einen echten Kundentermin?")


if __name__ == "__main__":
    main()
