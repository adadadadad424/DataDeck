"""
Datei-Einlese- und Datenbereinigungslogik für DataDeck.

ÄNDERUNGEN GEGENÜBER DER VORVERSION (siehe Audit):
- DATA-1: CSV-Trennzeichen wird jetzt automatisch erkannt (Komma ODER
  Semikolon) statt fest auf Komma zu bestehen.
- DATA-2: BOM-sichere Zeichenkodierung (utf-8-sig) als erster Versuch,
  zusätzlich cp1252-Fallback (in deutschen Excel-Exporten häufig).
- DATA-3: parse_currency() erkennt jetzt buchhalterische
  Klammer-Negativschreibweise, z.B. "(1.234,56)" -> -1234.56.
- DATA-4: parse_currency() erkennt jetzt nachgestellte Minuszeichen,
  z.B. "1.234,56-" -> -1234.56.
- DATA-5: numerisch bereits typisierte Spalten (Regelfall bei aus Excel
  gelesenen Zahlen) werden vektorisiert statt zeilenweise konvertiert.
- DATA-6: bool-Werte (Python-Subtyp von int) werden in Umsatz-/
  Gewinnspalten explizit als ungültig statt als 1.0/0.0 behandelt.
- DATA-7: das nicht unterstützte .xls-Altformat liefert jetzt eine klare
  Fehlermeldung statt eines unklaren openpyxl-Fehlers.
- DATA-8: vollständig identische Zeilen werden gezählt und angezeigt,
  aber bewusst NICHT automatisch entfernt (siehe Docstring dort).
- DATA-9: leere Kategorie-Strings (nicht nur NaN) werden auf "Unbekannt"
  normalisiert.
- Datei wird jetzt mit einem Zeilen-Limit (nrows=max_rows+1) statt
  vollständig eingelesen und danach gekürzt - spart Zeit/Speicher bei
  großen Dateien, die das jeweilige Plan-Limit deutlich überschreiten.

UNVERÄNDERT (siehe Audit DATA-10): die Kern-Heuristik zur Unterscheidung
von Tausender-/Dezimaltrennzeichen wurde gegen alle in der
Originalanforderung genannten Testfälle geprüft und ist korrekt - hier
wurde bewusst NICHTS geändert.
"""

import io
import os
import re
import csv
import unicodedata
import zipfile

import numpy as np
import pandas as pd


DEFAULT_MAX_COLUMNS = 250
DEFAULT_MAX_XLSX_SHEETS = 50
DEFAULT_MAX_XLSX_UNCOMPRESSED_MB = 250


def _positive_env_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, min(value, maximum))


def _excel_column_number(reference: str) -> int:
    letters = "".join(char for char in reference.upper() if char.isalpha())
    result = 0
    for char in letters:
        result = result * 26 + ord(char) - 64
    return result


def _validate_csv_content(file_content: bytes, max_columns: int) -> None:
    sample = file_content[:1_000_000]
    if b"\x00" in sample:
        raise ValueError("Die CSV-Datei enthält Binärdaten und wurde aus Sicherheitsgründen abgelehnt.")

    control_bytes = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    if sample and control_bytes / len(sample) > 0.01:
        raise ValueError("Die Datei sieht nicht wie eine gültige Text-CSV aus.")

    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            text = sample.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        raise ValueError("Die CSV-Datei konnte nicht als Text gelesen werden.")

    detected = _detect_csv_header(text)
    delimiter = detected[1] if detected else None
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    try:
        widest = max((len(row) for row in list(csv.reader(io.StringIO(text), delimiter=delimiter))[:50]), default=0)
    except csv.Error as error:
        raise ValueError("Die CSV-Struktur ist beschädigt oder unvollständig.") from error
    if widest > max_columns:
        raise ValueError(f"Die Datei überschreitet das Spaltenlimit von {max_columns} Spalten.")


