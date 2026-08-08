from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ==========================================================
# Cell
# ==========================================================

@dataclass(slots=True)
class CellData:
    """
    Represents one physical Excel cell after normalization.
    """

    row: int
    column: int
    coordinate: str

    value: Any

    formula: str | None = None

    data_type: str | None = None

    number_format: str | None = None

    comment: str | None = None

    merged: bool = False

    hidden: bool = False

    bold: bool = False
    italic: bool = False

    fill_color: str | None = None

    font_color: str | None = None

    alignment: str | None = None


# ==========================================================
# Table Region
# ==========================================================

@dataclass(slots=True)
class TableRegion:
    """
    A rectangular block that appears to contain one logical table.

    The detector will create these before the LLM analyzes them.
    """

    sheet_name: str

    start_row: int
    end_row: int

    start_column: int
    end_column: int

    cells: list[list[CellData]]

    dataframe: Any

    title: str | None = None

    notes: list[str] = field(default_factory=list)


# ==========================================================
# Worksheet
# ==========================================================

@dataclass(slots=True)
class WorksheetFrame:
    """
    Represents an Excel worksheet.
    """

    name: str

    hidden: bool = False

    max_rows: int = 0
    max_columns: int = 0

    merged_ranges: list[str] = field(default_factory=list)

    frozen_panes: str | None = None

    cells: list[list[CellData]] = field(default_factory=list)

    table_regions: list[TableRegion] = field(default_factory=list)

    excel_tables: list[dict[str, Any]] = field(default_factory=list)

    sheet_index: int = 0

    row_heights: dict[int, float] = field(default_factory=dict)

    column_widths: dict[str, float] = field(default_factory=dict)


# ==========================================================
# Workbook
# ==========================================================

@dataclass(slots=True)
class WorkbookFrame:
    """
    Root object returned by workbook extraction.
    """

    filename: str

    sheets: list[WorksheetFrame] = field(default_factory=list)

    workbook_properties: dict[str, Any] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)

    def visible_sheets(self) -> list[WorksheetFrame]:
        return [s for s in self.sheets if not s.hidden]

    def all_tables(self) -> list[TableRegion]:
        tables: list[TableRegion] = []

        for sheet in self.sheets:
            tables.extend(sheet.table_regions)

        return tables
    
@dataclass
class DetectedTable:
    sheet_name: str

    start_row: int
    end_row: int

    start_column: int
    end_column: int

    title: str | None

    confidence: float

    source: str