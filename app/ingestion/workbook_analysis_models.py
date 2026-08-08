from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TableType(str, Enum):
    ENTITY_TABLE = "entity_table"
    REPORT = "report"
    SUMMARY = "summary"
    PIVOT = "pivot"
    DASHBOARD = "dashboard"
    MATRIX = "matrix"
    UNKNOWN = "unknown"


class ChunkStrategy(str, Enum):
    PER_ROW = "per_row"
    WHOLE_TABLE = "whole_table"
    GROUPED_ROWS = "grouped_rows"
    TIME_SERIES = "time_series"
    CUSTOM = "custom"


@dataclass(slots=True)
class SpreadsheetAnalysis:

    table_name: str

    description: str

    table_type: TableType

    chunk_strategy: ChunkStrategy

    confidence: float

    row_represents: str | None = None

    title_rows: list[int] = field(default_factory=list)

    header_rows: list[int] = field(default_factory=list)

    footer_rows: list[int] = field(default_factory=list)

    primary_columns: list[str] = field(default_factory=list)

    secondary_columns: list[str] = field(default_factory=list)

    money_columns: list[str] = field(default_factory=list)

    date_columns: list[str] = field(default_factory=list)

    identifier_columns: list[str] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)