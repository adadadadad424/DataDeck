"""
Sicherheits- und Datenschutz-Hilfsfunktionen für DataDeck.

ARCHITEKTUR (Audit SEC-4, unverändert): Die eigentliche Verteidigungslinie
gegen PII-Leaks an Gemini ist NICHT diese Datei, sondern dass
core/ai_insights.py ausschließlich bereits aggregierte KPIs (Summen,
Mittelwerte) und kurze Kategorienamen überträgt - niemals Rohdaten
einzelner Tabellenzeilen. Die Funktionen hier sind eine zusätzliche,
zweite Verteidigungslinie für den Fall, dass eine falsch erkannte Spalte
(z.B. durch mehrdeutige Kopfzeilen) versehentlich personenbezogene
Freitexte als "Kategorie" enthält.

ÄNDERUNGEN GEGENÜBER DER VORVERSION (siehe Audit):
- SEC-1: Telefon-Regex verlangt jetzt mindestens ein echtes Trennzeichen
  zwischen den Zifferngruppen. Vorher konnte jede beliebige 6-8-stellige
  Ziffernfolge ohne Trennzeichen (z.B. Teil eines Produktcodes oder ein
  Datum wie "20260115") fälschlich als Telefonnummer erkannt werden.
- SEC-2/SEC-3: IBAN- und Kreditkarten-Kandidaten werden jetzt zusätzlich
  per Prüfsumme validiert (Mod-97 bzw. Luhn), bevor sie maskiert werden -
  senkt die False-Positive-Rate bei zufällig ähnlich aussehenden
  Produkt-/Artikelcodes deutlich.
- SEC-5: sanitize_for_prompt() entfernt jetzt zusätzlich Zeilenumbrüche/
  Tabs vor der Zeichen-Filterung (erschwert das Vortäuschen neuer
  Prompt-Abschnitte als Teil der bestehenden Prompt-Injection-Abwehr).

GRENZE: Automatische PII-Erkennung per Regex kann grundsätzlich weder
alle PII zuverlässig erkennen (False Negatives, z.B. ungewöhnlich
formatierte Telefonnummern) noch False Positives vollständig
ausschließen. Das ist dokumentiert, keine Vollständigkeitsgarantie.
"""

import re
import html

import pandas as pd


def _luhn_valid(digits: str) -> bool:
    """Validiert eine Ziffernfolge per Luhn-Algorithmus (Standard-Prüfsumme
    für Kreditkartennummern). Reduziert False Positives bei zufälligen
    13-19-stelligen Ziffernfolgen (z.B. EAN/GTIN-Artikelcodes) erheblich,
    da eine zufällige Folge nur mit ca. 10% Wahrscheinlichkeit besteht."""
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _iban_checksum_valid(candidate: str) -> bool:
    """Validiert eine IBAN-Kandidatin per Mod-97-Prüfsumme (ISO 7064).
    Reduziert False Positives bei zufälligen "2 Großbuchstaben + 2 Ziffern
    + alphanumerisch"-Mustern in Kategorie-/Produktnamen."""
    iban = candidate.replace(' ', '').upper()
    if not (15 <= len(iban) <= 34):
        return False
    if not (iban[:2].isalpha() and iban[2:4].isdigit()):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric_chars = []
    for ch in rearranged:
        if ch.isdigit():
            numeric_chars.append(ch)
        elif ch.isalpha():
            numeric_chars.append(str(ord(ch) - 55))
        else:
            return False
    try:
        return int(''.join(numeric_chars)) % 97 == 1
    except ValueError:
        return False


_EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

# Audit SEC-1: verlangt jetzt mindestens EIN echtes Trennzeichen zwischen
# den Zifferngruppen. Reine, ununterbrochene Ziffernfolgen (Datumswerte,
# Artikel-/EAN-Nummern) werden dadurch bewusst NICHT mehr getroffen.
_PHONE_RE = re.compile(
    r'(?<!\w)(\+\d{1,3}[\s./-]?)?\(?0?\d{2,5}\)?[\s./-]\d[\d\s./-]{3,12}\d(?!\w)'
)

_IBAN_CANDIDATE_RE = re.compile(r'\b[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}\b')

# Ziffernfolgen mit optionalen Leerzeichen/Bindestrichen dazwischen; nur
# Kandidaten, die zusätzlich die Luhn-Prüfsumme bestehen, werden maskiert.
_CC_CANDIDATE_RE = re.compile(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)')

