"""Honest trust-center content and a self-contained security whitepaper."""

from __future__ import annotations

import datetime as dt
import os
import sys

from jinja2 import Environment, select_autoescape


TRUST_SECTIONS = (
    ("Datenschutz", "Uploads werden sitzungsgebunden verarbeitet. In PostgreSQL liegen Kontodaten, Mandantennamen und Referenzen sowie aggregierte Analyse- und Reportdaten; Rohdateien werden dort nicht gespeichert."),
    ("KI-Datengrenze", "Gemini erhält ausschließlich berechnete Kennzahlen und begrenzte Kategorienamen, keine vollständigen Rohzeilen."),
    ("Zugriff", "OIDC-Anmeldung, serverseitige Workspace-Rollen und ressourcenbezogene Berechtigungsprüfungen begrenzen den Zugriff."),
    ("Historie", "Analyse- und Reportversionen sowie Aktivitätsereignisse sind technisch gegen nachträgliche Änderung geschützt."),
    ("Betrieb", "Healthchecks, strukturierte technische Logs, Rate Limits und dokumentierte Wiederherstellungsabläufe unterstützen den Betrieb."),
)

SUBPROCESSORS = (
    ("Render", "Hosting und PostgreSQL", "EU-Region Frankfurt, soweit im gewählten Dienst verfügbar"),
    ("Google", "OIDC-Anmeldung und optionale Gemini-Interpretation", "Aggregierte Kennzahlen bei aktivierter KI"),
    ("Stripe", "Optionale Test-/Abo-Abrechnung", "Nur bei aktivierter Billing-Konfiguration"),
)


def generate_security_whitepaper() -> bytes:
    if sys.platform == "darwin":
        os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")
    from weasyprint import HTML

    template = Environment(autoescape=select_autoescape(default_for_string=True)).from_string("""
    <!doctype html><html lang="de"><head><meta charset="utf-8"><style>
    @page { size:A4; margin:20mm; @bottom-right { content:"Seite " counter(page); font:8pt Arial; color:#777; } }
    body { font-family:Arial,sans-serif; color:#181821; line-height:1.55; font-size:11pt; }
    h1 { font-size:27pt; margin:0 0 8mm; } h2 { font-size:15pt; margin-top:9mm; border-bottom:2px solid #4F46E5; padding-bottom:2mm; }
    .meta,.note { color:#666; } .note { background:#F7F7FB; border-left:3px solid #4F46E5; padding:4mm; }
    table { width:100%; border-collapse:collapse; } th,td { text-align:left; padding:3mm; border-bottom:1px solid #ddd; vertical-align:top; }
    th { font-size:9pt; color:#666; }
    </style></head><body>
    <h1>DataDeck Security Whitepaper</h1><p class="meta">Technische Beta · Stand {{ date }}</p>
    <p class="note">Dieses Dokument beschreibt den aktuell implementierten technischen Stand. Es ist weder Zertifizierung noch Rechtsberatung und behauptet keine ISO-, SOC-2- oder DSGVO-Zertifizierung.</p>
    <h2>Sicherheitsprinzipien</h2>{% for title,text in sections %}<h3>{{ title }}</h3><p>{{ text }}</p>{% endfor %}
    <h2>Datenfluss</h2><p>CSV/XLSX → lokale Validierung und Normalisierung → deterministische KPI-Berechnung → optionale, aggregierte KI-Interpretation → PDF/PPTX. Rohdateien werden nicht in der Mandantenhistorie gespeichert.</p>
    <h2>Dienstleister</h2><table><tr><th>Dienst</th><th>Zweck</th><th>Hinweis</th></tr>{% for name,purpose,note in subprocessors %}<tr><td>{{ name }}</td><td>{{ purpose }}</td><td>{{ note }}</td></tr>{% endfor %}</table>
    <h2>Grenzen und Verantwortung</h2><p>Automatische PII-Mustererkennung ist keine vollständige Anonymisierung. Nutzer müssen Datenminimierung, Rechtsgrundlage, Aufbewahrung und fachliche Ergebnisprüfung organisatorisch sicherstellen.</p>
    <h2>Vorfälle und Wiederherstellung</h2><p>DataDeck besitzt dokumentierte Abläufe für Incident Response, Backup/Restore und Produktionsbetrieb. Sicherheitsrelevante Meldungen sollen über den vom Betreiber veröffentlichten Supportkanal gemeldet werden.</p>
    </body></html>""")
    html = template.render(date=dt.date.today().strftime("%d.%m.%Y"), sections=TRUST_SECTIONS,
                           subprocessors=SUBPROCESSORS)
    content = HTML(string=html).write_pdf()
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Das Security Whitepaper überschreitet das Größenlimit")
    return content