def _validate_xlsx_container(file_content: bytes, max_columns: int) -> None:
    if not file_content.startswith(b"PK"):
        raise ValueError("Der Dateiinhalt entspricht nicht dem XLSX-Format.")

    max_sheets = _positive_env_int("MAX_XLSX_SHEETS", DEFAULT_MAX_XLSX_SHEETS, 200)
    max_uncompressed = _positive_env_int(
        "MAX_XLSX_UNCOMPRESSED_MB", DEFAULT_MAX_XLSX_UNCOMPRESSED_MB, 1000
    ) * 1024 * 1024
    try:
        with zipfile.ZipFile(io.BytesIO(file_content)) as archive:
            entries = archive.infolist()
            if len(entries) > 5_000:
                raise ValueError("Die XLSX-Datei enthält ungewöhnlich viele interne Dateien.")
            total_uncompressed = sum(entry.file_size for entry in entries)
            if total_uncompressed > max_uncompressed:
                raise ValueError("Die entpackte XLSX-Datei überschreitet das Sicherheitslimit.")
            for entry in entries:
                if entry.file_size > 100 * 1024 * 1024:
                    raise ValueError("Ein interner XLSX-Bestandteil ist ungewöhnlich groß.")
                if entry.file_size > 1_000_000 and entry.file_size > max(1, entry.compress_size) * 200:
                    raise ValueError("Die XLSX-Datei weist ein verdächtiges Kompressionsverhältnis auf.")

            names = [entry.filename.lower() for entry in entries]
            if any("vbaproject.bin" in name or name.startswith("xl/externallinks/") for name in names):
                raise ValueError("Makros oder externe Excel-Verknüpfungen werden nicht verarbeitet.")
            sheet_entries = [entry for entry in entries if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", entry.filename.lower())]
            if len(sheet_entries) > max_sheets:
                raise ValueError(f"Die XLSX-Datei überschreitet das Limit von {max_sheets} Tabellenblättern.")
            for entry in sheet_entries:
                with archive.open(entry) as stream:
                    prefix = stream.read(65_536).decode("utf-8", errors="ignore")
                dimension = re.search(r'<dimension\s+ref="(?:[^:"]+:)?([A-Z]+\d+)"', prefix)
                if dimension and _excel_column_number(dimension.group(1)) > max_columns:
                    raise ValueError(f"Die Datei überschreitet das Spaltenlimit von {max_columns} Spalten.")
    except zipfile.BadZipFile as error:
        raise ValueError("Der Dateiinhalt entspricht keiner gültigen XLSX-Datei.") from error


_CSV_HEADER_REVENUE_HINTS = [
    "umsatz", "revenue", "sales", "mrr", "arr", "monthly recurring revenue",
    "subscription revenue", "amount", "betrag", "net amount",
]
_CSV_HEADER_PROFIT_HINTS = [
    "gewinn", "profit", "net income", "gross profit", "ebitda", "deckungsbeitrag",
]
_CSV_HEADER_COST_HINTS = [
    "kosten", "cost", "costs", "cogs", "expense", "expenses", "cac",
    "cost of goods sold",
]
_CSV_HEADER_CATEGORY_HINTS = [
    "category", "kategorie", "product", "produkt", "plan", "tier", "segment",
    "customer", "kunde", "cohort", "country", "industry",
]


def parse_currency(val) -> float | None:
    """
    Parst internationale Finanzwerte.
    Behandelt Tausendertrennzeichen robust ohne US-/DE-Verwechslung.

    Unterstützt u.a.:
      1.234,56   1,234.56   1234,56   1234.56   1234
      1 234,56   1 234.56   € 1.234,56   $1,234.56   £1,234.56
      -1.234,56  -1,234.56  1.234,56-   (1.234,56)

    GRENZE (unverändert, Audit DATA-10): Bei genau einem Trennzeichen mit
    exakt 3 Nachkommastellen (z.B. "1.234" oder "1,234") wird dies als
    Tausendertrennzeichen gewertet (Ergebnis: 1234), da Finanzbeträge in
    der Praxis so gut wie nie exakt 3 Dezimalstellen haben. Diese Fälle
    sind ohne Locale-Information inhärent mehrdeutig - das ist eine
    bewusste, dokumentierte Design-Entscheidung, kein Bug.
    """
    if pd.isna(val):
        return None

    if isinstance(val, bool):
        # Audit DATA-6: bool ist in Python ein int-Subtyp (True == 1) -
        # ohne diese Prüfung würde ein versehentlicher Boolean-Wert in
        # einer Umsatz-/Gewinnspalte still zu 1.0/0.0.
        return None

    if isinstance(val, (int, float)):
        return float(val)

    val_str = str(val).strip()

    if not val_str:
        return None

    is_negative = False

    # Audit DATA-3: buchhalterische Klammer-Notation für negative Werte.
    # Muss VOR dem Zeichen-Filter unten geprüft werden, da dieser
    # Klammern entfernen würde.
    if val_str.startswith('(') and val_str.endswith(')'):
        is_negative = True
        val_str = val_str[1:-1].strip()

    val_str = re.sub(r'[^\d.,-]', '', val_str)

    if not val_str:
        return None

    # Audit DATA-4: nachgestelltes Minuszeichen. float() akzeptiert nur
    # führende Minuszeichen, daher hier vorher umhängen.
    if val_str.endswith('-'):
        is_negative = True
        val_str = val_str[:-1]

    if val_str.startswith('-'):
        is_negative = True
        val_str = val_str[1:]

    if not val_str:
        return None

    last_comma = val_str.rfind(',')
    last_dot = val_str.rfind('.')

    if last_comma != -1 and last_dot != -1:
        if last_comma > last_dot:
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            val_str = val_str.replace(',', '')

    elif last_comma != -1:
        parts = val_str.split(',')

        if len(parts) > 2 or len(parts[-1]) == 3:
            val_str = val_str.replace(',', '')
        else:
            val_str = val_str.replace(',', '.')

    elif last_dot != -1:
        parts = val_str.split('.')

        if len(parts) > 2 or (len(parts[-1]) == 3 and len(parts) == 2):
            val_str = val_str.replace('.', '')

    try:
        result = float(val_str)
    except ValueError:
        return None

    if result == 0:
        return 0.0

    return -result if is_negative else result


def _parse_currency_series(series: pd.Series) -> pd.Series:
    """
    Wandelt eine Spalte robust in float um. Bereits rein numerische
    Spalten (Regelfall bei aus Excel gelesenen Zahlen) werden vektorisiert
    konvertiert statt zeilenweise über parse_currency() - bei großen
    Dateien spürbar schneller (Audit DATA-5) und deckt zugleich
    numpy-Zahlentypen zuverlässig ab.
    """
    if pd.api.types.is_bool_dtype(series):
        return pd.Series([None] * len(series), index=series.index, dtype=float)
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return series.apply(parse_currency)


def _normalize_column_name(value) -> str:
    text = str(value).lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_column(
    df: pd.DataFrame,
    possible_names: list,
    reject_names: list | None = None,
) -> str | None:
    """Sucht Spalten. Zuerst exakter Match, dann Wort-/Substring-Match.

    Spaltennamen werden normalisiert, damit reale Exporte mit Varianten wie
    "Netto-Betrag", "Umsatzerlöse" oder "Gross Profit" zuverlässiger
    erkannt werden.
    """
    columns_lower = {
        _normalize_column_name(col): col
        for col in df.columns
    }
    aliases = [_normalize_column_name(alias) for alias in possible_names]
    rejects = [_normalize_column_name(alias) for alias in (reject_names or [])]

    def rejected(col_lower: str) -> bool:
        return any(
            reject and (re.search(rf"\b{re.escape(reject)}\b", col_lower) or reject in col_lower)
            for reject in rejects
        )

    for col_lower, orig_col in columns_lower.items():
        if rejected(col_lower):
            continue
        if col_lower in aliases:
            return orig_col

    for col_lower, orig_col in columns_lower.items():
        if rejected(col_lower):
            continue
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", col_lower) or alias in col_lower:
                return orig_col

    return None


def _mapping_confidence(column, aliases: list, manually_selected: bool = False) -> str:
    """Bewertet nur die Sicherheit der Namenszuordnung, nicht den Inhalt."""
    if not column:
        return "nicht_verfuegbar"
    if manually_selected:
        return "bestaetigt"
    normalized = _normalize_column_name(column)
    normalized_aliases = [_normalize_column_name(alias) for alias in aliases]
    if normalized in normalized_aliases:
        return "hoch"
    if any(re.search(rf"\b{re.escape(alias)}\b", normalized) for alias in normalized_aliases):
        return "mittel"
    return "niedrig"


def assess_data_quality(
    raw_df: pd.DataFrame,
    clean_df: pd.DataFrame,
    warnings: dict,
) -> dict:
    """Erzeugt einen nachvollziehbaren, rein deterministischen Qualitätscheck."""
    total_rows = int(len(raw_df))
    total_cells = max(1, int(raw_df.shape[0] * raw_df.shape[1]))
    missing_cells = int(raw_df.isna().sum().sum())
    invalid_numeric = int(warnings.get("invalid_umsatz", 0))
    if not warnings.get("revenue_only_mode"):
        invalid_numeric += int(warnings.get("invalid_gewinn", 0))

    negative_revenue = int((clean_df["Umsatz_Clean"] < 0).sum())
    negative_profit = (
        int((clean_df["Gewinn_Clean"] < 0).sum())
        if clean_df["Gewinn_Clean"].notna().any() else 0
    )

    outlier_count = 0
    revenue = clean_df["Umsatz_Clean"].dropna()
    if len(revenue) >= 8:
        q1, q3 = revenue.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr > 0:
            outlier_count = int(((revenue < q1 - 3 * iqr) | (revenue > q3 + 3 * iqr)).sum())

    invalid_dates = int(warnings.get("invalid_date", 0))
    date_columns = [
        col for col in raw_df.columns
        if re.search(r"\b(date|datum|zeitraum|period|monat|month|jahr|year)\b", _normalize_column_name(col))
    ]
    for col in date_columns:
        values = raw_df[col].dropna()
        if not values.empty:
            parsed = pd.to_datetime(values, errors="coerce")
            invalid_dates = max(invalid_dates, int(parsed.isna().sum()))

    currencies = set()
    for col in raw_df.select_dtypes(include=["object", "string"]).columns:
        sample = " ".join(raw_df[col].dropna().astype(str).head(500).tolist())
        symbol_map = {"€": "EUR", "$": "USD", "£": "GBP"}
        currencies.update(code for symbol, code in symbol_map.items() if symbol in sample)
        currencies.update(
            match.upper()
            for match in re.findall(r"\b(EUR|USD|GBP|CHF)\b", sample, flags=re.IGNORECASE)
        )

    completeness = max(0.0, min(1.0, 1.0 - (missing_cells / total_cells)))
    issues = []
    if warnings.get("revenue_only_mode"):
        issues.append({
            "severity": "warning",
            "title": "Kosteninformationen fehlen",
            "detail": "Gewinn, Marge und Profitabilitätsvergleiche sind nicht berechenbar.",
        })
    if invalid_numeric:
        issues.append({
            "severity": "warning",
            "title": "Nicht lesbare Finanzwerte",
            "detail": f"{invalid_numeric} Werte wurden von der Analyse ausgeschlossen.",
        })
    if warnings.get("duplicate_rows"):
        issues.append({
            "severity": "info",
            "title": "Mögliche Duplikate",
            "detail": f"{warnings['duplicate_rows']} vollständig identische Zeilen wurden erkannt und nicht automatisch entfernt.",
        })
    if invalid_dates:
        issues.append({
            "severity": "warning",
            "title": "Ungültige Datumswerte",
            "detail": f"{invalid_dates} Werte in Datumsspalten konnten nicht gelesen werden.",
        })
    if len(currencies) > 1:
        issues.append({
            "severity": "warning",
            "title": "Mehrere Währungen erkannt",
            "detail": (
                "Gefundene Währungen: " + ", ".join(sorted(currencies))
                + ". Ohne Wechselkurse werden keine Finanzsummen oder Rankings gebildet."
            ),
        })
    if outlier_count:
        issues.append({
            "severity": "info",
            "title": "Mögliche Ausreißer",
            "detail": f"{outlier_count} Umsatzwerte liegen deutlich außerhalb der üblichen Verteilung.",
        })
    if negative_revenue:
        issues.append({
            "severity": "info",
            "title": "Negative Umsätze",
            "detail": f"{negative_revenue} negative Umsatzwerte können Gutschriften oder Korrekturen darstellen.",
        })

    for detail in warnings.get("mapping_warnings", []):
        issues.append({
            "severity": "warning",
            "title": "Spaltenzuordnung prüfen",
            "detail": detail,
        })

    if warnings.get("confirmation_required"):
        labels = {
            "umsatz": "Umsatz", "gewinn": "Gewinn", "kosten": "Kosten",
            "kategorie": "Kategorie", "datum": "Datum",
        }
        uncertain = ", ".join(
            labels.get(name, name) for name in warnings["confirmation_required"]
        )
        issues.append({
            "severity": "warning",
            "title": "Automatische Zuordnung bestätigen",
            "detail": f"Nur mittlere oder niedrige Sicherheit bei: {uncertain}.",
        })

    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    excluded_share = invalid_numeric / max(1, total_rows)
    if len(currencies) > 1 or excluded_share > 0.1 or invalid_dates > max(5, total_rows * 0.1):
        level = "nicht_ausreichend"
    elif warnings.get("revenue_only_mode") or len(warnings.get("mapping_warnings", [])) > 1:
        level = "eingeschraenkt"
    elif warning_count or completeness < 0.9:
        level = "mittel"
    else:
        level = "hoch"

    return {
        "level": level,
        "rows": total_rows,
        "columns": int(raw_df.shape[1]),
        "missing_cells": missing_cells,
        "missing_share": missing_cells / total_cells,
        "completeness": completeness,
        "invalid_numeric": invalid_numeric,
        "invalid_dates": invalid_dates,
        "duplicate_rows": int(warnings.get("duplicate_rows", 0)),
        "negative_revenue": negative_revenue,
        "negative_profit": negative_profit,
        "outlier_count": outlier_count,
        "currencies": sorted(currencies),
        "multiple_currencies": len(currencies) > 1,
        "issues": issues,
    }


def _format_detected_columns(df: pd.DataFrame, max_cols: int = 12) -> str:
    columns = [str(col) for col in df.columns[:max_cols]]
    suffix = " …" if len(df.columns) > max_cols else ""
    return ", ".join(columns) + suffix


def _looks_like_alias(value, aliases: list, reject_names: list | None = None) -> bool:
    normalized = _normalize_column_name(value)
    if not normalized:
        return False
    rejects = [_normalize_column_name(alias) for alias in (reject_names or [])]
    if any(reject and (re.search(rf"\b{re.escape(reject)}\b", normalized) or reject in normalized) for reject in rejects):
        return False
    for alias in [_normalize_column_name(alias) for alias in aliases]:
        if alias and (normalized == alias or re.search(rf"\b{re.escape(alias)}\b", normalized) or alias in normalized):
            return True
    return False


def _header_score(values: list) -> int:
    has_revenue = any(_looks_like_alias(value, _CSV_HEADER_REVENUE_HINTS, _CSV_HEADER_PROFIT_HINTS + _CSV_HEADER_COST_HINTS) for value in values)
    has_profit = any(_looks_like_alias(value, _CSV_HEADER_PROFIT_HINTS, _CSV_HEADER_COST_HINTS) for value in values)
    has_cost = any(_looks_like_alias(value, _CSV_HEADER_COST_HINTS) for value in values)
    has_category = any(_looks_like_alias(value, _CSV_HEADER_CATEGORY_HINTS) for value in values)
    return int(has_revenue) * 3 + int(has_profit or has_cost) * 3 + int(has_category)


def _detect_csv_header(text: str, max_scan_rows: int = 500) -> tuple[int, str] | None:
    lines = text.splitlines()
    delimiters = [",", ";", "\t", "|"]
    best: tuple[int, str, int] | None = None

    for delimiter in delimiters:
        for idx, line in enumerate(lines[:max_scan_rows]):
            try:
                values = next(csv.reader([line], delimiter=delimiter))
            except csv.Error:
                continue
            values = [value.strip() for value in values if value.strip()]
            if len(values) < 2:
                continue
            score = _header_score(values)
            if score >= 3 and (best is None or score > best[2]):
                best = (idx, delimiter, score)

    if best is None:
        return None
    return best[0], best[1]


def _promote_embedded_header(
    df: pd.DataFrame,
    umsatz_aliases: list,
    gewinn_aliases: list,
    kosten_aliases: list,
    kategorie_aliases: list,
    max_scan_rows: int = 500,
) -> tuple[pd.DataFrame, bool]:
    """Findet Export-Dateien mit Titel-/Metadatenzeilen vor der echten
    Kopfzeile, z.B. A1 = "Synthetic Micro SaaS customer test data" und die
    eigentlichen Spaltennamen erst in Zeile 2/3."""
    scan_limit = min(max_scan_rows, len(df))
    best_index = None
    best_score = 0

    for idx in range(scan_limit):
        row_values = [value for value in df.iloc[idx].tolist() if str(value).strip() and str(value).lower() != "nan"]
        if not row_values:
            continue

        has_revenue = any(_looks_like_alias(value, umsatz_aliases, gewinn_aliases + kosten_aliases) for value in row_values)
        has_profit = any(_looks_like_alias(value, gewinn_aliases, kosten_aliases) for value in row_values)
        has_cost = any(_looks_like_alias(value, kosten_aliases) for value in row_values)
        has_category = any(_looks_like_alias(value, kategorie_aliases) for value in row_values)
        score = int(has_revenue) * 3 + int(has_profit or has_cost) * 3 + int(has_category)

        if score > best_score:
            best_score = score
            best_index = idx

    if best_index is None or best_score < 3:
        return df, False

    promoted = df.iloc[best_index + 1:].copy()
    promoted.columns = [
        str(value).strip() if str(value).strip() and str(value).lower() != "nan" else f"Unnamed: {i}"
        for i, value in enumerate(df.iloc[best_index].tolist())
    ]
    promoted = promoted.reset_index(drop=True)
    promoted.attrs = df.attrs.copy()
    return promoted, True


def _manual_column(
    df: pd.DataFrame,
    column_mapping: dict | None,
    key: str,
) -> str | None:
    if not column_mapping:
        return None
    selected = column_mapping.get(key)
    if selected in (None, "", "__auto__", "__none__"):
        return None
    if selected not in df.columns:
        raise ValueError(
            f"Die manuell gewählte Spalte '{selected}' für '{key}' "
            "existiert in dieser Datei nicht mehr."
        )
    return selected


def _read_csv_robust(file_content: bytes, nrows: int) -> pd.DataFrame:
    """
    Liest eine CSV-Datei robust ein (Audit DATA-1, DATA-2):
    - erkennt automatisch das Trennzeichen (Komma ODER Semikolon - in
      deutschen Excel-Exporten mit Dezimalkomma ist Semikolon Standard,
      da Komma dort als Dezimaltrennzeichen reserviert ist)
    - versucht mehrere Zeichenkodierungen inkl. BOM-Handling (utf-8-sig)
      und Windows-1252 (in deutschen Excel-Exporten häufig)
    - liest höchstens `nrows` Zeilen ein
    """
    last_error: Exception | None = None

    for encoding in ('utf-8-sig', 'cp1252', 'latin1'):
        try:
            text = file_content.decode(encoding)
            detected_header = _detect_csv_header(text)
            if detected_header:
                skiprows, delimiter = detected_header
                return pd.read_csv(
                    io.StringIO(text),
                    sep=delimiter,
                    skiprows=skiprows,
                    nrows=nrows,
                )

            df = pd.read_csv(
                io.BytesIO(file_content),
                encoding=encoding,
                sep=None,
                engine='python',
                nrows=nrows,
            )
            if df.shape[1] < 2:
                # Auto-Erkennung hat vermutlich das falsche Trennzeichen
                # geraten - expliziter Versuch mit Semikolon.
                try:
                    df_semicolon = pd.read_csv(
                        io.BytesIO(file_content),
                        encoding=encoding,
                        sep=';',
                        nrows=nrows,
                    )
                    if df_semicolon.shape[1] >= 2:
                        return df_semicolon
                except (pd.errors.ParserError, pd.errors.EmptyDataError):
                    pass
            return df
        except UnicodeDecodeError as e:
            last_error = e
            continue
        except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
            last_error = e
            continue

    raise ValueError(
        "Die CSV-Datei konnte nicht gelesen werden. Bitte prüfe "
        "Zeichenkodierung und Trennzeichen (Komma oder Semikolon)."
    ) from last_error


def load_and_validate_file(
    file_content: bytes,
    file_name: str,
    is_premium: bool
) -> tuple[pd.DataFrame, bool, int]:
    """
    Validiert Limit und lädt Daten. Liest höchstens so viele Zeilen wie im
    aktuellen Plan erlaubt (Performance bei großen Dateien).

    Gibt (DataFrame, wurde_gekürzt, max_rows) zurück. Die Kürzungs-Warnung
    wird bewusst NICHT hier per st.warning ausgegeben, sondern von main.py
    anhand des Rückgabewerts - hält die Cache-Semantik dieser Funktion
    eindeutig.
    """

    max_mb = _positive_env_int("MAX_UPLOAD_SIZE_MB", 50, 500)
    max_columns = _positive_env_int("MAX_DATASET_COLUMNS", DEFAULT_MAX_COLUMNS, 2_000)

    if not file_content:
        raise ValueError("Die hochgeladene Datei ist leer (0 Byte).")

    if len(file_content) > max_mb * 1024 * 1024:
        raise ValueError(
            f"Die Datei überschreitet das Systemlimit von {max_mb} MB."
        )

    max_rows = 100_000 if is_premium else 1_000
    name_lower = file_name.lower()

    if name_lower.endswith('.csv'):
        _validate_csv_content(file_content, max_columns)
        df = _read_csv_robust(file_content, nrows=max_rows + 1)

    elif name_lower.endswith('.xlsx'):
        _validate_xlsx_container(file_content, max_columns)
        try:
            excel_file = pd.ExcelFile(
                io.BytesIO(file_content),
                engine='openpyxl',
                engine_kwargs={"read_only": True, "data_only": True, "keep_links": False},
            )
            first_df: pd.DataFrame | None = None
            first_error: Exception | None = None

            for sheet_name in excel_file.sheet_names:
                try:
                    candidate = pd.read_excel(
                        excel_file,
                        sheet_name=sheet_name,
                        nrows=max_rows + 1,
                    )
                except Exception as sheet_error:
                    if first_error is None:
                        first_error = sheet_error
                    continue

                if first_df is None:
                    first_df = candidate

                if candidate.empty or len(candidate.columns) == 0:
                    continue

                try:
                    clean_and_prepare_data(candidate)
                    candidate.attrs["source_sheet"] = str(sheet_name)
                    candidate.attrs["sheet_names"] = [str(name) for name in excel_file.sheet_names]
                    df = candidate
                    break
                except ValueError:
                    continue
            else:
                if first_df is not None:
                    df = first_df
                    df.attrs["source_sheet"] = str(excel_file.sheet_names[0])
                    df.attrs["sheet_names"] = [str(name) for name in excel_file.sheet_names]
                else:
                    raise first_error or ValueError("Keine lesbaren Tabellenblaetter gefunden.")
        except Exception as e:
            raise ValueError(
                "Die XLSX-Datei konnte nicht gelesen werden. Bitte "
                "prüfe, ob es sich um eine gültige, nicht beschädigte "
                "Excel-Datei handelt."
            ) from e

    elif name_lower.endswith('.xls'):
        # Audit DATA-7: .xls wurde vom ursprünglichen Code formal
        # akzeptiert, aber openpyxl kann das alte Binärformat nicht
        # lesen - das führte zu einem unklaren technischen Fehler statt
        # einer klaren Nutzermeldung.
        raise ValueError(
            "Das alte .xls-Format wird nicht unterstützt. Bitte "
            "speichere die Datei im .xlsx-Format und lade sie erneut "
            "hoch."
        )

    else:
        raise ValueError(
            "Bitte lade ausschließlich CSV- oder XLSX-Dateien hoch."
        )

    if df.empty or len(df.columns) == 0:
        raise ValueError(
            "Die hochgeladene Datei enthält keine Datenzeilen."
        )

    if len(df.columns) > max_columns:
        raise ValueError(f"Die Datei überschreitet das Spaltenlimit von {max_columns} Spalten.")

    was_truncated = len(df) > max_rows
    if was_truncated:
        df = df.head(max_rows).copy()

    return df, was_truncated, max_rows


def clean_and_prepare_data(
    df: pd.DataFrame,
    column_mapping: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Bereinigt und bereitet Finanzdaten auf."""

    # Keyword-Listen zentral an EINER Stelle (Audit: v3.2 hatte dieselbe
    # Erkennung dreifach - main.py, ai_insights.py, report_builder.py -
    # leicht unterschiedlich dupliziert; hier gibt es nur diese eine
    # Quelle, die von main.py/ai_insights.py/report_builder.py über das
    # bereits berechnete kpis-Dict konsumiert wird, nie erneut ausgeführt).
    # "margin" wurde bewusst ENTFERNT (stand in einer Vorversion in
    # gewinn_aliases): Substring-Match hätte z.B. eine Spalte
    # "error_margin" fälschlich als Gewinnspalte erkennen können - kein
    # Bestandteil der explizit geforderten Gewinn-Keywords.
    umsatz_aliases = [
        "umsatz",
        "gesamtumsatz",
        "umsatzerlos",
        "umsatzerlose",
        "erlös",
        "net sales",
        "gross sales",
        "erlöse",
        "erloese",
        "einnahmen",
        "einnahme",
        "verkauf",
        "verkaufe",
        "verkaufswert",
        "rechnungsbetrag",
        "betrag netto",
        "betrag",
        "netto betrag",
        "netto",
        "brutto",
        "net amount",
        "amount",
        "invoice amount",
        "order total",
        "total amount",
        "sales amount",
        "mrr",
        "arr",
        "monthly recurring revenue",
        "annual recurring revenue",
        "recurring revenue",
        "subscription revenue",
        "monthly revenue",
        "revenue monthly",
        "revenue eur",
        "revenue usd",
        "paid amount",
        "payment amount",
        "invoice value",
        "turnover",
        "revenue",
        "sales"
    ]

    gewinn_aliases = [
        "gewinn",
        "reingewinn",
        "bruttogewinn",
        "rohertrag",
        "deckungsbeitrag",
        "db",
        "ergebnis",
        "betriebsergebnis",
        "profit",
        "gross profit",
        "net profit",
        "net income",
        "operating income",
        "contribution margin",
        "profit loss",
        "ebitda"
    ]

    kosten_aliases = [
        "kosten",
        "cost",
        "costs",
        "cogs",
        "aufwand",
        "aufwaende",
        "aufwendungen",
        "ausgaben",
        "expense",
        "expenses",
        "wareneinsatz",
        "einkauf",
        "einkaufspreis",
        "materialkosten",
        "produktkosten",
        "herstellkosten",
        "cost of goods sold",
        "cac",
        "customer acquisition cost",
        "hosting cost",
        "support cost",
        "payment fees",
        "platform cost",
    ]

    kategorie_aliases = [
        "produkt",
        "kategorie",
        "category",
        "product",
        "artikel",
        "item",
        "bezeichnung",
        "name",
        "kunde",
        "kundengruppe",
        "segment",
        "customer segment",
        "customer",
        "company",
        "tenant",
        "subscription",
        "plan",
        "pricing plan",
        "subscription plan",
        "tier",
        "cohort",
        "industry",
        "country",
        "department",
        "abteilung",
        "konto",
        "account",
        "channel",
        "kanal",
        "automarke",
        "fahrzeug",
        "bereich"
    ]

    datum_aliases = [
        "datum", "date", "invoice date", "order date", "transaction date",
        "booking date", "paid date", "period", "period start", "monat",
        "month", "jahr", "year", "zeitraum", "created at",
    ]

    manual_umsatz = _manual_column(df, column_mapping, "umsatz")
    manual_gewinn = _manual_column(df, column_mapping, "gewinn")
    manual_kosten = _manual_column(df, column_mapping, "kosten")
    manual_kategorie = _manual_column(df, column_mapping, "kategorie")
    manual_datum = _manual_column(df, column_mapping, "datum")
    force_no_gewinn = bool(column_mapping and column_mapping.get("gewinn") == "__none__")
    force_no_kosten = bool(column_mapping and column_mapping.get("kosten") == "__none__")
    force_no_kategorie = bool(column_mapping and column_mapping.get("kategorie") == "__none__")
    force_no_datum = bool(column_mapping and column_mapping.get("datum") == "__none__")

    umsatz_col = manual_umsatz or find_column(df, umsatz_aliases, reject_names=gewinn_aliases + kosten_aliases)
    gewinn_col = None if force_no_gewinn else manual_gewinn or find_column(df, gewinn_aliases, reject_names=kosten_aliases)
    kosten_col = None if force_no_kosten else manual_kosten or find_column(df, kosten_aliases)
    kategorie_col = None if force_no_kategorie else manual_kategorie or find_column(df, kategorie_aliases)
    datum_col = None if force_no_datum else manual_datum or find_column(df, datum_aliases)
    header_promoted = False

    if not column_mapping and (not umsatz_col or (not gewinn_col and not kosten_col)):
        df, header_promoted = _promote_embedded_header(
            df, umsatz_aliases, gewinn_aliases, kosten_aliases, kategorie_aliases
        )
        umsatz_col = find_column(df, umsatz_aliases, reject_names=gewinn_aliases + kosten_aliases)
        gewinn_col = find_column(df, gewinn_aliases, reject_names=kosten_aliases)
        kosten_col = find_column(df, kosten_aliases)
        kategorie_col = find_column(df, kategorie_aliases)
        datum_col = find_column(df, datum_aliases)

    if not umsatz_col:
        detected = _format_detected_columns(df)
        raise ValueError(
            "Konnte keine passenden Spalten für 'Umsatz' "
            "und 'Gewinn' oder 'Kosten' finden. Bitte Datei-Kopfzeilen "
            f"überprüfen. Erkannte Spalten: {detected}."
        )

    mapping_warnings = []
    if umsatz_col == gewinn_col or umsatz_col == kosten_col:
        if manual_umsatz and (manual_gewinn or manual_kosten):
            mapping_warnings.append(
                f"'{umsatz_col}' wurde mehreren Finanzkennzahlen zugeordnet. "
                "Dadurch können Gewinn oder Marge irreführend sein."
            )
        else:
            raise ValueError(
                "Die Spalten für Umsatz und Gewinn/Kosten wurden auf dieselbe "
                f"Spalte ('{umsatz_col}') erkannt. Bitte Spaltennamen in der "
                "Datei eindeutiger benennen."
            )

    # Audit DATA-8: nur zählen/anzeigen, NICHT automatisch entfernen - bei
    # Finanztransaktionsdaten können identische Zeilen legitim sein (z.B.
    # zwei getrennte, zufällig gleich hohe Verkäufe). Automatisches
    # Löschen würde den Umsatz stillschweigend unterschätzen.
    duplicate_count = int(df.duplicated().sum())

    df = df.copy()

    df['Umsatz_Clean'] = _parse_currency_series(df[umsatz_col])
    if gewinn_col:
        df['Gewinn_Clean'] = _parse_currency_series(df[gewinn_col])
        gewinn_source = str(gewinn_col)
        revenue_only_mode = False
    else:
        if kosten_col:
            kosten_values = _parse_currency_series(df[kosten_col]).abs()
            df['Gewinn_Clean'] = df['Umsatz_Clean'] - kosten_values
            gewinn_source = f"{umsatz_col} - {kosten_col}"
            revenue_only_mode = False
        else:
            # Ohne Gewinn- oder Kostenbasis gibt es keinen seriös
            # berechenbaren Gewinn. NaN ist hier absichtlich ein fachlicher
            # Zustand und kein technischer Fehler. Umsatz bleibt unabhängig
            # davon vollständig analysierbar.
            df['Gewinn_Clean'] = float('nan')
            gewinn_source = None
            revenue_only_mode = True

    invalid_umsatz = int(df['Umsatz_Clean'].isna().sum())
    invalid_gewinn = (
        0 if revenue_only_mode else int(df['Gewinn_Clean'].isna().sum())
    )

    required_numeric = ['Umsatz_Clean']
    if not revenue_only_mode:
        required_numeric.append('Gewinn_Clean')
    df = df.dropna(subset=required_numeric)

    if df.empty:
        raise ValueError(
            "Nach der Bereinigung ungültiger Währungsformate "
            "blieben keine verwertbaren Daten übrig."
        )

    if kategorie_col:
        # Audit DATA-9: fillna() erfasst keine leeren Strings (nur NaN) -
        # zusätzlich getrimmt und leere Strings auf "Unbekannt" gemappt.
        kategorie_series = (
            df[kategorie_col]
            .fillna("Unbekannt")
            .astype(str)
            .str.strip()
        )
        kategorie_series = kategorie_series.replace('', 'Unbekannt')
        df['Kategorie_Clean'] = kategorie_series
    else:
        df['Kategorie_Clean'] = "Allgemein"

    invalid_date = 0
    if datum_col:
        parsed_dates = pd.to_datetime(df[datum_col], errors="coerce")
        invalid_date = int(parsed_dates.isna().sum() - df[datum_col].isna().sum())
        df['Datum_Clean'] = parsed_dates

    for label, source in (("Umsatz", manual_umsatz), ("Gewinn", manual_gewinn), ("Kosten", manual_kosten)):
        if source:
            original = df[source].dropna()
            numeric_share = (
                float(_parse_currency_series(original).notna().mean())
                if not original.empty else 0.0
            )
            if numeric_share < 0.7:
                mapping_warnings.append(
                    f"Die manuell gewählte {label}-Spalte '{source}' enthält nur "
                    f"{numeric_share:.0%} lesbare Zahlenwerte."
                )

    if manual_datum:
        original_dates = df[manual_datum].dropna()
        date_share = (
            float(pd.to_datetime(original_dates, errors="coerce").notna().mean())
            if not original_dates.empty else 0.0
        )
        if date_share < 0.7:
            mapping_warnings.append(
                f"Die manuell gewählte Datumsspalte '{manual_datum}' enthält nur "
                f"{date_share:.0%} lesbare Datumswerte."
            )

    if manual_kategorie:
        category_values = df[manual_kategorie].dropna().astype(str).str.strip()
        if len(category_values) >= 20:
            uniqueness = category_values.nunique(dropna=True) / max(1, len(category_values))
            if uniqueness > 0.95:
                mapping_warnings.append(
                    f"Die Segmentspalte '{manual_kategorie}' besteht fast nur aus "
                    "Einzelwerten. Eine Kunden- oder Beleg-ID ist meist keine sinnvolle Kategorie."
                )

    if manual_gewinn and not revenue_only_mode and len(df) > 1:
        comparable = df[['Umsatz_Clean', 'Gewinn_Clean']].dropna()
        if not comparable.empty:
            identical_share = float(
                np.isclose(
                    comparable['Umsatz_Clean'].to_numpy(),
                    comparable['Gewinn_Clean'].to_numpy(),
                    rtol=1e-9,
                    atol=1e-9,
                ).mean()
            )
            if identical_share > 0.95:
                mapping_warnings.append(
                    "Umsatz und Gewinn sind in fast allen Zeilen identisch. Bitte prüfen, "
                    "ob wirklich eine Gewinnspalte gewählt wurde."
                )

    mapping_confidence = {
        "umsatz": _mapping_confidence(umsatz_col, umsatz_aliases, bool(manual_umsatz)),
        "gewinn": _mapping_confidence(gewinn_col, gewinn_aliases, bool(manual_gewinn)),
        "kosten": _mapping_confidence(kosten_col, kosten_aliases, bool(manual_kosten)),
        "kategorie": _mapping_confidence(kategorie_col, kategorie_aliases, bool(manual_kategorie)),
        "datum": _mapping_confidence(datum_col, datum_aliases, bool(manual_datum)),
    }
    confirmation_required = [
        name for name, confidence in mapping_confidence.items()
        if confidence in {"mittel", "niedrig"}
    ]

    warnings = {
        "invalid_umsatz": invalid_umsatz,
        "invalid_gewinn": invalid_gewinn,
        "duplicate_rows": duplicate_count,
        "umsatz_source": str(umsatz_col),
        "gewinn_source": gewinn_source,
        "kosten_source": str(kosten_col) if kosten_col else None,
        "kategorie_source": str(kategorie_col) if kategorie_col else None,
        "datum_source": str(datum_col) if datum_col else None,
        "invalid_date": max(0, invalid_date),
        "header_promoted": header_promoted,
        "revenue_only_mode": revenue_only_mode,
        "metric_status": {
            "umsatz": "gemessen",
            "gewinn": (
                "gemessen" if gewinn_col else
                "berechnet" if kosten_col else
                "nicht_berechenbar"
            ),
            "marge": "berechnet" if not revenue_only_mode else "nicht_berechenbar",
        },
        "analysis_limitations": (
            ["Keine Gewinn- oder Kosteninformationen vorhanden; Gewinn, Marge und Profitabilitäts-Rankings sind nicht berechenbar."]
            if revenue_only_mode else []
        ),
        "mapping_confidence": mapping_confidence,
        "confirmation_required": confirmation_required,
        "mapping_warnings": mapping_warnings,
        "source_sheet": df.attrs.get("source_sheet"),
        "sheet_names": list(df.attrs.get("sheet_names", [])),
    }

    return df, warnings