_IPV4_CANDIDATE_RE = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
_VAT_ID_RE = re.compile(r'\bDE[ -]?\d{9}\b', re.IGNORECASE)
_TAX_ID_CONTEXT_RE = re.compile(
    r'(?i)\b(steuer(?:liche)?(?:\s+identifikationsnummer|-?id|nummer)?|tax\s*id)\s*[:#-]?\s*((?:\d[\s-]?){11})\b'
)
_BIRTHDATE_CONTEXT_RE = re.compile(
    r'(?i)\b(geburtsdatum|geboren|geb\.?|birth\s*date|dob)\s*[:#-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b'
)
_PERSON_NAME_CONTEXT_RE = re.compile(
    r'(?i)\b(kunde|kundin|name|ansprechpartner(?:in)?|kontaktperson|inhaber(?:in)?)\s*[:#-]?\s+'
    r'([A-ZÄÖÜ][a-zäöüß-]{1,30}\s+[A-ZÄÖÜ][a-zäöüß-]{1,30}(?:\s+[A-ZÄÖÜ][a-zäöüß-]{1,30})?)'
)
_GERMAN_ADDRESS_RE = re.compile(
    r'\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]{2,}'
    r'(?:straße|str\.|weg|platz|allee|gasse|ring|damm|ufer)\s+\d{1,4}[a-zA-Z]?\b'
)


def _ipv4_valid(candidate: str) -> bool:
    try:
        return all(0 <= int(part) <= 255 for part in candidate.split('.'))
    except ValueError:
        return False


def _tax_id_candidate_valid(candidate: str) -> bool:
    digits = re.sub(r'\D', '', candidate)
    return len(digits) == 11 and len(set(digits)) > 1


def detect_pii_types(text: str) -> set[str]:
    """Erkennt DSGVO-relevante Muster in einem Text und gibt Typ-Codes
    zurück. Kontextarme Felder wie Namen/Geburtsdaten werden nur erkannt,
    wenn typische Labels davorstehen, um False Positives zu senken."""
    if not isinstance(text, str):
        text = str(text)

    types: set[str] = set()

    if _EMAIL_RE.search(text):
        types.add("email")
    if _PHONE_RE.search(text):
        types.add("phone")
    if _VAT_ID_RE.search(text):
        types.add("vat_id")
    if _BIRTHDATE_CONTEXT_RE.search(text):
        types.add("birthdate")
    if _PERSON_NAME_CONTEXT_RE.search(text):
        types.add("person_name")
    if _GERMAN_ADDRESS_RE.search(text):
        types.add("address")

    for match in _IPV4_CANDIDATE_RE.finditer(text):
        if _ipv4_valid(match.group(0)):
            types.add("ip_address")
            break

    for match in _IBAN_CANDIDATE_RE.finditer(text):
        if _iban_checksum_valid(match.group(0)):
            types.add("iban")
            break

    for match in _CC_CANDIDATE_RE.finditer(text):
        digits_only = re.sub(r'[ -]', '', match.group(0))
        if _luhn_valid(digits_only):
            types.add("credit_card")
            break

    for match in _TAX_ID_CONTEXT_RE.finditer(text):
        if _tax_id_candidate_valid(match.group(2)):
            types.add("tax_id")
            break

    return types


def mask_pii(text: str) -> str:
    """
    Ersetzt erkennbare personenbezogene Daten (PII) durch Platzhalter.

    Erkannt werden: E-Mail-Adressen, Telefonnummern (mit Trennzeichen),
    IBANs (Mod-97-validiert) und Kreditkartennummern (Luhn-validiert).
    """
    if not isinstance(text, str):
        text = str(text)

    def _iban_replacer(match: re.Match) -> str:
        return '[IBAN MASKIERT]' if _iban_checksum_valid(match.group(0)) else match.group(0)

    def _cc_replacer(match: re.Match) -> str:
        digits_only = re.sub(r'[ -]', '', match.group(0))
        return '[CC MASKIERT]' if _luhn_valid(digits_only) else match.group(0)

    text = _EMAIL_RE.sub('[EMAIL MASKIERT]', text)
    text = _PERSON_NAME_CONTEXT_RE.sub(lambda m: f'{m.group(1)} [NAME MASKIERT]', text)
    text = _BIRTHDATE_CONTEXT_RE.sub(lambda m: f'{m.group(1)} [GEBURTSDATUM MASKIERT]', text)
    text = _IBAN_CANDIDATE_RE.sub(_iban_replacer, text)
    text = _CC_CANDIDATE_RE.sub(_cc_replacer, text)
    text = _TAX_ID_CONTEXT_RE.sub(
        lambda m: f'{m.group(1)} [STEUER-ID MASKIERT]' if _tax_id_candidate_valid(m.group(2)) else m.group(0),
        text,
    )
    text = _VAT_ID_RE.sub('[UST-ID MASKIERT]', text)
    text = _IPV4_CANDIDATE_RE.sub(
        lambda m: '[IP MASKIERT]' if _ipv4_valid(m.group(0)) else m.group(0),
        text,
    )
    text = _PHONE_RE.sub('[PHONE MASKIERT]', text)
    text = _GERMAN_ADDRESS_RE.sub('[ADRESSE MASKIERT]', text)

    return text


