from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.ingestion.workbook_models import WorkbookFrame

client = OpenAI()


def analyze_workbook_with_llm(
    workbook: WorkbookFrame,
    user_context: str = "",
) -> dict[str, Any]:
    """
    Analyze an entire workbook and return structured JSON describing
    all tables, charts, and worksheet layout.

    This function DOES NOT determine chunking.
    """

    workbook_text = serialize_workbook_for_llm(workbook)

    prompt = f"""
You are an expert spreadsheet analyst.

Your task is to analyze the workbook.

Determine:

- every logical table
- every Excel table
- every chart
- summary blocks
- notes blocks
- table titles
- header rows
- first data row
- last data row

Do NOT determine chunking.

User Context:
{user_context or "None"}

Workbook

{workbook_text}

Return ONLY valid JSON.

Schema:

{{
  "tables": [
    {{
      "id": "string",
      "sheet": "string",
      "title": "string",
      "range": "A1:H25",
      "header_rows": [1],
      "data_start_row": 2,
      "data_end_row": 25,
      "table_type": "entity|summary|pivot|matrix|report|unknown",
      "description": "string"
    }}
  ],

  "charts": [
    {{
      "sheet": "string",
      "title": "string",
      "chart_type": "string"
    }}
  ]
}}
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt,
        temperature=0,
    )

    return json.loads(response.output_text)