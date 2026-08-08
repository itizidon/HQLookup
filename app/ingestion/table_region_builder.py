from __future__ import annotations

import pandas as pd

from app.ingestion.workbook_models import (
    WorksheetFrame,
    TableRegion,
    DetectedTable,
)


def build_table_regions(
    worksheet: WorksheetFrame,
    detected_tables: list[DetectedTable],
) -> list[TableRegion]:
    """
    Converts DetectedTables into fully-populated TableRegions.

    This function extracts:

    - CellData
    - DataFrame
    - title
    - notes

    It does NOT call the LLM.
    """

    table_regions: list[TableRegion] = []

    for table in detected_tables:

        cells = _extract_cells(
            worksheet,
            table.start_row,
            table.end_row,
            table.start_column,
            table.end_column,
        )

        dataframe = _cells_to_dataframe(cells)

        notes = _extract_notes(
            worksheet,
            table.start_row,
        )

        region = TableRegion(
            sheet_name=worksheet.name,
            start_row=table.start_row,
            end_row=table.end_row,
            start_column=table.start_column,
            end_column=table.end_column,
            cells=cells,
            dataframe=dataframe,
            title=table.title,
            notes=notes,
        )

        table_regions.append(region)

    worksheet.table_regions = table_regions

    return table_regions


def _extract_cells(
    worksheet: WorksheetFrame,
    start_row: int,
    end_row: int,
    start_column: int,
    end_column: int,
):
    """
    Returns the rectangular slice of CellData objects.
    """

    extracted = []

    for row in range(start_row, end_row + 1):

        if row - 1 >= len(worksheet.cells):
            continue

        worksheet_row = worksheet.cells[row - 1]

        current = []

        for col in range(start_column, end_column + 1):

            if col - 1 >= len(worksheet_row):
                continue

            current.append(
                worksheet_row[col - 1]
            )

        extracted.append(current)

    return extracted


def _cells_to_dataframe(cells):

    rows = []

    for row in cells:

        values = []

        for cell in row:

            values.append(cell.value)

        rows.append(values)

    if not rows:
        return pd.DataFrame()

    header = rows[0]

    data = rows[1:]

    return pd.DataFrame(data, columns=header)


def _extract_notes(
    worksheet: WorksheetFrame,
    table_start_row: int,
) -> list[str]:
    """
    Extracts non-empty rows immediately above the table.

    Stops after encountering a blank row.

    Usually captures titles/subtitles.
    """

    notes = []

    current = table_start_row - 1

    while current >= 1:

        row = worksheet.cells[current - 1]

        text = " ".join(
            str(cell.value).strip()
            for cell in row
            if cell.value not in (None, "")
        ).strip()

        if not text:
            break

        notes.insert(0, text)

        current -= 1

    return notes