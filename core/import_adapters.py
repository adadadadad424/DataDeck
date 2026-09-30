"""Format-neutral import contracts; external connectors can implement the same boundary later."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import pandas as pd

from .data_processing import inspect_file_structure, load_and_validate_file


class SemanticRole(StrEnum):
    DATE = "date"
    REVENUE = "revenue"
    COST = "cost"
    PROFIT = "profit"
    MARGIN = "margin"
    CUSTOMER = "customer"
    PRODUCT = "product"
    SEGMENT = "segment"
    REGION = "region"
    QUANTITY = "quantity"
    CURRENCY = "currency"


@dataclass(frozen=True)
class NormalizedDataset:
    frame: pd.DataFrame
    source_type: str
    source_name: str
    sheet_name: str | None
    header_row: int
    role_mapping: dict[SemanticRole, str]
    import_confidence: dict[str, str]
    warnings: tuple[str, ...] = ()


class InputAdapter(Protocol):
    source_type: str

    def inspect(self, content: bytes, source_name: str) -> dict: ...

    def authenticate(self, credentials: dict | None = None) -> None: ...

    def fetch_data(self, content: bytes, source_name: str) -> bytes: ...

    def normalize(
        self, content: bytes, source_name: str, *, premium: bool,
        sheet_name: str | None = None, header_row: int | None = None,
    ) -> tuple[pd.DataFrame, bool, int]: ...

    def validate(self, frame: pd.DataFrame) -> None: ...

    def load(
        self, content: bytes, source_name: str, *, premium: bool,
        sheet_name: str | None = None, header_row: int | None = None,
    ) -> tuple[pd.DataFrame, bool, int]: ...


class FileAdapter:
    def __init__(self, source_type: str):
        if source_type not in {"csv", "xlsx"}:
            raise ValueError("Nur CSV- und XLSX-Adapter sind aktuell verfügbar")
        self.source_type = source_type

    def inspect(self, content: bytes, source_name: str) -> dict:
        return inspect_file_structure(content, source_name)

    def authenticate(self, credentials: dict | None = None) -> None:
        if credentials:
            raise ValueError("Dateiimporte benötigen keine Zugangsdaten")

    def fetch_data(self, content: bytes, source_name: str) -> bytes:
        if not content:
            raise ValueError("Die Datenquelle ist leer")
        return bytes(content)

    def normalize(
        self, content: bytes, source_name: str, *, premium: bool,
        sheet_name: str | None = None, header_row: int | None = None,
    ) -> tuple[pd.DataFrame, bool, int]:
        return self.load(content, source_name, premium=premium, sheet_name=sheet_name, header_row=header_row)

    def validate(self, frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("Die normalisierte Datenquelle enthält keine Datensätze")

    def load(
        self, content: bytes, source_name: str, *, premium: bool,
        sheet_name: str | None = None, header_row: int | None = None,
    ) -> tuple[pd.DataFrame, bool, int]:
        return load_and_validate_file(
            content, source_name, premium, sheet_name=sheet_name, header_row=header_row
        )


class CSVAdapter(FileAdapter):
    def __init__(self):
        super().__init__("csv")


class ExcelAdapter(FileAdapter):
    def __init__(self):
        super().__init__("xlsx")


def adapter_for(source_name: str) -> InputAdapter:
    lower = source_name.lower()
    if lower.endswith(".csv"):
        return CSVAdapter()
    if lower.endswith(".xlsx"):
        return ExcelAdapter()
    raise ValueError("Für dieses Dateiformat ist kein Import-Adapter verfügbar")
