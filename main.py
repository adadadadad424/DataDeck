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
dokumentiert. White-Label- und Seats-Funktionen sind nicht implementiert.
"""

import datetime
import hashlib
import logging
import math
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from billing.config import BillingConfig, billing_enabled
from billing.entitlements import entitlement_for
from billing.models import Identity, stable_user_id
from billing.service import BillingService

from core.ai_insights import (
    AIConfigError,
    AIInsightError,
    AIRateLimitError,
    generate_ai_summary,
    generate_local_summary,
)
from core.analysis import calculate_kpis, filter_data
from core.data_processing import assess_data_quality, clean_and_prepare_data, load_and_validate_file
from core.formatting import format_compact_number, format_de_date, format_de_number
from core.report_builder import generate_pdf
from core.security import escape_html, mask_pii, scan_dataframe_for_pii
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
    production_config_errors,
    safe_exception_name,
)


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

DEMO_DATA = {
    "Kategorie": ["Filterkaffee", "Cappuccino", "Käsekuchen", "Sandwich", "Espresso"],
    "Umsatz": [1200, 3500, 800, 1500, 2200],
    "Reingewinn": [800, 2400, 300, 600, 1500],
    "Notizen": [
        "Kunde Max Mustermann (max@test.de, Tel: 0176-1234567) liebt diesen Kaffee.",
        "Standardverkauf ohne Auffälligkeiten.",
        "Erhöhter Wareneinsatz diese Woche.",
        "Kontakt via info@gastro-test.de läuft stabil.",
        "Top-Seller am Morgen.",
    ],
}


def _init_session_state() -> None:
    defaults = {
        "theme": DEFAULT_THEME,
        "raw_df": None,
        "data_source": None,
        "data_signature": None,
        "last_upload_signature": None,
        "ai_insights": None,
        "ai_insights_key": None,
        "ai_insights_source": None,
        "ai_insights_created_at": None,
        "pdf_bytes": None,
        "pdf_filename": None,
        "pdf_context_key": None,
        "revenue_only_mode": False,
        "column_mapping": {},
        "correlation_id": new_correlation_id(),
        "user_id_hash": "local-dev",
        "ai_in_progress": False,
        "pdf_in_progress": False,
        "last_ai_started": None,
        "last_pdf_started": None,
        "last_ai_context": None,
        "last_pdf_context": None,
        "auth_audit_subject": None,
        "auth_denied_logged": False,
        "billing_checkout_url": None,
        "billing_return_synced": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _log_event(event: str, level: int = logging.INFO, **fields) -> None:
    safe_fields = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    logger.log(
        level,
        "%s correlation_id=%s user_id=%s%s",
        event,
        st.session_state.get("correlation_id", "startup"),
        st.session_state.get("user_id_hash", "anonymous"),
        f" {safe_fields}" if safe_fields else "",
    )


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
    if page not in {"impressum", "datenschutz", "nutzungsbedingungen", "feedback"}:
        return False

    st.markdown('<div class="dd-eyebrow">DATADECK BETA</div>', unsafe_allow_html=True)
    if page == "impressum":
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
        for error in errors:
            st.caption(error)
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
        if st.button("Sicher anmelden", type="primary", key="login_btn"):
            try:
                st.login()
            except Exception as error:
                _log_event("AUTH_LOGIN_ERROR", logging.ERROR, error_type=safe_exception_name(error))
                st.error("Die Anmeldung ist momentan nicht verfügbar. Bitte kontaktieren Sie den Beta-Support.")
        return None

    claims = dict(st.user)
    try:
        token_expired = int(claims.get("exp", 0)) <= int(time.time())
    except (TypeError, ValueError):
        token_expired = True
    if token_expired:
        clear_sensitive_session(st.session_state)
        st.warning("Ihre Anmeldung ist abgelaufen. Bitte melden Sie sich erneut an.")
        st.logout()
        return None
    email = claims.get("email") or claims.get("preferred_username")
    subject = claims.get("sub") or claims.get("oid")
    if claims.get("email_verified") is False or not is_approved_user(email):
        if not st.session_state.get("auth_denied_logged"):
            _log_event("LOGIN_DENIED", logging.WARNING)
            st.session_state.auth_denied_logged = True
        st.error("Dieses Konto ist nicht für die DataDeck-Beta freigegeben.")
        if st.button("Abmelden", key="denied_logout_btn"):
            clear_sensitive_session(st.session_state)
            st.logout()
        return None

    st.session_state.user_id_hash = anonymized_user_id(subject, email)
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


def _compute_insight_key(kpis: dict, ziel_marge: float | None, niche: str, is_premium: bool) -> str:
    """Fingerabdruck dessen, worauf sich eine KI-Analyse bezieht. Ändert er
    sich (z.B. weil ein Filter geändert wurde), gilt die vorhandene Analyse
    als veraltet - sie bleibt sichtbar, wird aber deutlich markiert."""
    categories = kpis["kategorien_daten"].to_json(orient="records")
    category_sig = hashlib.sha256(categories.encode("utf-8")).hexdigest()
    return "|".join([
        f"u{round(kpis['gesamt_umsatz'], 2)}", f"g{round(kpis['gesamt_gewinn'], 2)}",
        f"r{kpis['anzahl_zeilen']}", f"z{ziel_marge if ziel_marge is not None else 'na'}", f"n{niche}",
        f"p{is_premium}", f"c{category_sig}",
        f"a{kpis.get('financial_aggregation_available', True)}",
    ])


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


def _data_preview_table(df: pd.DataFrame, max_rows: int = 100) -> str:
    preview = df.head(max_rows)
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
                display_values.append(escape_html(mask_pii(value)))
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


def _reset_analysis_outputs() -> None:
    st.session_state.ai_insights = None
    st.session_state.ai_insights_key = None
    st.session_state.ai_insights_source = None
    st.session_state.ai_insights_created_at = None
    st.session_state.pdf_bytes = None
    st.session_state.pdf_filename = None
    st.session_state.pdf_context_key = None


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


def _render_column_mapping_controls(df_raw: pd.DataFrame, warnings: dict | None = None) -> None:
    columns = list(df_raw.columns)
    mapping = st.session_state.get("column_mapping") or {}
    review_required = _mapping_requires_review(warnings)

    label = "Spaltenzuordnung prüfen" if review_required else "Spaltenzuordnung"
    with st.expander(label, expanded=False):
        if warnings:
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
                st.markdown(
                    f"**{label}:** {escape_html(sources.get(key) or '—')}  "
                    f"\nSicherheit: {confidence_labels.get(role_confidence, role_confidence)}"
                )
        st.caption("Ändern Sie die Zuordnung nur, wenn die automatische Erkennung nicht zur Datei passt.")
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

            if st.form_submit_button("Zuordnung übernehmen", width="stretch"):
                st.session_state.column_mapping = {
                    "umsatz": umsatz,
                    "gewinn": gewinn,
                    "kosten": kosten,
                    "kategorie": kategorie,
                    "datum": datum,
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

        if is_production:
            is_premium = entitlement_for(billing_user).has_access if billing_user else True
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
                            st.session_state.billing_checkout_url = billing_service.create_portal_url(billing_identity)
                            _log_event("PORTAL_CREATED")
                    except Exception as error:
                        _log_event("PORTAL_ERROR", logging.ERROR, error_type=safe_exception_name(error))
                        st.error("Der Abrechnungsdienst ist momentan nicht erreichbar.")
                else:
                    try:
                        if st.button("DataDeck Pro abonnieren", key="billing_checkout_btn", width="stretch"):
                            st.session_state.billing_checkout_url = billing_service.create_checkout_url(billing_identity)
                            _log_event("CHECKOUT_CREATED")
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

        if st.button("Demo-Daten laden", key="demo_btn", width="stretch"):
            _reset_filters()
            st.session_state.raw_df = pd.DataFrame(DEMO_DATA)
            st.session_state.data_source = "demo"
            st.session_state.data_signature = f"demo_{is_premium}"
            st.session_state.column_mapping = {}
            st.session_state.revenue_only_mode = False
            _reset_analysis_outputs()

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

    # --- Datei-Upload verarbeiten ---
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        content_hash = dataset_hash(file_bytes)
        signature = (uploaded_file.name, content_hash, is_premium)
        if st.session_state.last_upload_signature != signature:
            _log_event("UPLOAD_STARTED", bytes=len(file_bytes), dataset=content_hash[:12])
            try:
                df_loaded, was_truncated, max_rows = load_and_validate_file(file_bytes, uploaded_file.name, is_premium)
                _log_event(
                    "UPLOAD_SUCCESS", bytes=len(file_bytes), rows=len(df_loaded),
                    columns=len(df_loaded.columns), truncated=was_truncated,
                    dataset=content_hash[:12],
                )
                if was_truncated:
                    st.warning(
                        f"Zeilenlimit erreicht: Im {'Premium' if is_premium else 'Free'}-Tier werden "
                        f"maximal {max_rows:,} Zeilen verarbeitet."
                    )
                st.session_state.raw_df = df_loaded
                _reset_filters()
                st.session_state.data_source = "upload"
                st.session_state.data_signature = f"{content_hash}_{is_premium}"
                st.session_state.column_mapping = {}
                _reset_analysis_outputs()
            except ValueError as e:
                st.error(f"Datei konnte nicht verarbeitet werden: {e}")
                _log_event("UPLOAD_REJECTED", logging.WARNING, error_type=safe_exception_name(e))
                st.session_state.raw_df = None
            except Exception as e:
                _show_unexpected_error("upload")
                _log_event("UPLOAD_ERROR", logging.ERROR, error_type=safe_exception_name(e))
                st.session_state.raw_df = None
            st.session_state.last_upload_signature = signature
    elif st.session_state.last_upload_signature is not None:
        if st.session_state.data_source == "upload":
            st.session_state.raw_df = None
            st.session_state.data_source = None
            st.session_state.data_signature = None
            st.session_state.column_mapping = {}
            _reset_analysis_outputs()
            _reset_filters()
        st.session_state.last_upload_signature = None

    # --- Empty State ---
    if st.session_state.raw_df is None:
        st.markdown('<div class="dd-eyebrow">NEUE ANALYSE</div>', unsafe_allow_html=True)
        st.markdown('<h1 style="margin-top:0;">Unternehmensdaten auswerten</h1>', unsafe_allow_html=True)
        st.markdown(
            '<p class="dd-muted" style="font-size:1.05rem;max-width:640px;">'
            "Laden Sie eine CSV- oder Excel-Datei hoch. DataDeck prüft die Struktur, "
            "berechnet belastbare Kennzahlen und bereitet die Ergebnisse für den Bericht auf.</p>",
            unsafe_allow_html=True,
        )
        st.markdown('<div class="dd-empty-hero">', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        steps = [
            ("1", "Datei hochladen", "CSV oder XLSX links auswählen oder Demo-Daten nutzen."),
            ("2", "Zuordnung prüfen", "Erkannte Finanz-, Segment- und Datumsspalten bestätigen."),
            ("3", "Ergebnisse nutzen", "Kennzahlen prüfen, KI-Einordnung starten und PDF erstellen."),
        ]
        for col, (num, title, desc) in zip([c1, c2, c3], steps):
            with col:
                st.markdown(
                    f'<div class="dd-onboarding-step"><div class="dd-step-num">{num}</div>'
                    f'<b>{title}</b><span class="dd-muted">{desc}</span></div>',
                    unsafe_allow_html=True,
                )
        st.markdown('</div>', unsafe_allow_html=True)
        st.info("Noch keine eigene Datei zur Hand? Nutzen Sie **Demo-Daten laden** links in der Seitenleiste.")
        return

    df_raw = st.session_state.raw_df
    pii_scan = scan_dataframe_for_pii(df_raw)

    clean_started = time.perf_counter()
    try:
        df_clean, warnings = clean_and_prepare_data(df_raw, _effective_column_mapping())
        new_revenue_only_mode = bool(warnings.get("revenue_only_mode"))
        revenue_mode_changed = st.session_state.revenue_only_mode != new_revenue_only_mode
        st.session_state.revenue_only_mode = new_revenue_only_mode
        data_quality = assess_data_quality(df_raw, df_clean, warnings)
        _log_event(
            "DATA_PREPARED", rows=len(df_clean), columns=len(df_clean.columns),
            mapping=";".join(
                f"{key}:{value}"
                for key, value in sorted(warnings.get("mapping_confidence", {}).items())
            ),
            duration_ms=round((time.perf_counter() - clean_started) * 1000),
        )
    except ValueError as e:
        st.error(f"Daten konnten nicht aufbereitet werden: {e}")
        _log_event("DATA_PREPARATION_REJECTED", logging.WARNING, error_type=safe_exception_name(e))
        return

    except Exception as e:
        _show_unexpected_error("data_preparation")
        _log_event("DATA_PREPARATION_ERROR", logging.ERROR, error_type=safe_exception_name(e))
        return

    if revenue_mode_changed:
        st.rerun()

    # --- Upload-/Datenschutz-Status ---
    demo_badge = '<span class="dd-badge dd-badge-demo">DEMO-DATEN</span> ' if st.session_state.data_source == "demo" else ""
    st.markdown(f'<h2 style="margin-bottom:2px;">{demo_badge}Datenübersicht</h2>', unsafe_allow_html=True)

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
    st.markdown(
        '<div class="dd-status-grid">'
        f'{_card_html(import_status)}{_card_html(privacy_status)}{_card_html(quality_status)}'
        '</div>',
        unsafe_allow_html=True,
    )

    if pii_scan["treffer_gesamt"] > 0:
        with st.expander("Datenschutzdetails", expanded=False):
            st.write(
                "Die Erkennung ist ein automatischer Hinweis und keine vollständige "
                "DSGVO-Anonymisierung. Personenbezogene Muster werden in der Vorschau maskiert."
            )
            st.caption("An Gemini werden ausschließlich aggregierte Kennzahlen übertragen, niemals Rohzeilen.")

    if data_quality["issues"]:
        with st.expander("Datenqualität im Detail", expanded=data_quality["level"] == "nicht_ausreichend"):
            for issue in data_quality["issues"]:
                st.markdown(f"**{issue['title']}**  \n{issue['detail']}")

    _render_column_mapping_controls(df_raw, warnings)

    if data_quality["level"] == "nicht_ausreichend":
        st.error("Die Datenbasis ist für eine belastbare Gesamtanalyse noch nicht ausreichend. Details stehen oben.")

    # --- Filter ---
    _section_header("Filter", "Grenzen Sie die aktuelle Auswertung ein.")
    with st.form("filter_form"):
        if warnings.get("revenue_only_mode"):
            min_gewinn, min_marge = 0.0, 0.0
            suchbegriff = st.text_input("Kategorie durchsuchen", value="", placeholder="z.B. Espresso",
                                        key="category_filter")
            st.caption("Gewinn- und Margenfilter werden erst mit einer Gewinn- oder Kosten-Spalte verfügbar.")
        else:
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                lowest_gain = math.floor(min(0.0, float(df_clean["Gewinn_Clean"].min())))
                highest_gain = math.ceil(max(1.0, float(df_clean["Gewinn_Clean"].max())))
                min_gewinn = st.slider("Mindest-Gewinn je Datensatz (€)", lowest_gain, highest_gain,
                                       lowest_gain, key="min_gain_filter")
            with fc2:
                min_marge = st.slider("Mindest-Marge je Datensatz (%)", 0, 100, 0,
                                      key="min_margin_filter")
            with fc3:
                suchbegriff = st.text_input("Kategorie durchsuchen", value="", placeholder="z.B. Espresso",
                                            key="category_filter")
        st.form_submit_button("Filter anwenden", width="stretch")

    df_filtered = filter_data(df_clean, min_gewinn=min_gewinn, min_marge=min_marge)
    if suchbegriff.strip():
        df_filtered = df_filtered[
            df_filtered["Kategorie_Clean"].str.contains(suchbegriff.strip(), case=False, na=False, regex=False)
        ].copy()
        st.caption(f"{len(df_filtered)} Treffer für „{suchbegriff.strip()}“")
    if df_filtered.empty:
        st.warning("Keine Daten entsprechen den aktuellen Filtereinstellungen. Bitte Filter anpassen.")
        return

    analysis_started = time.perf_counter()
    analysis_context = {**warnings, "data_quality": data_quality}
    kpis = calculate_kpis(df_filtered, analysis_context)
    _log_event(
        "ANALYSIS_COMPLETED", rows=kpis["anzahl_zeilen"],
        categories=kpis["anzahl_kategorien"],
        duration_ms=round((time.perf_counter() - analysis_started) * 1000),
    )
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
            mode="lines+markers", name="Umsatz", line=dict(color=theme["accent"]),
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
                mode="lines+markers", name="Gewinn", line=dict(color=theme["success"]),
            ))
        time_fig.update_layout(title="Monatliche Entwicklung (€)", height=300, margin=dict(t=40, b=20, l=10, r=10), **layout)
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

    # --- AI Insights ---
    insight_key = _compute_insight_key(kpis, effective_target, niche, is_premium)
    ist_veraltet = st.session_state.ai_insights is not None and st.session_state.ai_insights_key != insight_key
    report_context = (insight_key, st.session_state.ai_insights_key if not ist_veraltet else None)
    if st.session_state.pdf_bytes and st.session_state.pdf_context_key != report_context:
        st.session_state.pdf_bytes = None
        st.session_state.pdf_filename = None
        st.session_state.pdf_context_key = None

    _section_header("KI-Insights", "Einordnung ausschließlich auf Basis berechneter, aggregierter Kennzahlen.")

    if ist_veraltet:
        st.warning("Diese Analyse basiert auf einem vorherigen Filterstand. Bitte aktualisieren.")
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
        with st.spinner("Analysiere Unternehmensdaten …"):
            if not gemini_configured:
                st.session_state.ai_insights = generate_local_summary(kpis, effective_target)
                st.session_state.ai_insights_source = "local"
                st.session_state.ai_insights_key = insight_key
                st.session_state.ai_insights_created_at = datetime.datetime.now()
                st.success("Lokale KPI-Analyse erstellt.")
                _log_event("AI_LOCAL_SUCCESS", duration_ms=round((time.perf_counter() - ai_started) * 1000))
            else:
                try:
                    st.session_state.ai_insights = generate_ai_summary(kpis, effective_target, is_premium, niche)
                    st.session_state.ai_insights_source = "gemini"
                    st.session_state.ai_insights_key = insight_key
                    st.session_state.ai_insights_created_at = datetime.datetime.now()
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_filename = None
                    st.session_state.pdf_context_key = None
                    st.success("Analyse abgeschlossen.")
                    _log_event("AI_PROVIDER_SUCCESS", duration_ms=round((time.perf_counter() - ai_started) * 1000))
                except (AIConfigError, AIRateLimitError, AIInsightError) as e:
                    if not preserve_current_gemini:
                        st.session_state.ai_insights = generate_local_summary(kpis, effective_target)
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
                        st.session_state.ai_insights = generate_local_summary(kpis, effective_target)
                        st.session_state.ai_insights_source = "local"
                        st.session_state.ai_insights_key = insight_key
                        st.session_state.ai_insights_created_at = datetime.datetime.now()
                    st.warning(
                        "Gemini war nicht verfügbar. "
                        + ("Die letzte erfolgreiche Analyse bleibt sichtbar." if preserve_current_gemini else "DataDeck zeigt eine lokale KPI-Analyse.")
                    )
                    _log_event("AI_UNEXPECTED_ERROR", logging.ERROR, error_type=safe_exception_name(e))
        st.session_state.ai_in_progress = False

    if not gemini_configured and not st.session_state.ai_insights:
        st.info("Gemini ist nicht eingerichtet. DataDeck kann stattdessen eine lokale KPI-Analyse erstellen.")

    if st.session_state.ai_insights:
        ai = st.session_state.ai_insights
        source_label = "Gemini" if st.session_state.ai_insights_source == "gemini" else "Lokale KPI-Analyse"
        st.caption(f"Quelle: {source_label}. Es wurden keine Rohzeilen an Gemini übertragen.")
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
        with st.expander("Warum sehe ich diese Einordnung?"):
            st.write(evidence)
            st.caption("An Gemini wurden nur diese aggregierten Kennzahlen übertragen, keine Rohzeilen.")

    # --- Daten ---
    _section_header("Detaildaten", "Maskierte Vorschau der ersten 100 gefilterten Datensätze.")
    st.markdown(_data_preview_table(df_filtered), unsafe_allow_html=True)
    if len(df_filtered) > 100:
        st.caption("Vorschau zeigt die ersten 100 gefilterten Datensätze.")

    # --- PDF ---
    _section_header("Bericht", "Managementreport mit Kennzahlen, Methodik und aktueller KI-Einordnung.")
    if not is_premium:
        st.info("PDF-Reports sind in dieser Demo hinter dem Premium-Schalter. Aktivieren Sie links **Demo: Premium-Funktionen**, um den Export zu testen.")
    else:
        pdf_clicked = st.button(
            "PDF-Report erstellen",
            key="generate_pdf_btn",
            disabled=bool(st.session_state.pdf_in_progress),
        )
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
                    st.session_state.pdf_bytes = generate_pdf(
                        kpis,
                        current_ai,
                        niche,
                        revenue_only=st.session_state.revenue_only_mode,
                        data_quality=data_quality,
                    )
                    st.session_state.pdf_filename = f"DataDeck_Analyse_{datetime.date.today():%Y-%m}.pdf"
                    st.session_state.pdf_context_key = report_context
                    _log_event(
                        "PDF_SUCCESS", bytes=len(st.session_state.pdf_bytes),
                        duration_ms=round((time.perf_counter() - pdf_started) * 1000),
                    )
                except Exception as e:
                    st.session_state.pdf_bytes = None
                    st.session_state.pdf_filename = None
                    st.session_state.pdf_context_key = None
                    st.error(
                        "Der PDF-Report konnte nicht erstellt werden. Bitte versuchen Sie es erneut. "
                        f"Fehler-ID: {st.session_state.correlation_id}"
                    )
                    _log_event("PDF_ERROR", logging.ERROR, error_type=safe_exception_name(e))
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


if __name__ == "__main__":
    main()