def sanitize_for_prompt(text: str) -> str:
    """
    Schützt vor Prompt Injection durch Bereinigung gefährlicher
    Sonderzeichen und Kürzung auf max. 50 Zeichen.

    Reihenfolge: PII-Maskierung -> Entfernen von Zeilenumbrüchen/Tabs
    (Audit SEC-5) -> Entfernen strukturell gefährlicher Zeichen -> Kürzung.
    """
    text = mask_pii(text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'--+', ' ', text)
    text = re.sub(r'[{}\[\]<>\'"`;]', '', text)
    return text.strip()[:50]


def escape_html(text) -> str:
    """Escaped HTML-Zeichen für die sichere PDF-Generierung via Jinja2."""
    if text is None:
        return ""
    return html.escape(str(text))


def scan_dataframe_for_pii(df, max_cell_len: int = 500) -> dict:
    """
    Rein informativer Scan über alle Text-Spalten eines DataFrames (zeigt
    dem Nutzer transparent, ob/wie viele E-Mail-/Telefon-artige Muster in
    der hochgeladenen Datei erkannt wurden). Maskiert NICHTS und verändert
    das DataFrame nicht. Die Vorschau-Tabelle maskiert erkannte Muster
    zusätzlich. Die wichtigste Schutzmaßnahme bleibt architektonisch:
    An Gemini gehen ausschließlich aggregierte Kennzahlen, nie Rohspalten.

    Nutzt bewusst dieselben, bereits gehärteten Muster wie mask_pii()
    (kein separates, zweites, schwächeres Regel-Set wie in einer
    Vorversion) - es gibt nur EINE PII-Erkennungslogik in der App.

    Gibt {"treffer_gesamt": int, "spalten_mit_treffern": list[str]} zurück.
    """
    treffer_gesamt = 0
    spalten_mit_treffern = []
    typen_gesamt: dict[str, int] = {}

    for spalte in df.columns:
        # BUGFIX (QA-Fund, verifiziert gegen pandas 3.0.2): `dtype != object`
        # erkennt String-Spalten NICHT zuverlaessig. pandas 3.0 gibt reinen
        # Text-Spalten standardmaessig dtype 'str' (StringDtype), nicht mehr
        # zwingend 'object' - `df[spalte].dtype == object` ist dafuer False,
        # obwohl es eine Textspalte ist. pd.api.types.is_string_dtype()
        # erkennt zuverlaessig BEIDE Faelle (object UND StringDtype). Das
        # war der tatsaechliche Grund, warum der PII-Scan die Notizen-Spalte
        # im Demo-Datensatz zunaechst nicht fand (QA-Testlauf: 53/54).
        if not pd.api.types.is_string_dtype(df[spalte]):
            continue

        werte = df[spalte].dropna().astype(str)
        if werte.empty:
            continue

        spalten_treffer = 0
        for wert in werte:
            zelle = wert[:max_cell_len]
            pii_types = detect_pii_types(zelle)
            if pii_types:
                spalten_treffer += 1
                for typ in pii_types:
                    typen_gesamt[typ] = typen_gesamt.get(typ, 0) + 1

        if spalten_treffer > 0:
            treffer_gesamt += spalten_treffer
            spalten_mit_treffern.append(str(spalte))

    return {
        "treffer_gesamt": treffer_gesamt,
        "spalten_mit_treffern": spalten_mit_treffern,
        "typen": sorted(typen_gesamt),
        "typen_anzahl": typen_gesamt,
    }
