"""Real-world CSV/XLSX structure and format-neutral adapter regression tests."""

from __future__ import annotations

import io
import re
import unittest
import zipfile

import openpyxl

from core.data_processing import (
    clean_and_prepare_data,
    inspect_file_structure,
    load_and_validate_file,
)
from core.import_adapters import CSVAdapter, ExcelAdapter, SemanticRole, adapter_for


def workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    notes = workbook.active
    notes.title = "Hinweise"
    notes.append(["Monatsreport für Geschäftsführung"])
    data = workbook.create_sheet("Daten")
    data.append(["Vertraulich"])
    data.append([])
    data.append(["Segment", "Umsatz", "Kosten", "Datum"])
    data.append(["A", 100, 40, "01.03.2026"])
    data.append(["B", -20, -5, "02.03.2026"])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def workbook_without_dimension_bytes() -> bytes:
    source = workbook_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source), "r") as zin, zipfile.ZipFile(output, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet") and item.filename.endswith(".xml"):
                content = re.sub(br"<dimension[^>]*/>", b"", content, count=1)
            zout.writestr(item, content)
    return output.getvalue()


class ImportPipelineTests(unittest.TestCase):
    def test_01_ragged_csv_metadata_preview(self):
        content = (
            b"Synthetic customer export\n"
            b"Generated,2026-09-20\n"
            b"Segment,Revenue,Costs\n"
            b"Enterprise,1000,400\n"
        )
        inspection = inspect_file_structure(content, "messy.csv")
        sheet = inspection["sheets"][0]
        self.assertEqual(sheet["suggested_header_row"], 2)
        self.assertEqual(sheet["columns"], 3)

    def test_02_manual_csv_header_row(self):
        content = b"Report\nInternal\nSegment;Umsatz;Kosten\nA;1.234,56;234,56\n"
        frame, truncated, _ = load_and_validate_file(
            content, "german.csv", True, header_row=2,
        )
        clean, _ = clean_and_prepare_data(frame)
        self.assertFalse(truncated)
        self.assertAlmostEqual(clean["Umsatz_Clean"].sum(), 1234.56)
        self.assertAlmostEqual(clean["Gewinn_Clean"].sum(), 1000)

    def test_03_xlsx_lists_and_suggests_tabular_sheet(self):
        inspection = inspect_file_structure(workbook_bytes(), "messy.xlsx")
        self.assertEqual([sheet["name"] for sheet in inspection["sheets"]], ["Hinweise", "Daten"])
        self.assertEqual(inspection["suggested_sheet"], "Daten")
        data_sheet = next(sheet for sheet in inspection["sheets"] if sheet["name"] == "Daten")
        self.assertEqual(data_sheet["suggested_header_row"], 2)

    def test_03b_xlsx_without_dimension_metadata_is_supported(self):
        inspection = inspect_file_structure(workbook_without_dimension_bytes(), "no-dimension.xlsx")
        self.assertEqual(inspection["suggested_sheet"], "Daten")
        data_sheet = next(sheet for sheet in inspection["sheets"] if sheet["name"] == "Daten")
        self.assertEqual(data_sheet["suggested_header_row"], 2)
        self.assertGreaterEqual(data_sheet["columns"], 4)

    def test_04_explicit_xlsx_sheet_and_header(self):
        frame, truncated, _ = load_and_validate_file(
            workbook_bytes(), "messy.xlsx", True, sheet_name="Daten", header_row=2,
        )
        clean, warnings = clean_and_prepare_data(frame)
        self.assertFalse(truncated)
        self.assertEqual(warnings["source_sheet"], "Daten")
        self.assertEqual(clean["Umsatz_Clean"].sum(), 80)
        self.assertEqual(clean["Gewinn_Clean"].sum(), 45)

    def test_05_duplicate_and_empty_headers_are_safe(self):
        content = b"Umsatz,Umsatz,,Kosten\n100,ignored,,40\n"
        frame, _, _ = load_and_validate_file(content, "duplicate.csv", True, header_row=0)
        self.assertEqual(list(frame.columns), ["Umsatz", "Umsatz.1", "Kosten"])

    def test_06_adapter_selection(self):
        self.assertIsInstance(adapter_for("input.CSV"), CSVAdapter)
        self.assertIsInstance(adapter_for("input.xlsx"), ExcelAdapter)
        with self.assertRaises(ValueError):
            adapter_for("input.pdf")

    def test_07_semantic_roles_are_format_neutral(self):
        self.assertEqual(SemanticRole.REVENUE.value, "revenue")
        self.assertEqual(SemanticRole.CURRENCY.value, "currency")

    def test_08_csv_adapter_uses_common_pipeline(self):
        content = b"Segment,Revenue,Cost\nA,100,40\n"
        adapter = CSVAdapter()
        inspection = adapter.inspect(content, "input.csv")
        frame, truncated, _ = adapter.load(content, "input.csv", premium=True, header_row=0)
        self.assertEqual(inspection["kind"], "csv")
        self.assertFalse(truncated)
        self.assertEqual(len(frame), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
