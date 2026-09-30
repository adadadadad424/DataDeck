"""
Zentrales DataDeck Design-System.

Einzige Quelle für Farben/Typografie/Spacing/Radius/Shadows in der
gesamten App. Referenz: die DataDeck-Landingpage (Framer) - heller,
hochwertiger B2B-SaaS-Look mit einem Indigo/Blau-Violett als Markenfarbe,
plus ein ebenso hochwertiges, eigenständig gestaltetes Dark Theme (nicht
nur "Hintergrund schwarz", siehe TOKENS unten: eigene Card-/Border-/
Schatten-Werte für beide Modi).

Verwendung in main.py:
    tokens = get_theme(st.session_state.theme)
    st.markdown(inject_theme_css(tokens), unsafe_allow_html=True)
Verwendung in Chart-Code:
    fig.update_layout(**plotly_layout_colors(tokens))
"""

from typing import Literal

ThemeName = Literal["dark", "light"]

# Markenfarbe bleibt über beide Modi konstant (wie bei den meisten
# hochwertigen SaaS-Produkten) - nur ihre Umgebung (Flächen/Text/Borders)
# passt sich an.
BRAND = "#4F46E5"
BRAND_HOVER = "#4338CA"

FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', "
    "'Helvetica Neue', Arial, sans-serif"
)

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#F8FAFC",
        "surface": "#FFFFFF",
        "surface_alt": "#F3F5F9",
        "text": "#161820",
        "text_muted": "#667085",
        "border": "#E3E7EE",
        "accent": BRAND,
        "accent_hover": BRAND_HOVER,
        "accent_soft": "#EEEDFD",
        "accent_text": "#FFFFFF",
        "success": "#0F9D58",
        "success_bg": "#EAF7EF",
        "warning": "#B7791F",
        "warning_bg": "#FDF3E3",
        "error": "#D2402C",
        "error_bg": "#FBEAE7",
        "info_bg": "#EEF1FC",
        "shadow": "0 1px 2px rgba(16,24,40,0.04), 0 10px 30px rgba(16,24,40,0.05)",
        "chip_demo_bg": "#FDF3E3",
        "chip_demo_text": "#8A5A12",
    },
    "dark": {
        "bg": "#0B0B10",
        "surface": "#15151C",
        "surface_alt": "#1C1C26",
        "text": "#F3F3F7",
        "text_muted": "#9A9AAC",
        "border": "#26262F",
        "accent": "#6E68F5",
        "accent_hover": "#847EF7",
        "accent_soft": "#22213D",
        "accent_text": "#FFFFFF",
        "success": "#3DDC84",
        "success_bg": "#12271C",
        "warning": "#E8B34D",
        "warning_bg": "#2B230F",
        "error": "#F0665A",
        "error_bg": "#2B1613",
        "info_bg": "#191A2C",
        "shadow": "0 1px 2px rgba(0,0,0,0.3), 0 12px 28px rgba(0,0,0,0.35)",
        "chip_demo_bg": "#2B230F",
        "chip_demo_text": "#E8B34D",
    },
}

DEFAULT_THEME: ThemeName = "light"

RADIUS_SM = "6px"
RADIUS_MD = "8px"
RADIUS_LG = "12px"


