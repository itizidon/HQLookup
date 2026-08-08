from io import StringIO


def serialize_workbook_for_llm(
    workbook: WorkbookFrame,
    max_rows: int = 100,
    max_columns: int = 30,
) -> str:
    """
    Converts WorkbookFrame into a compact textual representation
    suitable for an LLM.
    """

    out = StringIO()

    out.write(f"Workbook: {workbook.filename}\n")

    for sheet in workbook.visible_sheets():

        out.write("\n")
        out.write("=" * 80)
        out.write("\n")

        out.write(f"Sheet: {sheet.name}\n")

        out.write(
            f"Dimensions: {sheet.max_rows} rows x {sheet.max_columns} columns\n"
        )

        if sheet.excel_tables:
            out.write(f"Excel Tables:\n")
            for table in sheet.excel_tables:
                out.write(
                    f"  - {table['name']} ({table['range']})\n"
                )

        out.write("\nCells\n")

        rows = sheet.cells[:max_rows]

        for row in rows:

            values = []

            for cell in row[:max_columns]:

                if cell.value is None:
                    values.append("")
                else:
                    values.append(str(cell.value))

            out.write("|".join(values))
            out.write("\n")

        if sheet.max_rows > max_rows:
            out.write(
                f"... ({sheet.max_rows-max_rows} more rows)\n"
            )

    return out.getvalue()