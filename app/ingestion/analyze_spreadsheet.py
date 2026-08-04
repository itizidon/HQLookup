import json
import pandas as pd
from openai import OpenAI

def extract_spreadsheet_to_text(file_path: str) -> str:
    """
    Reads all sheets from an Excel workbook and converts them into a 
    text representation containing sheet names and row/column indices.
    """
    excel_data = pd.ExcelFile(file_path)
    sheet_texts = []
    
    for sheet_name in excel_data.sheet_names:
        # Read the sheet without assuming a header row so raw grid structure is preserved
        df = pd.read_excel(excel_data, sheet_name=sheet_name, header=None)
        
        sheet_texts.append(f"=== SHEET: {sheet_name} ===\n")
        # to_string handles layout formatting well for LLMs
        sheet_texts.append(df.to_string(na_rep="", index=True, header=True))
        sheet_texts.append("\n\n")
        
    return "".join(sheet_texts)

def analyze_spreadsheet_with_llm(file_path: str, client: OpenAI = None) -> dict:
    """
    Passes the spreadsheet contents and structural prompt to the LLM 
    and returns the parsed JSON response.
    """
    if client is None:
        client = OpenAI() # Uses OPENAI_API_KEY environment variable by default

    # Step 1: Extract contents of the spreadsheet file
    spreadsheet_text = extract_spreadsheet_to_text(file_path)

    # Step 2: Construct the prompt incorporating your schema and rules
    prompt = f"""
You are an expert data extraction and spreadsheet analysis assistant. Your task is to analyze the provided spreadsheet data (sheet names, cell contents, or structural text dumps) and identify the logical structure of the workbook.

Your goal is to detect:
- All distinct tables (even if they are not formatted as Excel Tables).
- The cell range occupied by each table.
- The column headers for each table.
- Any charts or visualizations.
- Important summary metrics or findings.

Return your response as a single, valid JSON object and nothing else. Do not include markdown code blocks (such as ```json), explanations, or conversational text.

The JSON object must strictly conform to the following schema:
{{
  "spreadsheet_summary": "A brief overview of the workbook contents.",
  "tables": [
    {{
      "table_name": "Name or inferred title of the table",
      "cell_range": "e.g., A1:D15",
      "column_headers": ["Header1", "Header2"],
      "description": "Brief description of the table contents"
    }}
  ],
  "charts": [
    {{
      "chart_name": "Name or inferred title of the chart",
      "chart_type": "e.g., Bar, Line, Pie",
      "location_or_range": "Cell location if identifiable",
      "description": "Brief description of what the chart visualizes"
    }}
  ],
  "key_findings": [
    "Notable data insight or summary total"
  ]
}

Analyze the following spreadsheet content:
{spreadsheet_text}
"""

    # Step 3: Call the LLM with JSON mode enabled for strict parsing guarantees
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a precise data extraction assistant that outputs strictly valid JSON objects."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )

    # Step 4: Parse and return the JSON payload
    raw_content = response.choices[0].message.content
    return json.loads(raw_content)