def get_theme(name: str) -> dict[str, str]:
    """Gibt das Token-Dict für 'dark'/'light' zurück; fällt bei
    unbekanntem/leerem Namen auf DEFAULT_THEME zurück statt zu crashen."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def plotly_layout_colors(theme: dict[str, str]) -> dict:
    """Gemeinsame Plotly-Layout-Optik für alle Charts, aus dem Theme
    abgeleitet - Charts sollen wie Teil des Produkts wirken, nicht wie
    Standard-Plotly."""
    return {
        "plot_bgcolor": theme["surface"],
        "paper_bgcolor": theme["surface"],
        "font_color": theme["text_muted"],
        "font_family": "Inter, -apple-system, sans-serif",
        "title_font_color": theme["text"],
        "title_font_size": 16,
        "legend_font_color": theme["text_muted"],
        "hoverlabel": {
            "bgcolor": theme["surface"],
            "bordercolor": theme["border"],
            "font_color": theme["text"],
        },
        "xaxis": {"gridcolor": theme["border"], "color": theme["text_muted"], "showline": False},
        "yaxis": {"gridcolor": theme["border"], "color": theme["text_muted"], "showline": False},
        "bargap": 0.35,
    }


def inject_theme_css(theme: dict[str, str]) -> str:
    """
    Kompletter CSS-Block: App-Hintergrund, Sidebar, Buttons, Alerts,
    Expander, Inputs (Text/Number/Selectbox/Slider), File Uploader,
    Tabellen, Tabs, Metriken sowie die DataDeck-eigenen Komponentenklassen
    (Card/Badge/Empty-State/KPI/Insight-Card - siehe unten).

    Bekannte Grenze: Streamlit exportiert seine internen data-testid-
    Selektoren nicht als stabile öffentliche API. Selektoren sind Stand
    Streamlit >=1.38 korrekt; nach einem Versionsupdate lohnt ein
    visueller Recheck.
    """
    return f"""
    <style>
    html, body, .stApp {{
        font-family: {FONT_STACK};
    }}
    .stApp {{
        background-color: {theme['bg']};
        color: {theme['text']};
    }}
    h1, h2, h3, h4, h5, h6 {{
        color: {theme['text']};
        font-weight: 700;
        letter-spacing: 0;
    }}
    p, label, span, div {{ color: {theme['text']}; }}

    #MainMenu, footer, header {{ visibility: hidden; }}
    .block-container {{ padding-top: 1.8rem; padding-bottom: 3.5rem; max-width: 1120px; }}

    /* ---- Sidebar / App-Shell ---- */
    [data-testid="stSidebar"] {{
        background-color: {theme['surface']};
        border-right: 1px solid {theme['border']};
    }}
    [data-testid="stSidebar"] {{ color: {theme['text']}; }}
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {{
        color: {theme['text_muted']} !important;
    }}

    /* ---- Buttons ---- */
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
        background-color: {theme['accent']} !important;
        color: {theme['accent_text']} !important;
        border: none !important;
        border-radius: {RADIUS_MD} !important;
        font-weight: 600 !important;
        min-height: 42px;
        padding: 0.58rem 1.15rem !important;
        transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
        background-color: {theme['accent_hover']} !important;
    }}
    .stButton > button:disabled, .stDownloadButton > button:disabled,
    .stFormSubmitButton > button:disabled {{
        background-color: {theme['surface_alt']} !important;
        color: {theme['text_muted']} !important;
        border: 1px solid {theme['border']} !important;
        opacity: 0.72;
        cursor: not-allowed;
    }}
    .stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
    .stFormSubmitButton > button:focus-visible {{
        outline: 3px solid {theme['accent_soft']} !important;
        outline-offset: 2px;
    }}
    .stButton > button[kind="secondary"] {{
        background-color: transparent !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['border']} !important;
        box-shadow: none !important;
    }}
    .stButton > button[kind="secondary"] * {{ color: {theme['text']} !important; }}
    .stButton > button *, .stDownloadButton > button *, .stFormSubmitButton > button * {{
        color: {theme['accent_text']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button {{
        background-color: transparent !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['border']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button * {{
        color: {theme['text']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        border-color: {theme['accent']} !important;
        color: {theme['accent']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover * {{
        color: {theme['accent']} !important;
    }}

    /* ---- Alerts ---- */
    .stAlert, div[data-testid="stNotification"] {{
        background-color: {theme['surface_alt']} !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_SM} !important;
    }}

    div[data-testid="stExpander"] {{
        background-color: {theme['surface']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_MD} !important;
        margin: 10px 0 14px;
        box-shadow: none !important;
    }}
    [data-testid="stExpander"] details,
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] details[open] > summary,
    [data-testid="stExpander"] summary:hover,
    [data-testid="stExpander"] summary:focus,
    [data-testid="stExpander"] summary:active,
    [data-testid="stExpanderDetails"] {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
    }}
    [data-testid="stExpander"] summary * {{
        color: {theme['text']} !important;
    }}
    [data-testid="stExpander"] summary {{
        min-height: 48px;
        font-weight: 600;
    }}
    [data-testid="stExpander"] summary:focus-visible {{
        outline: 2px solid {theme['accent']} !important;
        outline-offset: -2px;
    }}

    /* ---- Inputs ---- */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stTextArea"] textarea {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_SM} !important;
    }}
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input {{ min-height: 42px; }}
    [data-testid="stTextArea"] [data-baseweb="textarea"],
    [data-testid="stTextArea"] div[data-baseweb="base-input"] {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
        border-color: {theme['border']} !important;
    }}
    [data-testid="stTextArea"] textarea:focus,
    [data-testid="stTextArea"] div[data-baseweb="base-input"]:focus-within {{
        border-color: {theme['accent']} !important;
        box-shadow: 0 0 0 1px {theme['accent']} !important;
    }}
    [data-testid="stTextArea"] textarea::placeholder {{
        color: {theme['text_muted']} !important;
    }}
    [data-testid="stSelectbox"] [role="group"],
    [data-testid="stNumberInputContainer"] {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_SM} !important;
    }}
    [data-testid="stSelectbox"] input,
    [data-testid="stNumberInputContainer"] button {{
        color: {theme['text']} !important;
    }}
    [data-testid="stSelectboxVirtualDropdown"] {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_SM} !important;
        box-shadow: {theme['shadow']} !important;
    }}
    [data-testid="stSelectboxVirtualDropdown"] [role="listbox"],
    [data-testid="stSelectboxVirtualDropdown"] [role="option"] {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
    }}
    [data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
    [data-testid="stSelectboxVirtualDropdown"] [aria-selected="true"] {{
        background-color: {theme['surface_alt']} !important;
        color: {theme['text']} !important;
    }}
    [data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {{
        background-color: {theme['accent']} !important;
    }}
    [data-testid="stSegmentedControl"],
    [role="radiogroup"][aria-label="Was möchten Sie erstellen?"] {{
        background: {theme['surface_alt']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_MD} !important;
        padding: 4px !important;
    }}
    [data-testid="stSegmentedControl"] button,
    [role="radiogroup"][aria-label="Was möchten Sie erstellen?"] button {{
        background: transparent !important;
        color: {theme['text']} !important;
        border: 1px solid transparent !important;
        min-height: 40px;
        border-radius: {RADIUS_SM} !important;
        font-weight: 600 !important;
    }}
    [role="radiogroup"][aria-label="Was möchten Sie erstellen?"] button * {{
        color: {theme['text']} !important;
    }}
    [role="radiogroup"][aria-label="Was möchten Sie erstellen?"] button[data-selected="true"] {{
        background: {theme['accent_soft']} !important;
        border-color: {theme['accent']} !important;
        box-shadow: inset 0 0 0 1px {theme['accent']} !important;
    }}
    [role="radiogroup"][aria-label="Was möchten Sie erstellen?"] button[data-selected="true"] * {{
        color: {theme['accent']} !important;
    }}
    [data-testid="stFileUploaderDropzone"] {{
        background-color: {theme['surface_alt']} !important;
        border: 1.5px dashed {theme['border']} !important;
        border-radius: {RADIUS_MD} !important;
        color: {theme['text']} !important;
    }}
    [data-testid="stFileUploaderDropzone"] * {{ color: {theme['text_muted']} !important; }}

    /* ---- Tabellen ---- */
    [data-testid="stDataFrame"] {{
        background-color: {theme['surface']} !important;
        border: 1px solid {theme['border']} !important;
        border-radius: {RADIUS_MD};
        overflow: hidden;
    }}
    [data-testid="stDataFrame"] div,
    [data-testid="stDataFrame"] span,
    [data-testid="stDataFrame"] button {{
        color: {theme['text']} !important;
    }}
    [data-testid="stDataFrame"] canvas,
    [data-testid="stDataFrame"] [data-testid="stTable"],
    [data-testid="stDataFrame"] [role="grid"],
    [data-testid="stDataFrame"] [role="table"] {{
        background-color: {theme['surface']} !important;
    }}
    [data-testid="stDataFrame"] [role="columnheader"],
    [data-testid="stDataFrame"] [role="rowheader"],
    [data-testid="stDataFrame"] [role="gridcell"],
    [data-testid="stDataFrame"] [role="cell"] {{
        background-color: {theme['surface']} !important;
        color: {theme['text']} !important;
        border-color: {theme['border']} !important;
    }}
    [data-testid="stDataFrame"] [role="columnheader"] {{
        background-color: {theme['surface_alt']} !important;
        color: {theme['text_muted']} !important;
    }}

    /* ---- Metriken (Streamlit-native st.metric, Fallback) ---- */
    [data-testid="stMetric"] {{
        background-color: {theme['surface']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_MD};
        padding: 14px 18px;
        box-shadow: {theme['shadow']};
    }}
    [data-testid="stMetricLabel"] {{ color: {theme['text_muted']} !important; }}
    [data-testid="stMetricValue"] {{ color: {theme['text']} !important; }}

    /* ================= DataDeck-Komponenten ================= */

    .dd-eyebrow {{
        color: {theme['accent']};
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 4px;
    }}
    .dd-muted {{ color: {theme['text_muted']}; font-size: 0.92rem; }}

    .dd-card {{
        background: {theme['surface']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_MD};
        padding: 20px 22px;
        box-shadow: {theme['shadow']};
        margin-bottom: 16px;
    }}
    .dd-card-flat {{
        background: {theme['surface_alt']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_MD};
        padding: 16px 18px;
        margin-bottom: 12px;
    }}
    .dd-status-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
        align-items: stretch;
        margin: 14px 0;
    }}
    .dd-status-grid-compact {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
    }}
    .dd-status-grid .dd-card {{ height: 100%; box-sizing: border-box; margin-bottom: 0; }}
    .dd-card.assistant {{
        background: {theme['accent_soft']};
        border-color: {theme['accent']};
        box-shadow: none;
    }}
    .dd-card.assistant ol {{
        margin: 10px 0 0 1.1rem;
        padding: 0;
        color: {theme['text']};
    }}
    .dd-card.assistant li {{
        margin: 4px 0;
        padding-left: 2px;
    }}

    .dd-kpi-label {{
        color: {theme['text_muted']};
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    .dd-kpi-value {{
        color: {theme['text']};
        font-size: 1.75rem;
        font-weight: 800;
        letter-spacing: 0;
        line-height: 1.15;
        margin-top: 2px;
        white-space: nowrap;
    }}
    .dd-kpi-delta-pos {{ color: {theme['success']}; font-weight: 600; font-size: 0.85rem; }}
    .dd-kpi-delta-neg {{ color: {theme['error']}; font-weight: 600; font-size: 0.85rem; }}
    .dd-kpi-delta-na {{ color: {theme['text_muted']}; font-weight: 600; font-size: 0.85rem; }}
    .dd-kpi-reason {{
        color: {theme['text_muted']};
        font-size: 0.78rem;
        line-height: 1.3;
        margin-top: 5px;
        min-height: 2.05em;
    }}
    .dd-kpi-label + .dd-kpi-value {{ min-height: 2.25rem; }}

    .dd-section-header {{ margin: 42px 0 16px; }}
    .dd-section-header h3 {{ margin: 0; font-size: 1.4rem; line-height: 1.25; }}
    .dd-section-description {{
        color: {theme['text_muted']};
        font-size: 0.88rem;
        line-height: 1.4;
        margin-top: 5px;
    }}

    .dd-onboarding-step {{
        padding: 8px 12px 8px 0;
        border-top: 2px solid {theme['border']};
    }}
    .dd-onboarding-step b {{ display: block; margin: 5px 0 2px; }}

    .dd-badge {{
        display: inline-block;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        padding: 3px 10px;
        border-radius: 999px;
    }}
    .dd-badge-demo {{ background: {theme['chip_demo_bg']}; color: {theme['chip_demo_text']}; }}
    .dd-badge-success {{ background: {theme['success_bg']}; color: {theme['success']}; }}
    .dd-badge-warning {{ background: {theme['warning_bg']}; color: {theme['warning']}; }}
    .dd-badge-accent {{ background: {theme['accent_soft']}; color: {theme['accent']}; }}

    .dd-insight-card {{
        background: {theme['surface']};
        border: 1px solid {theme['border']};
        border-left: 3px solid {theme['accent']};
        border-radius: 0 {RADIUS_MD} {RADIUS_MD} 0;
        padding: 14px 18px;
        margin-bottom: 10px;
    }}
    .dd-insight-card.risk {{ border-left-color: {theme['error']}; }}
    .dd-insight-card.recommend {{ border-left-color: {theme['success']}; }}
    .dd-insight-tag {{
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: {theme['text_muted']};
        margin-bottom: 4px;
        display: block;
    }}
    .dd-insight-text {{
        color: {theme['text']};
        font-size: 0.95rem;
        line-height: 1.55;
    }}

    .dd-empty-hero {{ padding: 12px 0 4px 0; }}
    .dd-table-wrap {{
        width: 100%;
        max-height: 560px;
        overflow: auto;
        background: {theme['surface']};
        border: 1px solid {theme['border']};
        border-radius: {RADIUS_MD};
        box-shadow: {theme['shadow']};
    }}
    .dd-table {{
        width: 100%;
        border-collapse: collapse;
        min-width: 760px;
        color: {theme['text']};
        font-size: 0.86rem;
    }}
    .dd-table th {{
        position: sticky;
        top: 0;
        z-index: 1;
        background: {theme['surface_alt']};
        color: {theme['text_muted']};
        text-align: left;
        font-weight: 700;
        padding: 10px 12px;
        border-bottom: 1px solid {theme['border']};
        white-space: nowrap;
    }}
    .dd-table td {{
        background: {theme['surface']};
        color: {theme['text']};
        padding: 9px 12px;
        border-bottom: 1px solid {theme['border']};
        white-space: nowrap;
    }}
    .dd-table tr:nth-child(even) td {{
        background: {theme['surface_alt']};
    }}

    .dd-step-num {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; border-radius: 999px;
        background: {theme['accent_soft']}; color: {theme['accent']};
        font-weight: 700; font-size: 0.85rem; margin-bottom: 8px;
    }}

    .dd-divider {{ border: none; border-top: 1px solid {theme['border']}; margin: 22px 0; }}
    @media (max-width: 900px) {{
        .dd-status-grid {{ grid-template-columns: 1fr; gap: 10px; }}
        .dd-kpi-value {{ font-size: 1.5rem; }}
    }}
    @media (max-width: 600px) {{
        h1 {{ font-size: 2rem !important; line-height: 1.14 !important; }}
        .block-container {{ padding-top: 1.2rem; padding-bottom: 2.5rem; }}
    }}
    </style>
    """
