from __future__ import annotations

import re
from typing import Any

import pandas as pd

from app.ingestion.workbook_models import (
    WorkbookFrame,
    WorksheetFrame,
    TableRegion,
    CellData,
)


# ==========================================================
# Public API
# ==========================================================

def extract_tables_from_analysis(
    workbook: WorkbookFrame,
    analysis: dict[str, Any],
) -> list[TableRegion]:
    """
    Uses the LLM workbook analysis to build TableRegion objects.

    The LLM has already identified:
        - sheet
        - range
        - title
        - header rows

    This function simply slices those cells from the workbook.
    """

    tables: list[TableRegion] = []

    for table in analysis.get("tables", []):

        worksheet = _find_sheet(
            workbook,
            table["sheet"],
        )

        if worksheet is None:
            continue

        start_row, start_col, end_row, end_col = _parse_excel_range(
            table["range"]
        )

        region = _build_table_region(
            worksheet=worksheet,
            title=table.get("title"),
            start_row=start_row,
            end_row=end_row,
            start_col=start_col,
            end_col=end_col,
            metadata=table,
        )

        tables.append(region)

    return tables


# ==========================================================
# Region Builder
# ==========================================================

def _build_table_region(
    worksheet: WorksheetFrame,
    title: str | None,
    start_row: int,
    end_row: int,
    start_col: int,
    end_col: int,
    metadata: dict[str, Any],
) -> TableRegion:

    cells: list[list[CellData]] = []

    for row in range(start_row, end_row + 1):

        row_cells = []

        if row - 1 >= len(worksheet.cells):
            continue

        worksheet_row = worksheet.cells[row - 1]

        for col in range(start_col, end_col + 1):

            if col - 1 >= len(worksheet_row):
                continue

            row_cells.append(
                worksheet_row[col - 1]
            )

        cells.append(row_cells)

    dataframe = _cells_to_dataframe(
        cells,
        metadata.get("header_rows", []),
    )

    return TableRegion(
        sheet_name=worksheet.name,
        start_row=start_row,
        end_row=end_row,
        start_column=start_col,
        end_column=end_col,
        cells=cells,
        dataframe=dataframe,
        title=title,
        notes=[],
    )


# ==========================================================
# DataFrame Builder
# ==========================================================

def _cells_to_dataframe(
    cells: list[list[CellData]],
    header_rows: list[int],
) -> pd.DataFrame:

    if not cells:
        return pd.DataFrame()

    if not header_rows:

        data = [
            [cell.value for cell in row]
            for row in cells
        ]

        return pd.DataFrame(data)

    relative_header = header_rows[0] - cells[0][0].row

    relative_header = max(relative_header, 0)

    header = [
        "" if c.value is None else str(c.value)
        for c in cells[relative_header]
    ]

    data_rows = cells[relative_header + 1 :]

    rows = []

    for row in data_rows:

        rows.append([
            cell.value
            for cell in row
        ])

    return pd.DataFrame(
        rows,
        columns=header,
    )


# ==========================================================
# Worksheet Lookup
# ==========================================================

def _find_sheet(
    workbook: WorkbookFrame,
    name: str,
) -> WorksheetFrame | None:

    for sheet in workbook.sheets:

        if sheet.name == name:
            return sheet

    return None


# ==========================================================
# Excel Range Parsing
# ==========================================================

_RANGE_RE = re.compile(
    r"([A-Z]+)(\d+):([A-Z]+)(\d+)"
)


def _parse_excel_range(
    excel_range: str,
) -> tuple[int, int, int, int]:

    match = _RANGE_RE.fullmatch(
        excel_range.strip()
    )

    if not match:
        raise ValueError(
            f"Invalid range: {excel_range}"
        )

    start_col = _letters_to_number(
        match.group(1)
    )

    start_row = int(match.group(2))

    end_col = _letters_to_number(
        match.group(3)
    )

    end_row = int(match.group(4))

    return (
        start_row,
        start_col,
        end_row,
        end_col,
    )


def _letters_to_number(
    letters: str,
) -> int:

    value = 0

    for c in letters:

        value *= 26
        value += ord(c.upper()) - 64

    return value