from __future__ import annotations

from collections import deque

from app.ingestion.workbook_models import WorkbookFrame, WorksheetFrame, DetectedTable


# ----------------------------------------------------------
# Tunable parameters
# ----------------------------------------------------------

MAX_BLANK_ROWS = 2          # stop after two consecutive blank rows
MIN_ROWS = 2                # minimum rows in a table
MIN_COLS = 2                # minimum columns in a table
MIN_FILLED_RATIO = 0.35     # how dense a row must be


# ----------------------------------------------------------
# Public API
# ----------------------------------------------------------

def detect_tables(workbook: WorkbookFrame) -> list[DetectedTable]:
    tables: list[DetectedTable] = []

    for sheet in workbook.visible_sheets():

        # 1. Real Excel tables
        tables.extend(_detect_excel_tables(sheet))

        # 2. Heuristic tables
        tables.extend(_detect_dense_regions(sheet))

    return _merge_tables(tables)


# ----------------------------------------------------------
# Excel Tables
# ----------------------------------------------------------

def _detect_excel_tables(sheet: WorksheetFrame) -> list[DetectedTable]:

    tables = []

    for table in sheet.excel_tables:

        ref = table["range"]

        start, end = ref.split(":")

        sr, sc = _coordinate_to_index(start)
        er, ec = _coordinate_to_index(end)

        tables.append(
            DetectedTable(
                sheet_name=sheet.name,
                start_row=sr,
                end_row=er,
                start_column=sc,
                end_column=ec,
                title=table["name"],
                confidence=1.0,
                source="excel_table",
            )
        )

    return tables


# ----------------------------------------------------------
# Dense Region Detection
# ----------------------------------------------------------

def _detect_dense_regions(sheet: WorksheetFrame):

    tables = []

    visited = set()

    for row in range(1, sheet.max_rows + 1):

        if row in visited:
            continue

        if not _row_has_data(sheet, row):
            continue

        start = row
        end = row

        blank_rows = 0

        while end <= sheet.max_rows:

            if _row_has_data(sheet, end):
                blank_rows = 0
                visited.add(end)
                end += 1
            else:
                blank_rows += 1

                if blank_rows >= MAX_BLANK_ROWS:
                    break

                end += 1

        end = end - blank_rows

        if end < start:
            continue

        left, right = _column_bounds(sheet, start, end)

        if right - left + 1 < MIN_COLS:
            continue

        if end - start + 1 < MIN_ROWS:
            continue

        density = _density(sheet, start, end, left, right)

        if density < MIN_FILLED_RATIO:
            continue

        tables.append(
            DetectedTable(
                sheet_name=sheet.name,
                start_row=start,
                end_row=end,
                start_column=left,
                end_column=right,
                title=None,
                confidence=min(0.95, density),
                source="heuristic",
            )
        )

    return tables


# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------

def _row_has_data(sheet: WorksheetFrame, row: int):

    if row > len(sheet.cells):
        return False

    for cell in sheet.cells[row - 1]:

        if cell.hidden:
            continue

        if cell.value is None:
            continue

        if str(cell.value).strip() == "":
            continue

        return True

    return False


def _column_bounds(sheet, start_row, end_row):

    left = 10_000
    right = 0

    for r in range(start_row, end_row + 1):

        if r > len(sheet.cells):
            continue

        for cell in sheet.cells[r - 1]:

            if cell.hidden:
                continue

            if cell.value is None:
                continue

            if str(cell.value).strip() == "":
                continue

            left = min(left, cell.column)
            right = max(right, cell.column)

    return left, right


def _density(sheet, sr, er, sc, ec):

    total = 0
    filled = 0

    for r in range(sr, er + 1):

        if r > len(sheet.cells):
            continue

        for cell in sheet.cells[r - 1]:

            if cell.column < sc:
                continue

            if cell.column > ec:
                continue

            total += 1

            if cell.value is None:
                continue

            if str(cell.value).strip() == "":
                continue

            filled += 1

    if total == 0:
        return 0

    return filled / total


# ----------------------------------------------------------
# Merge overlapping regions
# ----------------------------------------------------------

def _merge_tables(tables: list[DetectedTable]):

    merged = []

    for table in sorted(
        tables,
        key=lambda t: (
            t.sheet_name,
            t.start_row,
            t.start_column,
        ),
    ):

        overlap = None

        for existing in merged:

            if existing.sheet_name != table.sheet_name:
                continue

            if (
                table.start_row <= existing.end_row
                and table.end_row >= existing.start_row
                and table.start_column <= existing.end_column
                and table.end_column >= existing.start_column
            ):
                overlap = existing
                break

        if overlap is None:
            merged.append(table)
            continue

        overlap.start_row = min(overlap.start_row, table.start_row)
        overlap.end_row = max(overlap.end_row, table.end_row)
        overlap.start_column = min(overlap.start_column, table.start_column)
        overlap.end_column = max(overlap.end_column, table.end_column)

        overlap.confidence = max(
            overlap.confidence,
            table.confidence,
        )

        if table.source == "excel_table":
            overlap.source = "excel_table"

    return merged


# ----------------------------------------------------------
# Coordinate parser
# ----------------------------------------------------------

def _coordinate_to_index(coord: str):

    letters = ""

    numbers = ""

    for c in coord:

        if c.isalpha():
            letters += c.upper()
        else:
            numbers += c

    column = 0

    for ch in letters:
        column = column * 26 + ord(ch) - 64

    return int(numbers), column